import pytest
from app.crypto import encrypt_private_key, decrypt_private_key


def test_encrypt_decrypt_roundtrip():
    plaintext = "test-private-key-abc123"
    encrypted = encrypt_private_key(plaintext)
    assert encrypted != plaintext
    assert encrypted.startswith("gA")  # Fernet token prefix
    decrypted = decrypt_private_key(encrypted)
    assert decrypted == plaintext


def test_encrypt_produces_different_ciphertexts():
    plaintext = "same-key"
    enc1 = encrypt_private_key(plaintext)
    enc2 = encrypt_private_key(plaintext)
    # Fernet uses random IV, so ciphertexts differ
    assert enc1 != enc2
    assert decrypt_private_key(enc1) == plaintext
    assert decrypt_private_key(enc2) == plaintext


def test_decrypt_invalid_token():
    with pytest.raises(Exception):
        decrypt_private_key("not-a-valid-fernet-token")
