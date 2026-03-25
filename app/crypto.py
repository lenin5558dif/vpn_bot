from __future__ import annotations

import logging

from cryptography.fernet import Fernet

from app.config import get_settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = get_settings().encryption_key
        if not key:
            raise RuntimeError("ENCRYPTION_KEY is not set — cannot encrypt/decrypt private keys")
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_private_key(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_private_key(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
