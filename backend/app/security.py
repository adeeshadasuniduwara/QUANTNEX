from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash
from .config import SECRET_KEY, TOKEN_MINUTES

password_hash = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, stored_hash: str) -> bool:
    return password_hash.verify(password, stored_hash)

def create_access_token(user_id: int) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expiry}, SECRET_KEY, algorithm="HS256")

def decode_access_token(token: str) -> int:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    subject = payload.get("sub")
    if not subject or not str(subject).isdigit():
        raise ValueError("Invalid token subject.")
    return int(subject)

import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

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
