"""Fernet symmetric encryption for API keys."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import settings


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the API secret."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key(settings.api_secret_key))
    return _fernet


def encrypt_api_key(plain: str) -> bytes:
    """Encrypt an API key string, returns bytes suitable for LargeBinary column."""
    return _get_fernet().encrypt(plain.encode("utf-8"))


def decrypt_api_key(encrypted: bytes) -> str:
    """Decrypt API key bytes back to string."""
    return _get_fernet().decrypt(encrypted).decode("utf-8")
