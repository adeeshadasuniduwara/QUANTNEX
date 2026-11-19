"""QUANTNEX OpenAI assistant helpers.

API credentials are read from encrypted local preferences or server environment
variables and are never returned to the browser or Telegram.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_MODEL
from .models import Preference
from .security import decrypt_secret

SYSTEM_INSTRUCTIONS = """You are QUANTNEX AI, the knowledgeable assistant for the QUANTNEX trading workspace.
Explain QUANTNEX features accurately using this product context:
- QUANTNEX is a local-first trading workspace with Web and Android shell, a loopback FastAPI backend, charts, market data, multi-timeframe signals, signal lifecycle, trade journal, wallet ledger, paper trading, paper autopilot, risk tools, performance analytics, strategy research, economic news, Telegram alerts, Binance Demo credential center, and system diagnostics.
- Crypto chart candles use Binance Spot with limited Coinbase fallback. Gold history requires local read-only MT5 or Twelve Data. Gold-API quotes are indicative only.
- Signal confluence scores count rules; they are NOT win probabilities. No profit or win-rate is guaranteed.
- Telegram alerts are informational. The current product does not place broker orders. Binance Demo credentials and risk policies do not mean execution is enabled. Never claim a trade was placed.
- The backend is loopback-only and must not be exposed to a LAN or public internet. Secrets must never be sent in Telegram or logged.
- You may explain current implemented capabilities and guide users through setup. If a feature is not confirmed as implemented, say so and describe it as planned/not yet available.
- You cannot inspect files or invoke QUANTNEX tools unless a tool result is explicitly provided in the conversation. Never pretend to have changed settings or performed actions.
Answer in the language used by the user, including Sinhala when appropriate. Be practical, clear, and risk-aware."""

def _get(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    return row.value if row else default

def get_openai_config(db: Session, user_id: int) -> tuple[str, str]:
    encrypted = _get(db, user_id, "openai_api_key_enc")
    key = decrypt_secret(encrypted) if encrypted else AI_API_KEY
    model = _get(db, user_id, "openai_model", "") or AI_MODEL or "gpt-5.5"
    return key, model

async def ask_openai(db: Session, user_id: int, message: str) -> tuple[str, str]:
    key, model = get_openai_config(db, user_id)
    if not key:
        raise RuntimeError("OpenAI is not configured. Add an API key in QUANTNEX → Connections & Integrations.")
    enabled = _get(db, user_id, "openai_web_search_enabled", "false") == "true"
    payload = {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS + (
            "\nWeb search is enabled. Use it only when current external information is needed."
            if enabled else ""
        ),
        "input": message,
        "store": False,
        "max_output_tokens": 1200,
    }
    if enabled:
        payload["tools"] = [{"type": "web_search"}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    answer = data.get("output_text")
    if not isinstance(answer, str) or not answer.strip():
        pieces = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        pieces.append(part["text"])
        answer = "\n".join(pieces)
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("OpenAI returned an empty response.")
    return answer.strip(), model
