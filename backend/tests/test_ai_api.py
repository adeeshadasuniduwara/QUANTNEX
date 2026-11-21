import httpx
from fastapi.testclient import TestClient

from app import ai_assistant
from app.main import app


def test_openai_connection_test_performs_a_real_responses_api_call(monkeypatch):
    calls = []

    async def fake_ask_openai(db, user_id, message):
        calls.append(message)
        return "QUANTNEX AI connection verified.", "gpt-5.5"

    monkeypatch.setattr(ai_assistant, "ask_openai", fake_ask_openai)
    response = TestClient(app).post("/api/v1/ai/test")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["model"] == "gpt-5.5"
    assert "Responses API returned" in data["message"]
    assert data["reply_preview"] == "QUANTNEX AI connection verified."
    assert calls == ["Reply with exactly: QUANTNEX AI connection verified."]


def test_ai_chat_maps_openai_quota_errors_to_http_429(monkeypatch):
    async def fake_ask_openai(*_args, **_kwargs):
        request = httpx.Request("POST", ai_assistant.OPENAI_RESPONSES_URL)
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    monkeypatch.setattr(ai_assistant, "ask_openai", fake_ask_openai)
    response = TestClient(app).post("/api/v1/ai/chat", json={"message": "Hello"})
    assert response.status_code == 429
    assert "rate limit or project quota" in response.json()["detail"]


def test_ai_chat_maps_openai_timeouts_to_http_504(monkeypatch):
    async def fake_ask_openai(*_args, **_kwargs):
        request = httpx.Request("POST", ai_assistant.OPENAI_RESPONSES_URL)
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(ai_assistant, "ask_openai", fake_ask_openai)
    response = TestClient(app).post("/api/v1/ai/chat", json={"message": "Hello"})
    assert response.status_code == 504
    assert "too long to respond" in response.json()["detail"]
