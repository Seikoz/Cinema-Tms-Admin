"""Database-backed authentication and signing-key management for the license manager."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import bcrypt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from license_admin.contract import (
    HARDWARE_REQUEST_SCHEMA,
    LICENSE_SCHEMA,
    PRODUCT_ID,
    TRUSTED_PUBLIC_KEY_PEM,
    canonical_payload,
    trusted_issuer_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(os.getenv("CINEMA_TMS_ADMIN_DATA_DIR", str(PROJECT_ROOT / "data")))
HARDWARE_KEY_PATTERN = re.compile(r"^[0-9A-F]{4}(?:-[0-9A-F]{4}){7}$")
HARDWARE_KEY_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
DPAPI_ENTROPY = hashlib.sha256(b"Cinema-TMS-License-Authority-DPAPI-v1").digest()
KEY_WRAP_AAD = b"Cinema-TMS-License-Authority-DB-v1"
MAX_LOGIN_FAILURES = 5
LOCKOUT_MINUTES = 15
ROLES = {"admin", "operator", "viewer"}


class LegacyKeyMigrationRequired(ValueError):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    username: str
    role: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _dpapi_transform(value: bytes, *, protect: bool) -> bytes:
    """Read the previous beta's DPAPI key only for one-time DB migration."""
    if os.name != "nt":
        raise ValueError("기존 Windows 보호 발급키는 Windows에서만 이전할 수 있습니다.")
    operation = "Protect" if protect else "Unprotect"
    entropy = base64.b64encode(DPAPI_ENTROPY).decode("ascii")
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Security;"
        "$value=[Convert]::FromBase64String([Console]::In.ReadToEnd());"
        f"$entropy=[Convert]::FromBase64String('{entropy}');"
        "$scope=[Security.Cryptography.DataProtectionScope]::CurrentUser;"
        f"$result=[Security.Cryptography.ProtectedData]::{operation}($value,$entropy,$scope);"
        "[Console]::Out.Write([Convert]::ToBase64String($result))"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        input=base64.b64encode(value).decode("ascii"), capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30,
    )
    if result.returncode != 0:
        raise ValueError("기존 Windows 보호 발급키를 현재 계정에서 읽을 수 없습니다.") from RuntimeError(result.stderr.strip())
    try:
        return base64.b64decode(result.stdout.strip(), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("기존 Windows 보호 발급키 결과를 읽을 수 없습니다.") from exc


def _validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("로그인 계정은 영문, 숫자, 마침표, 밑줄, 하이픈으로 3~40자까지 입력하세요.")
    return username


def _validate_password(password: str) -> None:
    if not password:
        raise ValueError("비밀번호를 입력하세요.")


def _derive_wrap_key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))


def _wrap_private_key(private_der: bytes, password: str) -> tuple[bytes, bytes, bytes]:
    salt, nonce = os.urandom(16), os.urandom(12)
    encrypted = AESGCM(_derive_wrap_key(password, salt)).encrypt(nonce, private_der, KEY_WRAP_AAD)
    return salt, nonce, encrypted


def _unwrap_private_key(salt: bytes, nonce: bytes, encrypted: bytes, password: str) -> bytes:
    try:
        return AESGCM(_derive_wrap_key(password, salt)).decrypt(nonce, encrypted, KEY_WRAP_AAD)
    except Exception as exc:
        raise ValueError("계정의 발급키를 해제할 수 없습니다. DB가 손상되었을 수 있습니다.") from exc


def normalize_hardware_key(value: str) -> str:
    normalized = "".join(str(value).translate(HARDWARE_KEY_DASHES).upper().split())
    if re.fullmatch(r"[0-9A-F]{32}", normalized):
        normalized = "-".join(normalized[index:index + 4] for index in range(0, 32, 4))
    if not HARDWARE_KEY_PATTERN.fullmatch(normalized):
        raise ValueError("하드웨어 키 파일의 클라이언트 하드웨어 키 형식이 올바르지 않습니다.")
    return normalized


