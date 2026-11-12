"""Local secret encryption helpers. QUANTNEX has no login or JWT system."""
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from .config import SECRET_KEY


def _secret_box() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("QUANTNEX-TELEGRAM:" + SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _secret_box().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _secret_box().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise ValueError("Stored Telegram token cannot be decrypted. Reconnect the bot after checking QUANTNEX_SECRET_KEY.") from exc
