"""Encrypt the shared update token for one licensed TMS machine."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


KEY_INFO = b"Cinema-TMS-GitHub-Update-Credential-v1"


def validate_client_public_key(value: str) -> str:
    try:
        raw = base64.b64decode(str(value), validate=True)
        X25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("하드웨어 키 파일의 업데이트 암호화 공개키가 올바르지 않습니다.") from exc
    return base64.b64encode(raw).decode("ascii")


def encrypt_update_token(token: str, client_public_key: str, *, license_id: str, hardware_key: str) -> dict:
    token = str(token or "").strip()
    if not token:
        raise ValueError("공용 GitHub 업데이트 토큰이 설정되지 않았습니다.")
    public_key = X25519PublicKey.from_public_bytes(base64.b64decode(validate_client_public_key(client_public_key)))
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(public_key)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=KEY_INFO).derive(shared)
    nonce = os.urandom(12)
    aad = f"{license_id}|{hardware_key}".encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, token.encode("utf-8"), aad)
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return {
        "schema": 1,
        "ephemeral_public_key": base64.b64encode(ephemeral_public).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
