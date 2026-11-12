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
