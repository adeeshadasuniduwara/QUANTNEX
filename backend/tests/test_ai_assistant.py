import asyncio

from app import ai_assistant
from app.security import encrypt_secret


class FakePreference:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class FakeDB:
    def __init__(self, values):
        self.values = values

    def scalar(self, _query):
        for key, value in self.values.items():
            if key == _query.column_descriptions[0]["entity"].key:
                return FakePreference(key, value)
        # SQLAlchemy Select expressions are easier to identify from their WHERE bind.
        compiled = str(_query)
        for key, value in self.values.items():
            if key in compiled:
                return FakePreference(key, value)
        return None


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
