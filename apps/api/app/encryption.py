"""Fernet symmetric encryption for API keys.

The key is derived from ``encryption_secret``, falling back to ``api_secret_key`` so existing
deployments keep decrypting what they already stored. Set ``ENCRYPTION_SECRET`` to the old
``API_SECRET_KEY`` when rotating the JWT signing key - otherwise every stored integration
credential, index-provider key and GitHub App secret becomes undecryptable.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import settings


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from the encryption secret."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _encryption_secret() -> str:
    return settings.encryption_secret or settings.api_secret_key


_fernet: Fernet | None = None
_fernet_secret: str | None = None


def _get_fernet() -> Fernet:
    """Fernet for the current secret, rebuilt if the secret changed (tests, key rotation)."""
    global _fernet, _fernet_secret
    secret = _encryption_secret()
    if _fernet is None or _fernet_secret != secret:
        _fernet = Fernet(_derive_key(secret))
        _fernet_secret = secret
    return _fernet


def encrypt_api_key(plain: str) -> bytes:
    """Encrypt an API key string, returns bytes suitable for LargeBinary column."""
    return _get_fernet().encrypt(plain.encode("utf-8"))


def decrypt_api_key(encrypted: bytes) -> str:
    """Decrypt API key bytes back to string."""
    return _get_fernet().decrypt(encrypted).decode("utf-8")
