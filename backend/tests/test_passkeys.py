import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import _consume_webauthn_challenge, _webauthn_origin
from app.models import User, WebAuthnChallenge
from starlette.requests import Request


def _request(origin):
    return Request({
        "type": "http", "method": "POST", "scheme": "http",
        "path": "/", "raw_path": b"/", "query_string": b"",
        "headers": [(b"origin", origin.encode())],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000),
    })


def test_localhost_origin_is_accepted():
    assert _webauthn_origin(_request("http://localhost:5500")) == (
        "http://localhost:5500", "localhost"
    )


def test_unlisted_origin_is_rejected():
    with pytest.raises(HTTPException) as error:
        _webauthn_origin(_request("http://evil.example:5500"))
    assert error.value.status_code == 400


def test_webauthn_challenge_is_single_use():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="passkey-test@example.com", password_hash="not-used")
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(WebAuthnChallenge(
            id="8c7d9d5e-a49d-4a21-8cb2-b73ecbaaf38e",
            user_id=user.id,
            purpose="login",
            challenge="test-challenge",
            expected_origin="http://localhost:5500",
            expected_rp_id="localhost",
            expires_at=time.time() + 60,
        ))
        db.commit()

        result = _consume_webauthn_challenge(
            db, "8c7d9d5e-a49d-4a21-8cb2-b73ecbaaf38e", "login"
        )
        assert result["challenge"] == "test-challenge"
        with pytest.raises(HTTPException):
            _consume_webauthn_challenge(
                db, "8c7d9d5e-a49d-4a21-8cb2-b73ecbaaf38e", "login"
            )


def test_expired_webauthn_challenge_is_rejected():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="expired-passkey@example.com", password_hash="not-used")
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(WebAuthnChallenge(
            id="ab3d9d5e-a49d-4a21-8cb2-b73ecbaaf38e",
            user_id=user.id,
            purpose="register",
            challenge="expired",
            expected_origin="http://localhost:5500",
            expected_rp_id="localhost",
            expires_at=time.time() - 1,
        ))
        db.commit()
        with pytest.raises(HTTPException) as error:
            _consume_webauthn_challenge(
                db, "ab3d9d5e-a49d-4a21-8cb2-b73ecbaaf38e", "register", user.id
            )
        assert error.value.status_code == 400
