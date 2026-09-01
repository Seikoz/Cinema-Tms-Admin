"""Authenticated GitHub Release updates for Cinema TMS Admin."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_REPOSITORY = "Seikoz/Cinema-Tms-Updates"
RELEASE_TAG_PREFIX = "admin-v"
GITHUB_API_VERSION = "2022-11-28"
MAX_UPDATE_BYTES = 512 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")


class GitHubUpdateError(RuntimeError):
    pass


class GitHubAuthenticationRequired(GitHubUpdateError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    api_url: str
    size: int


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    published_at: str
    package: ReleaseAsset
    checksum: ReleaseAsset


def version_key(value: str) -> tuple[int, int, int, int, int]:
    match = VERSION_PATTERN.fullmatch(str(value or "").strip().lower().removeprefix("v"))
    if not match:
        raise ValueError(f"지원하지 않는 버전 형식입니다: {value}")
    stage = {"a": 0, "b": 1, "rc": 2, None: 3}[match.group(4)]
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), stage, int(match.group(5) or 0)


def _headers(token: str, binary: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "User-Agent": "Cinema-TMS-Admin-Updater",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _open(request: Request, timeout: int = 30):
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code in {401, 403, 404}:
            raise GitHubAuthenticationRequired(
                "GitHub Release에 접근할 수 없습니다. 관리자 DB의 공용 업데이트 자격 증명을 갱신해야 합니다."
            ) from exc
        raise GitHubUpdateError(f"GitHub가 HTTP {exc.code} 오류를 반환했습니다.") from exc
    except (URLError, OSError) as exc:
        raise GitHubUpdateError(f"GitHub 연결에 실패했습니다: {exc}") from exc


def parse_update_releases(payload: object, current_version: str) -> UpdateRelease | None:
    if not isinstance(payload, list):
        raise GitHubUpdateError("GitHub Release 응답 형식이 올바르지 않습니다.")
    releases = []
    for item in payload:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name") or "")
        if not tag.startswith(RELEASE_TAG_PREFIX):
            continue
        version = tag.removeprefix(RELEASE_TAG_PREFIX)
        try:
            if version_key(version) <= version_key(current_version):
                continue
        except ValueError:
            continue
        package_name = f"Cinema-TMS-Admin-Update-{version}.zip"
        checksum_name = package_name + ".sha256"
        assets = {str(asset.get("name")): asset for asset in item.get("assets", []) if isinstance(asset, dict)}
        package, checksum = assets.get(package_name), assets.get(checksum_name)
        if not package or not checksum:
            continue
        package_url, checksum_url = str(package.get("url") or ""), str(checksum.get("url") or "")
        size = int(package.get("size") or 0)
        if not package_url.startswith("https://api.github.com/") or not checksum_url.startswith("https://api.github.com/"):
            continue
        if size <= 0 or size > MAX_UPDATE_BYTES:
            continue
        releases.append(UpdateRelease(
            version, str(item.get("published_at") or ""),
            ReleaseAsset(package_name, package_url, size),
            ReleaseAsset(checksum_name, checksum_url, int(checksum.get("size") or 0)),
        ))
    return max(releases, key=lambda release: version_key(release.version), default=None)


def check_for_update(current_version: str, token: str, repository: str | None = None) -> UpdateRelease | None:
    repo = (repository or os.getenv("TMS_ADMIN_GITHUB_REPOSITORY") or DEFAULT_REPOSITORY).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise GitHubUpdateError("GitHub 저장소 형식은 owner/repository 여야 합니다.")
    request = Request(f"https://api.github.com/repos/{repo}/releases?per_page=30", headers=_headers(token))
    with _open(request) as response:
        try:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise GitHubUpdateError("GitHub 응답 크기가 허용 범위를 초과했습니다.")
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubUpdateError("GitHub Release 정보를 해석할 수 없습니다.") from exc
    return parse_update_releases(payload, current_version)


def _crypto_libraries():
    crypt32 = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    pointer = ctypes.POINTER(_DataBlob)
    crypt32.CryptProtectData.argtypes = [pointer, wintypes.LPCWSTR, pointer, wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, pointer]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [pointer, ctypes.POINTER(wintypes.LPWSTR), pointer, wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, pointer]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    return crypt32, kernel32


def protect_secret(secret: bytes) -> bytes:
    if os.name != "nt" or not secret:
        raise GitHubUpdateError("GitHub 토큰은 Windows에서만 암호화 저장할 수 있습니다.")
    buffer = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
    source, protected = _DataBlob(len(secret), buffer), _DataBlob()
    crypt32, kernel32 = _crypto_libraries()
    if not crypt32.CryptProtectData(ctypes.byref(source), "Cinema TMS Admin GitHub token", None, None, None, 1, ctypes.byref(protected)):
        raise GitHubUpdateError(f"GitHub 토큰 암호화 실패: {ctypes.WinError(ctypes.get_last_error())}")
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(protected.pbData, wintypes.HLOCAL))


def unprotect_secret(payload: bytes) -> bytes:
    if os.name != "nt" or not payload:
        raise GitHubUpdateError("저장된 GitHub 토큰을 복호화할 수 없습니다.")
    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source, clear = _DataBlob(len(payload), buffer), _DataBlob()
    crypt32, kernel32 = _crypto_libraries()
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(clear)):
        raise GitHubUpdateError(f"GitHub 토큰 복호화 실패: {ctypes.WinError(ctypes.get_last_error())}")
    try:
        return ctypes.string_at(clear.pbData, clear.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(clear.pbData, wintypes.HLOCAL))


def save_update_token(path: Path, token: str, protector=protect_secret) -> None:
    token = str(token or "").strip()
    if not token or len(token) > 1024:
        raise GitHubUpdateError("GitHub 토큰 값이 비어 있거나 너무 깁니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(protector(token.encode("utf-8")))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_update_token(path: Path, unprotector=unprotect_secret) -> str:
    if not path.is_file():
        return ""
    try:
        token = unprotector(path.read_bytes()).decode("utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise GitHubUpdateError(f"저장된 GitHub 토큰을 읽지 못했습니다: {exc}") from exc
    if not token:
        raise GitHubUpdateError("저장된 GitHub 토큰이 비어 있습니다.")
    return token


def download_update(release: UpdateRelease, destination: Path, token: str) -> Path:
    with _open(Request(release.checksum.api_url, headers=_headers(token, True)), 60) as response:
        checksum_raw = response.read(65537)
        if len(checksum_raw) > 65536:
            raise GitHubUpdateError("업데이트 SHA-256 응답이 너무 큽니다.")
        checksum_text = checksum_raw.decode("ascii", errors="strict").strip()
    expected = checksum_text.split()[0].lower() if checksum_text else ""
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise GitHubUpdateError("업데이트 SHA-256 파일 형식이 올바르지 않습니다.")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / release.package.name
    temporary = target.with_suffix(target.suffix + ".part")
    digest, written = hashlib.sha256(), 0
    try:
        with _open(Request(release.package.api_url, headers=_headers(token, True)), 120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPDATE_BYTES:
                    raise GitHubUpdateError("업데이트 파일 크기가 허용 범위를 초과했습니다.")
                digest.update(chunk)
                output.write(chunk)
        if written != release.package.size or digest.hexdigest() != expected:
            raise GitHubUpdateError("업데이트 크기 또는 SHA-256 검증에 실패했습니다.")
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)
