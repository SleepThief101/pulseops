import pytest
from cryptography.fernet import Fernet

from app.core.security import (
    EncryptionConfigurationError,
    EncryptionError,
    decrypt_credentials,
    encrypt_credentials,
    generate_encryption_key,
    get_fernet,
)


def test_generate_encryption_key():
    """Verify generated key is valid base64 Fernet key."""
    key = generate_encryption_key()
    assert isinstance(key, str)
    assert len(key) == 44
    # Ensure Fernet accepts it
    fernet = Fernet(key.encode("utf-8"))
    assert fernet is not None


def test_encryption_and_decryption_roundtrip(test_encryption_key):
    """Verify encryption followed by decryption returns original plaintext."""
    plaintext = '{"api_key": "pulse_test_12345", "secret": "super_secret_value"}'

    ciphertext = encrypt_credentials(plaintext, key=test_encryption_key)
    assert isinstance(ciphertext, str)
    # Stored ciphertext must never match original plaintext
    assert ciphertext != plaintext
    assert "pulse_test_12345" not in ciphertext
    assert "super_secret_value" not in ciphertext

    decrypted = decrypt_credentials(ciphertext, key=test_encryption_key)
    assert decrypted == plaintext


def test_encryption_bytes_payload(test_encryption_key):
    """Verify encryption works with bytes payload."""
    plaintext_bytes = b"ghp_test_token_bytes_value"
    ciphertext = encrypt_credentials(plaintext_bytes, key=test_encryption_key)

    decrypted = decrypt_credentials(ciphertext, key=test_encryption_key)
    assert decrypted == "ghp_test_token_bytes_value"


def test_encryption_ciphertext_is_different_each_time(test_encryption_key):
    """Fernet generates a random 128-bit IV for each encryption call."""
    plaintext = "my_token"
    token1 = encrypt_credentials(plaintext, key=test_encryption_key)
    token2 = encrypt_credentials(plaintext, key=test_encryption_key)

    assert token1 != token2
    assert decrypt_credentials(token1, key=test_encryption_key) == plaintext
    assert decrypt_credentials(token2, key=test_encryption_key) == plaintext


def test_missing_encryption_key_fails_safely(monkeypatch):
    """Verify missing key raises EncryptionConfigurationError and never returns plaintext."""
    from app.config import settings
    monkeypatch.setattr(settings, "integration_encryption_key", None)

    with pytest.raises(EncryptionConfigurationError) as exc_info:
        encrypt_credentials("secret_data")
    assert "INTEGRATION_ENCRYPTION_KEY is not configured" in str(exc_info.value)

    with pytest.raises(EncryptionConfigurationError) as exc_info:
        decrypt_credentials("some_token")
    assert "INTEGRATION_ENCRYPTION_KEY is not configured" in str(exc_info.value)


def test_empty_string_encryption_key_fails_safely(monkeypatch):
    """Verify blank or whitespace-only key raises EncryptionConfigurationError."""
    from app.config import settings
    monkeypatch.setattr(settings, "integration_encryption_key", "   ")

    with pytest.raises(EncryptionConfigurationError):
        get_fernet()


def test_malformed_encryption_key_fails_safely():
    """Verify invalid Fernet key format raises EncryptionConfigurationError."""
    with pytest.raises(EncryptionConfigurationError) as exc_info:
        encrypt_credentials("secret", key="not_a_valid_fernet_key")
    assert "Invalid INTEGRATION_ENCRYPTION_KEY" in str(exc_info.value)


def test_decryption_with_wrong_key_fails(test_encryption_key):
    """Verify decryption fails when using a different key than encryption."""
    another_key = generate_encryption_key()
    ciphertext = encrypt_credentials("api_token_123", key=test_encryption_key)

    with pytest.raises(EncryptionError) as exc_info:
        decrypt_credentials(ciphertext, key=another_key)
    assert "Failed to decrypt credentials" in str(exc_info.value)


def test_decryption_with_tampered_ciphertext_fails(test_encryption_key):
    """Verify authenticated decryption rejects tampered ciphertext."""
    ciphertext = encrypt_credentials("token", key=test_encryption_key)
    tampered = ciphertext[:-4] + "AAAA"

    with pytest.raises(EncryptionError):
        decrypt_credentials(tampered, key=test_encryption_key)
