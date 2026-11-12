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


# Small per-process guard for public authentication endpoints.
# Appropriate for the single-computer local API; public deployments should
# additionally use a shared reverse-proxy/API-gateway rate limiter.
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from fastapi import HTTPException, Request

_AUTH_ATTEMPTS = defaultdict(deque)
_AUTH_ATTEMPTS_LOCK = Lock()
_AUTH_WINDOW_SECONDS = 60
_AUTH_MAX_ATTEMPTS = 5

def enforce_auth_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    key = (client, request.url.path)
    now = monotonic()
    with _AUTH_ATTEMPTS_LOCK:
        for old_key in list(_AUTH_ATTEMPTS):
            bucket = _AUTH_ATTEMPTS[old_key]
            while bucket and now - bucket[0] >= _AUTH_WINDOW_SECONDS:
                bucket.popleft()
            if not bucket:
                _AUTH_ATTEMPTS.pop(old_key, None)
        bucket = _AUTH_ATTEMPTS[key]
        while bucket and now - bucket[0] >= _AUTH_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _AUTH_MAX_ATTEMPTS:
            retry_after = max(1, int(_AUTH_WINDOW_SECONDS - (now - bucket[0])))
            raise HTTPException(status_code=429, detail="Too many authentication attempts. Wait a minute and try again.",
                                headers={"Retry-After": str(retry_after)})
        bucket.append(now)
