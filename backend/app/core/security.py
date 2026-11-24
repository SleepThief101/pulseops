from cryptography.fernet import Fernet, InvalidToken
from app.config import settings


class EncryptionError(Exception):
    """Base exception for encryption and decryption errors."""
    pass


class EncryptionConfigurationError(EncryptionError):
    """Raised when the encryption key is missing, empty, or malformed."""
    pass


def generate_encryption_key() -> str:
    """Generate a fresh URL-safe base64-encoded Fernet key."""
    return Fernet.generate_key().decode("utf-8")


def get_fernet(key: str | None = None) -> Fernet:
    """
    Instantiate a Fernet cipher instance using the provided key or
    the application-level INTEGRATION_ENCRYPTION_KEY setting.

    Raises EncryptionConfigurationError if no key is configured or
    if the key is invalid. Never silently falls back to plaintext.
    """
    encryption_key = key or settings.integration_encryption_key
    if not encryption_key or not encryption_key.strip():
        raise EncryptionConfigurationError(
            "INTEGRATION_ENCRYPTION_KEY is not configured. "
            "Please configure INTEGRATION_ENCRYPTION_KEY in your environment or .env file."
        )

    try:
        raw_key = encryption_key.strip().encode("utf-8")
        return Fernet(raw_key)
    except Exception as exc:
        raise EncryptionConfigurationError(
            f"Invalid INTEGRATION_ENCRYPTION_KEY: {exc}"
        ) from exc


def encrypt_credentials(data: str | bytes, key: str | None = None) -> str:
    """
    Encrypt integration credentials using Fernet authenticated symmetric encryption.

    Args:
        data: Plaintext credentials (e.g. JSON string, API key, token).
        key: Optional explicit encryption key (overrides settings).

    Returns:
        Ciphertext formatted as a URL-safe base64 string.
    """
    fernet = get_fernet(key)
    if isinstance(data, str):
        payload = data.encode("utf-8")
    elif isinstance(data, bytes):
        payload = data
    else:
        raise ValueError("Data to encrypt must be a str or bytes instance.")

    return fernet.encrypt(payload).decode("utf-8")


def decrypt_credentials(token: str | bytes, key: str | None = None) -> str:
    """
    Decrypt integration credentials using Fernet authenticated symmetric encryption.

    Args:
        token: Ciphertext token to decrypt.
        key: Optional explicit encryption key (overrides settings).

    Returns:
        Decrypted plaintext as a string.

    Raises:
        EncryptionError: If the token is invalid, tampered with, or the key is wrong.
    """
    fernet = get_fernet(key)
    if isinstance(token, str):
        token_bytes = token.strip().encode("utf-8")
    elif isinstance(token, bytes):
        token_bytes = token.strip()
    else:
        raise ValueError("Token to decrypt must be a str or bytes instance.")

    try:
        return fernet.decrypt(token_bytes).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "Failed to decrypt credentials: invalid token, tampered data, or incorrect encryption key."
        ) from exc
