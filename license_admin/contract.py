"""Shared, public Cinema TMS license-envelope contract.

This module intentionally contains verification-key material only. The private
signing key remains encrypted inside the administrator database.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


PRODUCT_ID = "cinema-tms"
LICENSE_SCHEMA = 3
HARDWARE_REQUEST_SCHEMA = 1
TRUSTED_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAGiHZOG0wXgxv3Ll5o4+tP8A7FWrCvnXogGbgy0ZLWYw=
-----END PUBLIC KEY-----
"""


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def trusted_issuer_id() -> str:
    digest = hashlib.sha256(TRUSTED_PUBLIC_KEY_PEM).hexdigest().upper()[:16]
    return "-".join(digest[index:index + 4] for index in range(0, len(digest), 4))
