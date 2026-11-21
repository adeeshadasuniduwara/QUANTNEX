"""QUANTNEX OpenAI Responses API integration.

Credentials are read from encrypted local preferences or environment variables.
The module never logs or returns API credentials.
"""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_MODEL
from .models import Preference
from .security import decrypt_secret

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.5"
MAX_OUTPUT_TOKENS = 1800

SYSTEM_INSTRUCTIONS = """You are QUANTNEX AI, the knowledgeable assistant for the QUANTNEX trading workspace.
Explain QUANTNEX features accurately using this product context:
- QUANTNEX is a local-first trading workspace with Web and Android shell, a loopback FastAPI backend, charts, market data, multi-timeframe signals, signal lifecycle, trade journal, wallet ledger, paper trading, paper autopilot, risk tools, performance analytics, strategy research, economic news, Telegram alerts, Binance Demo credential center, and system diagnostics.
- Crypto chart candles use Binance Spot with limited Coinbase fallback. Gold history requires local read-only MT5 or Twelve Data. Gold-API quotes are indicative only.
- Binance USDⓈ-M Futures has a separate candle-based signal-analysis path. Do not imply Futures order-flow confirmation or Futures order execution is enabled unless the caller provides explicit current evidence.
- Signal confluence scores count rules; they are NOT win probabilities. No profit or win-rate is guaranteed.
- Telegram alerts are informational. Paper trading is simulated. Never claim a trade was placed or filled unless an execution result explicitly confirms it.
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
    model = _get(db, user_id, "openai_model", "") or AI_MODEL or DEFAULT_MODEL
    return key, model


def extract_response_text(data: dict[str, Any]) -> str:
    """Extract user-visible text across Responses API output item variants."""
    if not isinstance(data, dict):
        raise ValueError("OpenAI returned an invalid response payload.")

    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        answer = direct.strip()
    else:
        pieces: list[str] = []
        output = data.get("output")
        if not isinstance(output, list):
            output = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "output_text":
                    value = part.get("text")
                elif part_type == "refusal":
                    value = part.get("refusal") or part.get("text")
                else:
                    continue
                if isinstance(value, str) and value.strip():
                    pieces.append(value.strip())
        answer = "\n".join(pieces)

    status = str(data.get("status") or "").lower()
    if not answer:
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                raise ValueError("OpenAI response failed: " + message.strip()[:400])
        incomplete = data.get("incomplete_details")
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else None
        if status == "incomplete" and reason == "max_output_tokens":
            raise ValueError("OpenAI response reached its output limit without returning text. Increase the response limit or shorten the request.")
        raise ValueError("OpenAI returned no readable text. Check model access, tool configuration and API project limits.")

    if status == "incomplete":
        incomplete = data.get("incomplete_details")
        reason = incomplete.get("reason") if isinstance(incomplete, dict) else "unknown"
        if reason == "max_output_tokens":
            answer += "\n\n[Response may be incomplete because the output-token limit was reached.]"
    elif status == "failed":
        raise ValueError("OpenAI reported a failed response.")
    return answer


async def ask_openai(db: Session, user_id: int, message: str) -> tuple[str, str]:
    key, model = get_openai_config(db, user_id)
    if not key:
        raise RuntimeError("OpenAI is not configured. Add an API key in QUANTNEX → Connections & Integrations.")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Enter a message before sending it to QUANTNEX AI.")
    if len(message) > 12000:
        raise ValueError("The message is too long. Keep it under 12,000 characters.")

    enabled = _get(db, user_id, "openai_web_search_enabled", "false") == "true"
    payload: dict[str, Any] = {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS + (
            "\nWeb search is enabled. Use it only when current external information is needed."
            if enabled else ""
        ),
        "input": message.strip(),
        "store": False,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    if enabled:
        payload["tools"] = [{"type": "web_search"}]

    timeout = httpx.Timeout(60.0, connect=10.0, read=50.0, write=15.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("OpenAI returned invalid JSON. Retry the request; if it continues, check the API status.") from exc

    return extract_response_text(data), model