def extended_license_expiry(previous_expiry: date, today: date | None = None) -> date:
    """Extend by one year without overflowing Python's maximum date."""
    base = max(previous_expiry, today or date.today())
    extension = timedelta(days=365)
    if (date.max - base).days < extension.days:
        return date.max
    return base + extension


def read_hardware_request(path: Path) -> dict:
    try:
        request = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("하드웨어 키 파일을 읽을 수 없습니다.") from exc
    if not isinstance(request, dict):
        raise ValueError("하드웨어 키 파일 형식이 올바르지 않습니다.")
    checksum = str(request.pop("checksum", "")).lower()
    expected = hashlib.sha256(canonical_payload(request)).hexdigest()
    if not checksum or checksum != expected:
        raise ValueError("하드웨어 키 파일이 손상되었거나 변경되었습니다.")
    if request.get("schema") != HARDWARE_REQUEST_SCHEMA or request.get("product") != PRODUCT_ID:
        raise ValueError("Cinema TMS용 하드웨어 키 파일이 아닙니다.")
    if request.get("issuer_id") != trusted_issuer_id():
        raise ValueError("이 라이선스 발급 시스템과 호환되지 않는 하드웨어 키 파일입니다.")
    if not str(request.get("request_id", "")).strip() or not str(request.get("created_at", "")).strip():
        raise ValueError("하드웨어 키 파일에 필수 정보가 없습니다.")
    request["hardware_key"] = normalize_hardware_key(request.get("hardware_key", ""))
    if request.get("request_type") == "hardware_rebind":
        request["previous_hardware_key"] = normalize_hardware_key(request.get("previous_hardware_key", ""))
    request["checksum"] = checksum
    return request


