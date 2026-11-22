from app import ai_assistant
from app.security import encrypt_secret


class FakePreference:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class FakeDB:
    def __init__(self, values):
        self.values = values

    def scalar(self, query):
        key = query.compile().params.get("key_1")
        return FakePreference(key, self.values[key]) if key in self.values else None


def test_get_openai_config_decrypts_local_key_and_uses_saved_model():
    db = FakeDB({
        "openai_api_key_enc": encrypt_secret("sk-" + "x" * 40),
        "openai_model": "gpt-5.5",
    })
    key, model = ai_assistant.get_openai_config(db, 1)
    assert key == "sk-" + "x" * 40
    assert model == "gpt-5.5"


def test_get_openai_config_falls_back_to_environment(monkeypatch):
    monkeypatch.setattr(ai_assistant, "AI_API_KEY", "sk-" + "e" * 40)
    monkeypatch.setattr(ai_assistant, "AI_MODEL", "gpt-5.5")
    key, model = ai_assistant.get_openai_config(FakeDB({}), 1)
    assert key == "sk-" + "e" * 40
    assert model == "gpt-5.5"


def test_telegram_assistant_prompt_has_product_safety_context():
    assert "loopback-only" in ai_assistant.SYSTEM_INSTRUCTIONS
    assert "NOT win probabilities" in ai_assistant.SYSTEM_INSTRUCTIONS
    assert "Never claim a trade was placed" in ai_assistant.SYSTEM_INSTRUCTIONS


def test_extract_response_text_reads_top_level_output_text():
    assert ai_assistant.extract_response_text({
        "status": "completed",
        "output_text": "  QUANTNEX is ready.  ",
        "output": [],
    }) == "QUANTNEX is ready."


def test_extract_response_text_reads_nested_output_text_and_multiple_messages():
    result = ai_assistant.extract_response_text({
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [
                {"type": "output_text", "text": "First paragraph."},
                {"type": "refusal", "refusal": "I cannot help with that request."},
            ]},
            {"type": "message", "content": [
                {"type": "output_text", "text": "Second paragraph."},
            ]},
        ],
    })
    assert result == "First paragraph.\nI cannot help with that request.\nSecond paragraph."


def test_extract_response_text_marks_partial_output_when_token_limit_is_reached():
    result = ai_assistant.extract_response_text({
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output_text": "Partial answer",
    })
    assert result.startswith("Partial answer")
    assert "may be incomplete" in result


def test_extract_response_text_surfaces_provider_error_without_secret_data():
    import pytest

    with pytest.raises(ValueError, match="model is not available"):
        ai_assistant.extract_response_text({
            "status": "failed",
            "error": {"message": "This model is not available to this project."},
        })


def test_extract_response_text_rejects_empty_or_malformed_payload():
    import pytest

    with pytest.raises(ValueError, match="no readable text"):
        ai_assistant.extract_response_text({"status": "completed", "output": []})
    with pytest.raises(ValueError, match="invalid response payload"):
        ai_assistant.extract_response_text(["not", "an", "object"])



def test_openai_http_error_messages_distinguish_auth_permissions_model_and_quota():
    import httpx

    cases = {
        401: "rejected the saved API key",
        403: "does not have permission",
        404: "model was not found",
        429: "rate limit or project quota",
        500: "temporarily experiencing a service problem",
    }
    for status, expected in cases.items():
        request = httpx.Request("POST", ai_assistant.OPENAI_RESPONSES_URL)
        response = httpx.Response(status, request=request)
        error = httpx.HTTPStatusError("provider error", request=request, response=response)
        assert expected in ai_assistant.openai_http_error_message(error)


def test_openai_http_error_message_never_echoes_provider_payload_or_credentials():
    import httpx

    request = httpx.Request("POST", ai_assistant.OPENAI_RESPONSES_URL)
    response = httpx.Response(
        401, request=request,
        json={"error": {"message": "Invalid key sk-secret-must-not-be-returned"}},
    )
    error = httpx.HTTPStatusError("provider error", request=request, response=response)
    message = ai_assistant.openai_http_error_message(error)
    assert "sk-secret" not in message
    assert "API key" in message
