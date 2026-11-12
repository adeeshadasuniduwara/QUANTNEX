from fastapi import HTTPException
from starlette.requests import Request

from app.schemas import LoginRequest
from app.security import _AUTH_ATTEMPTS, enforce_auth_rate_limit


def _request(path="/api/v1/auth/login", host="127.0.0.1"):
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": (host, 12345),
        "server": ("127.0.0.1", 8000),
    })


def test_auth_rate_limit_allows_five_attempts_then_blocks():
    _AUTH_ATTEMPTS.clear()
    request = _request()
    for _ in range(5):
        enforce_auth_rate_limit(request)

    try:
        enforce_auth_rate_limit(request)
    except HTTPException as exc:
        assert exc.status_code == 429
        assert "Retry-After" in exc.headers
    else:
        raise AssertionError("The sixth authentication attempt should be throttled.")


def test_auth_rate_limit_is_scoped_by_client_and_endpoint():
    _AUTH_ATTEMPTS.clear()
    login_request = _request()
    register_request = _request("/api/v1/auth/register")
    other_client_request = _request(host="127.0.0.2")

    for _ in range(5):
        enforce_auth_rate_limit(login_request)

    # A different endpoint and a different client have independent buckets.
    enforce_auth_rate_limit(register_request)
    enforce_auth_rate_limit(other_client_request)


def test_login_email_is_normalized_and_password_is_bounded():
    payload = LoginRequest(email="  TRADER@example.com  ", password="a-secure-password")
    assert payload.email == "trader@example.com"

    try:
        LoginRequest(email="not-an-email", password="a-secure-password")
    except Exception:
        pass
    else:
        raise AssertionError("Invalid email addresses must be rejected.")

    try:
        LoginRequest(email="trader@example.com", password="x" * 129)
    except Exception:
        pass
    else:
        raise AssertionError("Overlong passwords must be rejected.")