class LicenseAuthority:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.dpapi_key_path = self.data_dir / "license_private_key.dpapi"
        self.legacy_private_key_path = self.data_dir / "license_private_key.pem"
        self.legacy_public_key_path = self.data_dir / "license_public_key.pem"
        self.database_path = self.data_dir / "licenses.db"
        self._private_key: Ed25519PrivateKey | None = None
        self._current_user: AuthenticatedUser | None = None
        self._prepare_database()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path, timeout=15)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _prepare_database(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS licenses (
                    license_id TEXT PRIMARY KEY, customer TEXT NOT NULL, cinema TEXT NOT NULL,
                    machine_code TEXT NOT NULL, valid_from TEXT NOT NULL, expires_on TEXT NOT NULL,
                    issued_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                    file_path TEXT NOT NULL DEFAULT '', supersedes TEXT NOT NULL DEFAULT '',
                    operator TEXT NOT NULL DEFAULT '', workstation TEXT NOT NULL DEFAULT '',
                    auditorium_limit INTEGER NOT NULL DEFAULT 0,
                    action TEXT NOT NULL DEFAULT 'issue'
                )"""
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(licenses)")}
            if "operator" not in columns:
                db.execute("ALTER TABLE licenses ADD COLUMN operator TEXT NOT NULL DEFAULT ''")
            if "workstation" not in columns:
                db.execute("ALTER TABLE licenses ADD COLUMN workstation TEXT NOT NULL DEFAULT ''")
            if "auditorium_limit" not in columns:
                db.execute("ALTER TABLE licenses ADD COLUMN auditorium_limit INTEGER NOT NULL DEFAULT 0")
            if "action" not in columns:
                db.execute("ALTER TABLE licenses ADD COLUMN action TEXT NOT NULL DEFAULT 'issue'")
                db.execute("UPDATE licenses SET action='renewal' WHERE supersedes<>''")
            db.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash BLOB NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    failed_attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, last_login TEXT NOT NULL DEFAULT ''
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS user_key_wraps (
                    user_id INTEGER PRIMARY KEY, salt BLOB NOT NULL, nonce BLOB NOT NULL,
                    encrypted_key BLOB NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '', action TEXT NOT NULL,
                    success INTEGER NOT NULL, detail TEXT NOT NULL DEFAULT '',
                    workstation TEXT NOT NULL DEFAULT ''
                )"""
            )
            db.commit()

    @property
    def has_users(self) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    @property
    def initialized(self) -> bool:
        return self.has_users

    @property
    def requires_migration(self) -> bool:
        return not self.has_users and (self.dpapi_key_path.is_file() or self.legacy_private_key_path.is_file())

    @property
    def legacy_key_needs_password(self) -> bool:
        if not self.legacy_private_key_path.is_file() or self.dpapi_key_path.is_file():
            return False
        try:
            serialization.load_pem_private_key(self.legacy_private_key_path.read_bytes(), password=None)
            return False
        except (OSError, TypeError, ValueError):
            return True

    @property
    def unlocked(self) -> bool:
        return self._private_key is not None and self._current_user is not None

    @property
    def current_user(self) -> AuthenticatedUser | None:
        return self._current_user

    def import_database(self, source_path: Path) -> None:
        """Import an existing authority DB after validating its minimum trust state."""
        if self.has_users:
            raise ValueError("현재 라이선스 관리자 DB에 이미 로그인 계정이 있습니다.")
        source_path = Path(source_path).resolve()
        if source_path == self.database_path.resolve():
            raise ValueError("현재 사용 중인 관리자 DB와 같은 파일입니다.")
        if not source_path.is_file():
            raise ValueError("선택한 관리자 DB 파일을 찾을 수 없습니다.")
        temporary = self.data_dir / f".licenses-import-{uuid.uuid4().hex}.db"
        source = destination = None
        try:
            source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True, timeout=15)
            integrity = source.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("선택한 관리자 DB의 무결성 검사에 실패했습니다.")
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"users", "user_key_wraps", "licenses", "audit_logs"}
            if not required.issubset(tables):
                raise ValueError("선택한 파일은 Cinema TMS 라이선스 관리자 DB가 아닙니다.")
            usable_admin = source.execute(
                """SELECT 1 FROM users AS u
                   JOIN user_key_wraps AS k ON k.user_id=u.id
                   WHERE u.role='admin' AND u.active=1 LIMIT 1"""
            ).fetchone()
            if usable_admin is None:
                raise ValueError("선택한 관리자 DB에 발급키가 연결된 활성 관리자 계정이 없습니다.")
            destination = sqlite3.connect(temporary, timeout=15)
            source.backup(destination)
            destination.commit()
            destination.close()
            destination = None
            source.close()
            source = None
            os.replace(temporary, self.database_path)
            self._prepare_database()
        except sqlite3.DatabaseError as exc:
            raise ValueError("선택한 관리자 DB를 읽거나 가져올 수 없습니다.") from exc
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()
            temporary.unlink(missing_ok=True)

    def _validate_authorized_key(self, key: object) -> Ed25519PrivateKey:
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("지원하지 않는 개인키 형식입니다.")
        trusted = serialization.load_pem_public_key(TRUSTED_PUBLIC_KEY_PEM)
        if not isinstance(trusted, Ed25519PublicKey):
            raise ValueError("TMS 내부 검증키가 올바르지 않습니다.")
        actual_raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        trusted_raw = trusted.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        if actual_raw != trusted_raw:
            raise ValueError("이 발급키는 현재 Cinema TMS 검증키에 등록된 키가 아닙니다.")
        return key

    def _load_migration_key(self, legacy_password: str | None) -> Ed25519PrivateKey:
        if self.dpapi_key_path.is_file():
            try:
                private_der = _dpapi_transform(self.dpapi_key_path.read_bytes(), protect=False)
                return self._validate_authorized_key(serialization.load_der_private_key(private_der, password=None))
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError("현재 Windows 사용자로 기존 발급키를 읽을 수 없습니다.") from exc
        if self.legacy_private_key_path.is_file():
            try:
                key = serialization.load_pem_private_key(
                    self.legacy_private_key_path.read_bytes(),
                    password=legacy_password.encode("utf-8") if legacy_password is not None else None,
                )
            except (TypeError, ValueError) as exc:
                if legacy_password is None:
                    raise LegacyKeyMigrationRequired("기존 관리자 키 비밀번호가 필요합니다.") from exc
                raise ValueError("기존 관리자 키 비밀번호가 올바르지 않습니다.") from exc
            except OSError as exc:
                raise ValueError("기존 발급키 파일을 읽을 수 없습니다.") from exc
            return self._validate_authorized_key(key)
        raise ValueError(
            "이전할 라이선스 발급키가 없습니다. 기존 라이선스 관리자 PC의 licenses.db 또는 "
            "license_private_key.dpapi/.pem 파일이 필요합니다."
        )

    def bootstrap_admin(self, username: str, password: str, legacy_password: str | None = None) -> None:
        if self.has_users:
            raise ValueError("관리자 계정이 이미 등록되어 있습니다.")
        username = _validate_username(username)
        _validate_password(password)
        key = self._load_migration_key(legacy_password)
        private_der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        salt, nonce, encrypted = _wrap_private_key(private_der, password)
        now = _utc_now().isoformat()
        with closing(self._connect()) as db:
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                (username, bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)), "admin", now),
            )
            db.execute(
                "INSERT INTO user_key_wraps(user_id,salt,nonce,encrypted_key) VALUES(?,?,?,?)",
                (cursor.lastrowid, salt, nonce, encrypted),
            )
            db.commit()
        self.dpapi_key_path.unlink(missing_ok=True)
        self.legacy_private_key_path.unlink(missing_ok=True)
        self.legacy_public_key_path.unlink(missing_ok=True)
        self._audit(username, "bootstrap_admin", True, "기존 발급키를 로그인 DB 보호 방식으로 이전")

    def authenticate(self, username: str, password: str) -> AuthenticatedUser:
        username = username.strip()
        now = _utc_now()
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            if row is None:
                self._audit(username, "login", False, "등록되지 않은 계정")
                raise ValueError("계정 또는 비밀번호가 올바르지 않습니다.")
            locked_until = datetime.fromisoformat(row["locked_until"]) if row["locked_until"] else None
            if locked_until and locked_until > now:
                self._audit(row["username"], "login", False, "잠긴 계정 접근")
                remaining = max(1, int((locked_until - now).total_seconds() // 60) + 1)
                raise ValueError(f"로그인 실패가 누적되어 계정이 잠겼습니다. 약 {remaining}분 후 다시 시도하세요.")
            valid = bool(row["active"]) and bcrypt.checkpw(password.encode("utf-8"), bytes(row["password_hash"]))
            if not valid:
                failures = int(row["failed_attempts"]) + 1
                lock_value = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat() if failures >= MAX_LOGIN_FAILURES else ""
                db.execute("UPDATE users SET failed_attempts=?,locked_until=? WHERE id=?", (failures, lock_value, row["id"]))
                db.commit()
                self._audit(row["username"], "login", False, "비밀번호 오류 또는 비활성 계정")
                raise ValueError("계정 또는 비밀번호가 올바르지 않습니다.")
            wrap = db.execute("SELECT * FROM user_key_wraps WHERE user_id=?", (row["id"],)).fetchone()
            key = None
            if wrap is not None:
                private_der = _unwrap_private_key(bytes(wrap["salt"]), bytes(wrap["nonce"]), bytes(wrap["encrypted_key"]), password)
                key = self._validate_authorized_key(serialization.load_der_private_key(private_der, password=None))
            db.execute("UPDATE users SET failed_attempts=0,locked_until='',last_login=? WHERE id=?", (now.isoformat(), row["id"]))
            db.commit()
        self._private_key = key
        self._current_user = AuthenticatedUser(int(row["id"]), str(row["username"]), str(row["role"]))
        self._audit(self._current_user.username, "login", True, self._current_user.role)
        return self._current_user

    def logout(self) -> None:
        if self._current_user:
            self._audit(self._current_user.username, "logout", True, "")
        self._private_key = None
        self._current_user = None

    def _require_roles(self, *roles: str) -> AuthenticatedUser:
        if not self._current_user or self._current_user.role not in roles:
            raise ValueError("현재 로그인 계정에 이 작업을 수행할 권한이 없습니다.")
        return self._current_user

    def create_user(self, username: str, password: str, role: str) -> None:
        actor = self._require_roles("admin")
        username = _validate_username(username)
        _validate_password(password)
        if role not in ROLES:
            raise ValueError("지원하지 않는 계정 역할입니다.")
        if role in {"admin", "operator"} and not self._private_key:
            raise ValueError("현재 관리자 계정에서 발급키를 해제할 수 없습니다.")
        now = _utc_now().isoformat()
        try:
            with closing(self._connect()) as db:
                cursor = db.execute(
                    "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                    (username, bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)), role, now),
                )
                if role in {"admin", "operator"}:
                    private_der = self._private_key.private_bytes(
                        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                    )
                    salt, nonce, encrypted = _wrap_private_key(private_der, password)
                    db.execute(
                        "INSERT INTO user_key_wraps(user_id,salt,nonce,encrypted_key) VALUES(?,?,?,?)",
                        (cursor.lastrowid, salt, nonce, encrypted),
                    )
                db.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("이미 등록된 로그인 계정입니다.") from exc
        self._audit(actor.username, "create_user", True, f"{username}:{role}")

    def change_password(self, current_password: str, new_password: str) -> None:
        actor = self._require_roles("admin", "operator", "viewer")
        _validate_password(new_password)
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (actor.user_id,)).fetchone()
            if row is None or not bcrypt.checkpw(current_password.encode("utf-8"), bytes(row["password_hash"])):
                self._audit(actor.username, "change_password", False, "현재 비밀번호 오류")
                raise ValueError("현재 비밀번호가 올바르지 않습니다.")
            db.execute(
                "UPDATE users SET password_hash=?,failed_attempts=0,locked_until='' WHERE id=?",
                (bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)), actor.user_id),
            )
            if actor.role in {"admin", "operator"}:
                if not self._private_key:
                    raise ValueError("현재 계정의 발급키를 해제할 수 없습니다.")
                private_der = self._private_key.private_bytes(
                    serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                )
                salt, nonce, encrypted = _wrap_private_key(private_der, new_password)
                db.execute(
                    "UPDATE user_key_wraps SET salt=?,nonce=?,encrypted_key=? WHERE user_id=?",
                    (salt, nonce, encrypted, actor.user_id),
                )
            db.commit()
        self._audit(actor.username, "change_password", True, "")

    def users(self) -> list[dict]:
        self._require_roles("admin")
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT id,username,role,active,failed_attempts,locked_until,created_at,last_login FROM users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_user_active(self, user_id: int, active: bool) -> None:
        actor = self._require_roles("admin")
        if user_id == actor.user_id and not active:
            raise ValueError("현재 로그인한 관리자 계정은 비활성화할 수 없습니다.")
        with closing(self._connect()) as db:
            cursor = db.execute(
                "UPDATE users SET active=?,failed_attempts=0,locked_until='' WHERE id=?",
                (1 if active else 0, user_id),
            )
            db.commit()
        if cursor.rowcount != 1:
            raise ValueError("계정을 찾을 수 없습니다.")
        self._audit(actor.username, "set_user_active", True, f"user_id={user_id},active={active}")

    def _audit(self, username: str, action: str, success: bool, detail: str) -> None:
        with closing(self._connect()) as db:
            db.execute(
                "INSERT INTO audit_logs(created_at,username,action,success,detail,workstation) VALUES(?,?,?,?,?,?)",
                (_utc_now().isoformat(), username, action, 1 if success else 0, detail[:500], platform.node()),
            )
            db.commit()

    def audit_records(self, limit: int = 300) -> list[dict]:
        self._require_roles("admin")
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [dict(row) for row in rows]

    def issue(self, *, customer: str, cinema: str, hardware_key: str, valid_from: date,
              expires_on: date, auditorium_limit: int, destination: Path, supersedes: str = "") -> dict:
        actor = self._require_roles("admin", "operator")
        if not self._private_key:
            raise ValueError("현재 계정에는 라이선스 발급 권한이 없습니다.")
        customer, cinema = customer.strip(), cinema.strip()
        hardware_key = normalize_hardware_key(hardware_key)
        if not customer or not cinema:
            raise ValueError("고객명과 영화관명을 입력하세요.")
        if expires_on < valid_from:
            raise ValueError("만료일은 시작일 이후여야 합니다.")
        try:
            auditorium_limit = int(auditorium_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("상영관 수 제한은 1 이상의 숫자로 입력하세요.") from exc
        if auditorium_limit < 1:
            raise ValueError("상영관 수 제한은 1 이상이어야 합니다.")
        issued_at = _utc_now().isoformat()
        action = "renewal" if supersedes else "issue"
        payload = {
            "schema": LICENSE_SCHEMA, "product": PRODUCT_ID, "license_id": str(uuid.uuid4()),
            "customer": customer, "cinema": cinema, "hardware_key": hardware_key,
            "valid_from": valid_from.isoformat(), "expires_on": expires_on.isoformat(),
            "features": ["core"], "issued_at": issued_at,
            "auditorium_limit": auditorium_limit,
        }
        envelope = {"payload": payload, "signature": base64.b64encode(self._private_key.sign(canonical_payload(payload))).decode("ascii")}
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with closing(self._connect()) as db:
            db.execute(
                """INSERT INTO licenses
                   (license_id,customer,cinema,machine_code,valid_from,expires_on,issued_at,
                    status,file_path,supersedes,operator,workstation,auditorium_limit,action)
                   VALUES(?,?,?,?,?,?,?,'active',?,?,?,?,?,?)""",
                (payload["license_id"], customer, cinema, hardware_key, payload["valid_from"],
                 payload["expires_on"], issued_at, str(destination), supersedes, actor.username,
                 platform.node(), auditorium_limit, action),
            )
            if supersedes:
                db.execute("UPDATE licenses SET status='renewed' WHERE license_id=? AND status='active'", (supersedes,))
            db.commit()
        self._audit(
            actor.username, "renew_license" if supersedes else "issue_license", True,
            f"{payload['license_id']};auditorium_limit={auditorium_limit}",
        )
        return envelope

    def revoke(self, license_id: str) -> None:
        actor = self._require_roles("admin")
        with closing(self._connect()) as db:
            cursor = db.execute("UPDATE licenses SET status='revoked' WHERE license_id=?", (license_id,))
            db.commit()
        if cursor.rowcount != 1:
            raise ValueError("발급 이력을 찾을 수 없습니다.")
        self._audit(actor.username, "revoke_license", True, license_id)

    def records(self) -> list[dict]:
        if not self._current_user:
            return []
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM licenses ORDER BY issued_at DESC, rowid DESC").fetchall()
        return [{**dict(row), "hardware_key": row["machine_code"]} for row in rows]

    def latest_license_for_hardware_key(self, hardware_key: str, *, active_only: bool = False) -> dict | None:
        """Return the newest locally issued license for a normalized TMS key."""
        if not self._current_user:
            return None
        hardware_key = normalize_hardware_key(hardware_key)
        status_clause = " AND status='active'" if active_only else ""
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                f"""SELECT * FROM licenses
                    WHERE machine_code=?{status_clause}
                    ORDER BY issued_at DESC, rowid DESC LIMIT 1""",
                (hardware_key,),
            ).fetchone()
        return {**dict(row), "hardware_key": row["machine_code"]} if row is not None else None
