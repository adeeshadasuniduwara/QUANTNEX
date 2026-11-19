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

    def scalar(self, query):
        params = query.compile().params
        key = params.get("key_1")
        return FakePreference(key, self.values[key]) if key in self.values else None
