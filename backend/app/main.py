import asyncio
from contextlib import asynccontextmanager
import json
import math
import re
import sqlite3
import httpx
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .config import AI_API_KEY, AI_BASE_URL, AI_MODEL, CORS_ORIGINS, DATABASE_URL, QUANTNEX_MT5_ENABLED, QUANTNEX_MT5_GOLD_SYMBOL
from .database import Base, engine, get_db, SessionLocal
from .models import AuditEvent, GoalContribution, JournalImport, OrderFlowObservation, PaperTrade, PaperTradeEvent, PersonalGoal, Preference, SignalTrade, SignalTradeEvent, StrategyLabRun, Trade, User, WalletTransaction
from .schemas import AIChatRequest, AIChatResponse, LegacyJournalImportRequest, LegacyJournalImportResponse, PreferenceResponse, PreferenceWrite, TelegramConnectRequest, TelegramSendRequest, SignalSettingsRequest, AutoSignalSettingsRequest, TradeCreate, TradeResponse, WalletSummaryResponse, WalletTransactionCreate, WalletTransactionResponse
from .security import decrypt_secret, encrypt_secret
from .maintenance import daily_backup_worker, record_audit_event
from .system_security import router as system_security_router
from .events import event_hub, router as events_router
from .prop_challenge import router as prop_challenge_router, mt5_guardian_worker
from .binance_demo import router as binance_demo_router

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own all local background workers and read-only market streams."""
    from .binance_order_flow_manager import (
        start_binance_spot_order_flow_manager,
        stop_binance_spot_order_flow_manager,
    )
    await prepare_local_workspace()
    try:
        await start_binance_spot_order_flow_manager()
        await start_signal_lifecycle_worker()
        await start_telegram_background_worker()
        await start_prop_challenge_guardian()
        await start_daily_backup_worker()
        await start_paper_autopilot_worker()
        await start_binance_spot_auto_worker()
        yield
    finally:
        await stop_binance_spot_auto_worker()
        await stop_paper_autopilot_worker()
        await stop_daily_backup_worker()
        await stop_prop_challenge_guardian()
        await stop_telegram_background_worker()
        await stop_binance_spot_order_flow_manager()
        await stop_signal_lifecycle_worker()


app = FastAPI(title="QUANTNEX Local API",
              description="Loopback-only local workspace API. No user login or remote account system.",
              version="0.8.0", lifespan=lifespan)

def _safe_validation_json(value):
    """Make Pydantic validation details safe for strict JSON responses."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value).lower()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {str(key): _safe_validation_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_validation_json(item) for item in value]
    return str(value)


@app.exception_handler(RequestValidationError)
async def safe_request_validation_error(_request: Request, exc: RequestValidationError):
    # Pydantic may include NaN/Infinity in the rejected input. JSON does not
    # permit those numeric values, so serialize them as strings in the 422 body.
    return JSONResponse(
        status_code=422,
        content={"detail": _safe_validation_json(exc.errors())},
    )

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.include_router(system_security_router)
app.include_router(events_router)
app.include_router(prop_challenge_router)
app.include_router(binance_demo_router)


@app.middleware("http")
async def reject_untrusted_browser_mutations(request: Request, call_next):
    """Reject cross-origin browser writes while keeping native local clients usable.

    CORS alone does not stop a simple cross-origin form POST from reaching a
    loopback endpoint. Mutating requests with a browser Origin must come from
    the explicitly trusted local QUANTNEX Web workspace.
    """
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin not in CORS_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin changes are blocked by the local QUANTNEX security policy."},
            )
    return await call_next(request)


def local_workspace(db: Session = Depends(get_db)) -> User:
    """Return the one local workspace owner and safely consolidate legacy accounts."""
    users = list(db.scalars(select(User).order_by(User.id)))
    if not users:
        owner = User(email="local@quantnex.invalid", password_hash="")
        db.add(owner)
        db.commit()
        db.refresh(owner)
        return owner

    owner = users[0]
    changed = False
    for legacy in users[1:]:
        for preference in list(db.scalars(select(Preference).where(Preference.user_id == legacy.id))):
            existing = db.scalar(select(Preference).where(
                Preference.user_id == owner.id, Preference.key == preference.key
            ))
            if existing is None:
                preference.user_id = owner.id
            else:
                db.delete(preference)
        for trade in db.scalars(select(Trade).where(Trade.user_id == legacy.id)):
            trade.user_id = owner.id
        for transaction in db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == legacy.id)):
            transaction.user_id = owner.id
        # Phase 07/08 user-scoped ledgers must move with the original workspace too.
        # Otherwise legacy-account consolidation can orphan or cascade-delete paper
        # trades and strategy research created before local-only mode.
        for paper_trade in db.scalars(select(PaperTrade).where(PaperTrade.user_id == legacy.id)):
            paper_trade.user_id = owner.id
        for paper_event in db.scalars(select(PaperTradeEvent).where(PaperTradeEvent.user_id == legacy.id)):
            paper_event.user_id = owner.id
        for research_run in db.scalars(select(StrategyLabRun).where(StrategyLabRun.user_id == legacy.id)):
            research_run.user_id = owner.id
        for signal_trade in db.scalars(select(SignalTrade).where(SignalTrade.user_id == legacy.id)):
            signal_trade.user_id = owner.id
        for signal_event in db.scalars(select(SignalTradeEvent).where(SignalTradeEvent.user_id == legacy.id)):
            signal_event.user_id = owner.id
        for personal_goal in db.scalars(select(PersonalGoal).where(PersonalGoal.user_id == legacy.id)):
            personal_goal.user_id = owner.id
        for goal_contribution in db.scalars(select(GoalContribution).where(GoalContribution.user_id == legacy.id)):
            goal_contribution.user_id = owner.id
        # Flush reassigned child rows before deleting the legacy owner; ORM delete cascades
        # must not interpret the moved rows as orphans.
        db.flush()
        db.delete(legacy)
        changed = True

    if changed:
        db.flush()
    if owner.email != "local@quantnex.invalid":
        owner.email = "local@quantnex.invalid"
        changed = True
    if owner.password_hash:
        owner.password_hash = ""
        changed = True
    if changed:
        db.commit()
        db.refresh(owner)
    return owner

@app.get("/api/v1/charts/candles")
async def chart_candles(symbol: str = "BTCUSDT", interval: str = "15m", limit: int = 500):
    """Historical OHLC candles for the first-party QUANTNEX VIEW chart."""
    from .signal_engine import fetch_candles_with_provider, MarketDataError, is_binance_spot_symbol
    allowed_intervals = {"1m":"1min","5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h"}
    symbol = symbol.upper()
    try:
        supported_crypto = await is_binance_spot_symbol(symbol)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not supported_crypto and symbol != "XAUUSD":
        raise HTTPException(status_code=422, detail="Choose a currently tradable Binance Spot pair or XAUUSD.")
    if interval not in allowed_intervals or not 210 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="Choose a supported interval and 210–1000 candles.")
    try:
        candles, provider = await fetch_candles_with_provider(allowed_intervals[interval], limit, symbol)
        rows = candles[-limit:]
        source_timestamp = None
        age_seconds = None
        stale = True
        try:
            raw_source_time = str(rows[-1]["time"]).replace("Z", "+00:00")
            source_time = datetime.fromisoformat(raw_source_time)
            if source_time.tzinfo is None:
                source_time = source_time.replace(tzinfo=timezone.utc)
            source_time = source_time.astimezone(timezone.utc)
            source_timestamp = source_time.isoformat()
            age_seconds = max(0.0, (datetime.now(timezone.utc) - source_time).total_seconds())
            interval_seconds = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400}[interval]
            stale = age_seconds > max(120, interval_seconds * 2)
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            pass
        return {"symbol":symbol,"interval":interval,"provider":provider,
                "candles":rows,"count":len(rows),
                "timestamp":datetime.now(timezone.utc).isoformat(),
                "source_timestamp":source_timestamp,"age_seconds":round(age_seconds, 2) if age_seconds is not None else None,
                "stale":stale,"data_health":"stale" if stale else "ok",
                "stale_after_seconds":max(120, {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400}[interval] * 2)}
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Chart market-data provider is temporarily unavailable.")

@app.get("/api/v1/charts/quote")
async def chart_quote(symbol: str = "XAUUSD", interval: str = "15m"):
    """A live XAUUSD quote from the same configured provider as chart history."""
    symbol = symbol.upper()
    if symbol != "XAUUSD":
        raise HTTPException(status_code=422, detail="The chart quote endpoint currently supports XAUUSD only.")
    interval_seconds = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400}
    if interval not in interval_seconds:
        raise HTTPException(status_code=422, detail="Choose a supported chart timeframe.")
    stale_after_seconds = max(120, interval_seconds[interval] * 2)
    from .phase07_engine import get_quote as get_twelve_data_quote, IntelligenceDataError
    from .mt5_feed import get_quote as get_mt5_quote, MT5FeedError
    provider_errors = []
    if QUANTNEX_MT5_ENABLED:
        try:
            quote = await get_mt5_quote(QUANTNEX_MT5_GOLD_SYMBOL)
            bid, ask = float(quote["bid"]), float(quote["ask"])
            price = float(quote["last"]) if quote.get("last") else (bid + ask) / 2
            stale = bool(quote.get("stale")) or float(quote.get("age_seconds") or 0) > stale_after_seconds
            if not stale:
                return {"symbol": "XAUUSD", "price": price, "provider": quote["provider"],
                        "source_timestamp": quote.get("source_timestamp"),
                        "timestamp": quote.get("fetch_timestamp") or datetime.now(timezone.utc).isoformat(),
                        "stale": False, "stale_after_seconds": stale_after_seconds,
                        "spread": quote.get("spread")}
            provider_errors.append("MT5: quote is stale for the selected chart timeframe.")
        except (MT5FeedError, ValueError, KeyError) as exc:
            provider_errors.append("MT5: " + str(exc))
    try:
        quote = await get_twelve_data_quote("XAUUSD")
        from .phase10_engine import assess_quote
        health = assess_quote(quote)
        stale = not health["trading_safe"] or health["age_seconds"] is None or health["age_seconds"] > stale_after_seconds
        if not stale:
            return {"symbol": "XAUUSD", "price": quote["price"], "provider": quote["provider"],
                    "source_timestamp": quote.get("source_timestamp"),
                    "timestamp": quote.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                    "stale": False, "stale_after_seconds": stale_after_seconds, "data_health": health}
        provider_errors.append("Twelve Data: quote is stale or not safe for the selected chart timeframe.")
    except (IntelligenceDataError, httpx.HTTPError) as exc:
        provider_errors.append("Twelve Data: " + str(exc))
    except (ValueError, KeyError) as exc:
        provider_errors.append("Twelve Data returned an invalid quote: " + str(exc))
    # Gold-API is an indicative spot-price fallback only. It does not provide OHLC
    # history and must never be treated as a trading or broker execution quote.
    try:
        from .market_data import _gold_api_price
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True) as client:
            price = await _gold_api_price(client, "XAU")
        return {"symbol": "XAUUSD", "price": price, "provider": "Gold-API indicative spot (quote only)",
                "source_timestamp": None, "timestamp": datetime.now(timezone.utc).isoformat(),
                "stale": False, "stale_after_seconds": stale_after_seconds, "quote_only": True,
                "note": "Indicative quote only; historical candles require a connected MT5 terminal or Twelve Data API key."}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        provider_errors.append("Gold-API: " + str(exc))
    raise HTTPException(status_code=503, detail="Gold quote unavailable. " + " | ".join(provider_errors))


@app.get("/api/v1/quantnex-view/strategies")
def quantnex_view_strategies():
    from .quantnex_view_intelligence import STRATEGY_CATALOG
    return {"count": len(STRATEGY_CATALOG), "strategies": STRATEGY_CATALOG,
            "note": "100 catalog variants across 10 transparent setup families; variants are not 100 independent proven edges."}


@app.get("/api/v1/quantnex-view/analyze")
async def quantnex_view_analyze(symbol: str = "BTCUSDT", interval: str = "15m", min_score: int = 6,
                                user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .quantnex_view_intelligence import analyze_candles
    from .signal_engine import fetch_candles, MarketDataError
    from .signal_lifecycle import record_signal
    allowed = {"1m", "5m", "15m", "30m", "1h", "4h"}
    if interval not in allowed or not 4 <= min_score <= 20:
        raise HTTPException(status_code=422, detail="Choose a supported timeframe and confluence threshold 4–20.")
    symbol = symbol.upper()
    try:
        candles = await fetch_candles({"1m":"1min","5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h"}[interval], 320, symbol)
        result = analyze_candles(candles, symbol, interval, min_score)
        if result.get("signal"):
            trade, created = record_signal(db, user.id, result["signal"], "QUANTNEX_VIEW")
            db.commit()
            if created:
                event_hub.publish("signals.lifecycle.changed", "signal_trade", "created", {"trade_id": trade.id, "symbol": trade.symbol})
        return result
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except (ValueError, KeyError, IndexError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/quantnex-view/backtest")
async def quantnex_view_backtest(symbol: str = "BTCUSDT", interval: str = "15m",
                                 initial_balance: float = 10000, risk_percent: float = 1,
                                 min_score: int = 6):
    from .quantnex_view_intelligence import backtest_candles
    from .signal_engine import fetch_candles, MarketDataError
    allowed = {"1m", "5m", "15m", "30m", "1h", "4h"}
    if interval not in allowed or not 4 <= min_score <= 20:
        raise HTTPException(status_code=422, detail="Choose a supported timeframe and confluence threshold 4–20.")
    symbol = symbol.upper()
    try:
        candles = await fetch_candles({"1m":"1min","5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h"}[interval], 1000, symbol)
        return backtest_candles(candles, symbol, interval, initial_balance, risk_percent, min_score)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/signals/trades")
def list_signal_trades(symbol: str | None = None, limit: int = 100,
                       user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .signal_lifecycle import trade_payload
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    query = select(SignalTrade).where(SignalTrade.user_id == user.id)
    if symbol:
        query = query.where(SignalTrade.symbol == symbol.strip().upper())
    rows = list(db.scalars(query.order_by(SignalTrade.signal_time.desc(), SignalTrade.id.desc()).limit(limit)))
    result = []
    for trade in rows:
        events = list(db.scalars(select(SignalTradeEvent).where(
            SignalTradeEvent.trade_id == trade.id
        ).order_by(SignalTradeEvent.created_at)))
        result.append(trade_payload(trade, events))
    return result


@app.get("/api/v1/signals/performance")
def signal_performance(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    """Return all-time performance across every symbol for the current local workspace."""
    from .signal_lifecycle import signal_performance_summary
    trades = list(db.scalars(select(SignalTrade).where(SignalTrade.user_id == user.id)))
    return signal_performance_summary(trades)


@app.post("/api/v1/quantnex-view/replay")
async def replay_quantnex_view_signals(payload: dict, user: User = Depends(local_workspace),
                                       db: Session = Depends(get_db)):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from .signal_engine import fetch_candles, MarketDataError, closed_candles
    from .quantnex_view_intelligence import analyze_candles
    from .signal_lifecycle import record_signal, as_utc
    symbol = str(payload.get("symbol") or "BTCUSDT").strip().upper()
    interval = str(payload.get("interval") or "15m")
    min_score = int(payload.get("min_score", 6))
    intervals = {"1m":"1min","5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h"}
    if interval not in intervals or not 4 <= min_score <= 20:
        raise HTTPException(status_code=422, detail="Choose a supported chart timeframe and confluence threshold 4–20.")
    try:
        candles = closed_candles(await fetch_candles(intervals[interval], 3200, symbol), intervals[interval])
        now_local = datetime.now(ZoneInfo("Asia/Colombo"))
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        seconds = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400}[interval]
        first_time = as_utc(candles[0]["time"])
        coverage_complete = first_time <= day_start - timedelta(seconds=seconds * 210)
        start_index = next((i for i, row in enumerate(candles) if as_utc(row["time"]) >= day_start), len(candles))
        def replay_rows():
            candidates = []
            previous_side = None
            for index in range(max(209, start_index), len(candles)):
                window = candles[max(0, index - 319):index + 1]
                result = analyze_candles(window, symbol, interval, min_score)
                signal = result.get("signal")
                if not signal:
                    previous_side = None
                    continue
                side = signal["side"]
                if side != previous_side:
                    signal["signal_candle_time"] = candles[index]["time"]
                    signal["signal_time"] = (as_utc(candles[index]["time"]) + timedelta(seconds=seconds)).isoformat()
                    candidates.append(signal)
                previous_side = side
            return candidates
        candidates = await asyncio.to_thread(replay_rows)
        created = 0
        for signal in candidates:
            _trade, was_created = record_signal(db, user.id, signal, "QUANTNEX_VIEW", deduplicate_active=False)
            created += int(was_created)
        db.commit()
        event_hub.publish("signals.lifecycle.changed", "signal_trade", "history_replayed", {
            "symbol": symbol, "new_trades": created,
        })
        return {
            "symbol": symbol, "interval": interval, "day_start": day_start.isoformat(),
            "coverage_start": first_time.isoformat(), "coverage_complete": coverage_complete,
            "signals_replayed": len(candidates), "new_trades": created,
            "note": ("Full Colombo-day warm-up history is available." if coverage_complete else
                     "PARTIAL HISTORY: provider did not supply 210 warm-up candles before Colombo midnight. Outcomes before the available history will not be guessed."),
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/v1/market/overview")
async def market_overview():
    """Indicative BTC/USD, XAU/USD and converted Sri Lankan gold values."""
    from .market_data import get_market_overview
    try:
        return await get_market_overview()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="A market price provider is temporarily unavailable.")

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "quantnex-api", "version": app.version, "database": "connected"}

@app.get("/api/v1/journal", response_model=list[TradeResponse])
def list_journal(limit: int = 100, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    return list(db.scalars(select(Trade).where(Trade.user_id == user.id).order_by(Trade.id.desc()).limit(limit)))

@app.post("/api/v1/journal", response_model=TradeResponse, status_code=201)
def create_journal(payload: TradeCreate, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if payload.client_ref:
        marker = db.scalar(select(JournalImport).where(
            JournalImport.user_id == user.id,
            JournalImport.source_ref == payload.client_ref,
        ))
        if marker is not None:
            existing = db.get(Trade, marker.trade_id)
            if existing is not None:
                return existing
            raise HTTPException(status_code=409, detail="This journal submission was already processed and then deleted.")
    created_at = payload.created_at
    if created_at is not None:
        created_at = (created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None
                      else created_at.astimezone(timezone.utc))
    item = Trade(user_id=user.id, created_at=created_at or datetime.now(timezone.utc),
                 symbol=payload.symbol, direction=payload.direction,
                 outcome=payload.outcome, pnl=payload.pnl, notes=payload.notes)
    db.add(item)
    db.flush()
    if payload.client_ref:
        db.add(JournalImport(user_id=user.id, source_id="web-create",
                             source_ref=payload.client_ref, trade_id=item.id))
    db.add(WalletTransaction(user_id=user.id, transaction_type="trade_pnl", amount=payload.pnl,
                             description=f"{payload.symbol} {payload.direction.upper()} journal P&L", trade_id=item.id))
    record_audit_event(db, "journal.created", {"trade_id": item.id, "symbol": item.symbol, "direction": item.direction, "pnl": item.pnl})
    db.commit()
    db.refresh(item)
    event_hub.publish("journal.changed", "journal", "created", {"trade_id": item.id, "symbol": item.symbol})
    event_hub.publish("wallet.changed", "wallet", "journal_pnl_recorded", {"trade_id": item.id})
    return item

@app.put("/api/v1/journal/{trade_id}", response_model=TradeResponse)
def update_journal(trade_id: int, payload: TradeCreate,
                   user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    item = db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    created_at = payload.created_at
    if created_at is not None:
        created_at = (created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None
                      else created_at.astimezone(timezone.utc))
        item.created_at = created_at
    item.symbol = payload.symbol
    item.direction = payload.direction
    item.outcome = payload.outcome
    item.pnl = payload.pnl
    item.notes = payload.notes
    # Only reconcile a wallet row that already exists. Imported historical
    # journal entries deliberately have no wallet transaction and stay that way.
    linked = db.scalar(select(WalletTransaction).where(
        WalletTransaction.user_id == user.id,
        WalletTransaction.trade_id == trade_id,
    ))
    if linked is not None:
        linked.amount = payload.pnl
        linked.description = f"{payload.symbol} {payload.direction.upper()} journal P&L"
    record_audit_event(db, "journal.updated", {
        "trade_id": trade_id, "symbol": item.symbol,
        "direction": item.direction, "pnl": item.pnl,
        "wallet_reconciled": linked is not None,
    })
    db.commit()
    db.refresh(item)
    event_hub.publish("journal.changed", "journal", "updated", {"trade_id": trade_id})
    if linked is not None:
        event_hub.publish("wallet.changed", "wallet", "journal_pnl_updated", {"trade_id": trade_id})
    return item


@app.post("/api/v1/journal/import", response_model=LegacyJournalImportResponse)
def import_legacy_journal(payload: LegacyJournalImportRequest,
                          user: User = Depends(local_workspace),
                          db: Session = Depends(get_db)):
    """Import legacy browser journal rows without replaying historical P&L into the wallet.

    source_ref makes retries safe if the browser loses its response
    after the database commit or the import is split into multiple batches.
    """
    imported = 0
    for row in payload.rows:
        exists = db.scalar(select(JournalImport.id).where(
            JournalImport.user_id == user.id,
            JournalImport.source_ref == row.source_ref,
        ))
        if exists is not None:
            continue
        created_at = datetime.now(timezone.utc)
        if row.date:
            try:
                created_at = datetime.fromisoformat(row.date.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="A legacy journal date is invalid.") from exc
            if created_at.tzinfo is None:
                if len(row.date.strip()) == 10:
                    created_at = created_at.replace(hour=12, tzinfo=timezone.utc)
                else:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            else:
                created_at = created_at.astimezone(timezone.utc)
        try:
            with db.begin_nested():
                trade = Trade(user_id=user.id, created_at=created_at, symbol=row.symbol,
                              direction=row.direction, outcome=row.outcome,
                              pnl=row.pnl, notes=row.notes)
                db.add(trade)
                db.flush()
                db.add(JournalImport(user_id=user.id, source_id=payload.source_id,
                                     source_ref=row.source_ref, trade_id=trade.id))
                if row.record_wallet:
                    db.add(WalletTransaction(user_id=user.id, transaction_type="trade_pnl",
                                             amount=row.pnl,
                                             description=f"{row.symbol} {row.direction.upper()} journal P&L",
                                             trade_id=trade.id))
                db.flush()
                imported += 1
        except IntegrityError:
            # Another browser tab may have imported the same source row first.
            if db.scalar(select(JournalImport.id).where(
                JournalImport.user_id == user.id,
                JournalImport.source_ref == row.source_ref,
            )) is None:
                raise
    if imported:
        record_audit_event(db, "journal.legacy_imported",
                           {"source_id": payload.source_id, "imported": imported})
        db.commit()
        event_hub.publish("journal.changed", "journal", "legacy_imported",
                          {"imported": imported})
    return {"imported": imported, "total": len(payload.rows)}


@app.delete("/api/v1/journal/{trade_id}", status_code=204)
def delete_journal(trade_id: int, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    item = db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Journal entry not found.")
    linked = db.scalar(select(WalletTransaction).where(WalletTransaction.user_id == user.id,
                                                        WalletTransaction.trade_id == trade_id))
    if linked is not None:
        db.delete(linked)
    db.delete(item)
    record_audit_event(db, "journal.deleted", {"trade_id": trade_id})
    db.commit()
    event_hub.publish("journal.changed", "journal", "deleted", {"trade_id": trade_id})
    event_hub.publish("wallet.changed", "wallet", "journal_pnl_reversed", {"trade_id": trade_id})

@app.get("/api/v1/wallet/summary", response_model=WalletSummaryResponse)
def wallet_summary(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id)))
    deposits = sum(row.amount for row in rows if row.transaction_type == "deposit")
    withdrawals = sum(abs(row.amount) for row in rows if row.transaction_type == "withdrawal")
    trading_pnl = sum(row.amount for row in rows if row.transaction_type == "trade_pnl")
    return WalletSummaryResponse(balance=round(sum(row.amount for row in rows), 2),
                                 deposits=round(deposits, 2), withdrawals=round(withdrawals, 2),
                                 trading_pnl=round(trading_pnl, 2))

@app.get("/api/v1/wallet/transactions", response_model=list[WalletTransactionResponse])
def wallet_transactions(limit: int = 100, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    return list(db.scalars(select(WalletTransaction).where(WalletTransaction.user_id == user.id)
                           .order_by(WalletTransaction.id.desc()).limit(limit)))

@app.post("/api/v1/wallet/transactions", response_model=WalletTransactionResponse, status_code=201)
def create_wallet_transaction(payload: WalletTransactionCreate, user: User = Depends(local_workspace),
                               db: Session = Depends(get_db)):
    user_id = user.id
    description = payload.description.strip()
    if payload.transaction_type == "withdrawal":
        # Make the balance predicate part of the same INSERT so concurrent
        # withdrawals cannot both spend the same available ledger balance.
        statement = text("""
            INSERT INTO wallet_transactions
                (user_id, created_at, transaction_type, amount, description, trade_id)
            SELECT :user_id, :created_at, :transaction_type, :signed_amount, :description, NULL
            WHERE COALESCE((
                SELECT SUM(amount) FROM wallet_transactions WHERE user_id = :user_id
            ), 0) >= :requested_amount
            RETURNING id
        """)
        params = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc),
            "transaction_type": "withdrawal",
            "signed_amount": -payload.amount,
            "description": description,
            "requested_amount": payload.amount,
        }
        try:
            transaction_id = db.execute(statement, params).scalar_one_or_none()
        except OperationalError as exc:
            # SQLite WAL may reject a stale read snapshot. Retry once only after
            # rolling back; the conditional INSERT is retained on the retry.
            db.rollback()
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            try:
                transaction_id = db.execute(statement, params).scalar_one_or_none()
            except OperationalError as retry_exc:
                db.rollback()
                if "locked" in str(retry_exc).lower() or "busy" in str(retry_exc).lower():
                    raise HTTPException(
                        status_code=503,
                        detail="Wallet is busy. Refresh the balance and try the withdrawal again.",
                    ) from None
                raise
        if transaction_id is None:
            db.rollback()
            raise HTTPException(status_code=409, detail="Insufficient wallet balance for this withdrawal.")
        item = db.get(WalletTransaction, transaction_id)
        if item is None:
            db.rollback()
            raise HTTPException(status_code=500, detail="Wallet transaction could not be loaded after saving.")
    else:
        item = WalletTransaction(user_id=user_id, transaction_type="deposit",
                                 amount=payload.amount, description=description)
        db.add(item)
    record_audit_event(db, "wallet.transaction_created", {
        "transaction_type": item.transaction_type, "amount": item.amount
    })
    db.commit()
    db.refresh(item)
    event_hub.publish("wallet.changed", "wallet", "transaction_created", {
        "transaction_id": item.id, "transaction_type": item.transaction_type, "amount": item.amount
    })
    return item

@app.get("/api/v1/preferences", response_model=list[PreferenceResponse])
def get_preferences(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    return list(db.scalars(select(Preference).where(Preference.user_id == user.id).order_by(Preference.key)))

@app.put("/api/v1/preferences/{key}", response_model=PreferenceResponse)
def set_preference(key: str, payload: PreferenceWrite, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not key.replace("_", "").isalnum() or len(key) > 64:
        raise HTTPException(status_code=422, detail="Invalid preference key.")
    item = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.key == key))
    if item is None:
        item = Preference(user_id=user.id, key=key, value=payload.value)
        db.add(item)
    else:
        item.value = payload.value
    record_audit_event(db, "preference.updated", {"key": key})
    db.commit()
    db.refresh(item)
    event_hub.publish("preferences.changed", "preferences", "updated", {"key": key})
    return item

@app.get("/api/v1/ai/status")
def ai_status(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .ai_assistant import get_openai_config
    try:
        key, model = get_openai_config(db, user.id)
    except ValueError:
        key, model = "", "gpt-5.5"
    return {"configured": bool(key), "provider": "OpenAI" if key else None,
            "model": model, "api_key_saved": bool(_preference(db, user.id, "openai_api_key_enc")),
            "web_search_enabled": _preference(db, user.id, "openai_web_search_enabled", "false") == "true",
            "note": "API key is stored encrypted on the local backend and is never returned."}

@app.post("/api/v1/ai/config")
def save_ai_config(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    api_key = str(payload.get("api_key") or "").strip()
    model = str(payload.get("model") or "gpt-5.5").strip()
    if len(model) > 120 or not re.fullmatch(r"[A-Za-z0-9._:-]+", model):
        raise HTTPException(status_code=422, detail="Enter a valid OpenAI model identifier.")
    if api_key:
        if not api_key.startswith("sk-") or len(api_key) < 20 or len(api_key) > 512:
            raise HTTPException(status_code=422, detail="OpenAI API key format is invalid.")
        _save_preference(db, user.id, "openai_api_key_enc", encrypt_secret(api_key))
    _save_preference(db, user.id, "openai_model", model)
    _save_preference(db, user.id, "openai_web_search_enabled",
                     "true" if payload.get("web_search_enabled") is True else "false")
    record_audit_event(db, "ai.configuration_updated", {"api_key_replaced": bool(api_key), "model": model})
    db.commit()
    return {"ok": True, "api_key_saved": bool(_preference(db, user.id, "openai_api_key_enc")),
            "model": model, "web_search_enabled": _preference(db, user.id, "openai_web_search_enabled") == "true"}

@app.delete("/api/v1/ai/config")
def delete_ai_config(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    row = db.scalar(select(Preference).where(Preference.user_id == user.id, Preference.key == "openai_api_key_enc"))
    if row:
        db.delete(row)
    record_audit_event(db, "ai.configuration_deleted", {})
    db.commit()
    return {"ok": True, "api_key_saved": False}

@app.post("/api/v1/ai/test")
async def test_ai_config(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .ai_assistant import get_openai_config
    try:
        key, model = get_openai_config(db, user.id)
        if not key:
            raise HTTPException(status_code=409, detail="Add an OpenAI API key first.")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://api.openai.com/v1/models/" + model,
                headers={"Authorization": f"Bearer {key}"})
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="OpenAI rejected this API key.")
        if response.status_code == 404:
            raise HTTPException(status_code=422, detail="This model is not available to the configured API project.")
        response.raise_for_status()
        return {"ok": True, "model": model, "message": "OpenAI API key and model access verified."}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="Could not verify OpenAI. Check internet access, API key and project billing.")

@app.post("/api/v1/ai/chat", response_model=AIChatResponse)
async def ai_chat(payload: AIChatRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .ai_assistant import ask_openai
    try:
        reply, model = await ask_openai(db, user.id, payload.message)
        return AIChatResponse(reply=reply, model=model)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            raise HTTPException(status_code=401, detail="OpenAI rejected the saved API key.")
        raise HTTPException(status_code=502, detail="OpenAI request failed. Check model access and API billing.")
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        raise HTTPException(status_code=502, detail="OpenAI assistant request failed.")


@app.post("/api/v1/telegram/send")
async def send_telegram_message(payload: TelegramSendRequest, user: User = Depends(local_workspace)):
    """Send one user-triggered Telegram message; bot credentials are never stored."""
    import re
    if not re.fullmatch(r"[0-9]{5,12}:[A-Za-z0-9_-]{20,}", payload.bot_token):
        raise HTTPException(status_code=422, detail="Telegram bot token format is invalid.")
    if not re.fullmatch(r"(?:@[A-Za-z0-9_]{5,}|-?[0-9]{1,20})", payload.chat_id.strip()):
        raise HTTPException(status_code=422, detail="Use a numeric chat ID or @channel username.")
    url = "https://api.telegram.org/bot" + payload.bot_token + "/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(url, json={"chat_id": payload.chat_id.strip(),
                                                    "text": payload.message,
                                                    "disable_web_page_preview": True})
        data = response.json()
        if response.status_code >= 400 or not data.get("ok"):
            raise HTTPException(status_code=502, detail="Telegram rejected the message. Check the bot token, chat ID and bot permissions.")
        return {"ok": True, "message_id": data.get("result", {}).get("message_id")}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Telegram request timed out.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach Telegram. Check the server internet connection.")


def _preference(db: Session, user_id: int, key: str, default: str = "") -> str:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    return row.value if row else default

def _save_preference(db: Session, user_id: int, key: str, value: str) -> None:
    row = db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.key == key))
    if row is None:
        db.add(Preference(user_id=user_id, key=key, value=value))
    else:
        row.value = value

DEFAULT_SIGNAL_SETTINGS = {"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1.0,"min_score":7}

@app.get("/api/v1/signals/status")
def signal_engine_status(user: User = Depends(local_workspace)):
    from .signal_engine import gold_feed_configured, gold_feed_provider
    return {"configured": True, "crypto_configured": True, "gold_configured": gold_feed_configured(),
            "providers":{"crypto":"Binance Spot public candles; Coinbase Exchange fallback for BTC/ETH/SOL","gold":gold_feed_provider()},
            "note":"Signal results report the actual provider used for their selected timeframes. Crypto uses Binance Spot with Coinbase Exchange fallback for BTC/ETH/SOL; XAUUSD uses the configured local read-only MT5 terminal or Twelve Data."}

@app.get("/api/v1/signals/settings")
def get_signal_settings(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    try: settings=json.loads(_preference(db,user.id,"signal_settings",json.dumps(DEFAULT_SIGNAL_SETTINGS)))
    except ValueError: settings=DEFAULT_SIGNAL_SETTINGS
    return settings

@app.put("/api/v1/signals/settings")
def update_signal_settings(payload: SignalSettingsRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    settings=payload.model_dump()
    _save_preference(db,user.id,"signal_settings",json.dumps(settings))
    record_audit_event(db, "signals.settings_updated", {"primary": settings["primary"], "trend": settings["trend"]})
    db.commit()
    event_hub.publish("preferences.changed", "signals", "settings_updated", {"key": "signal_settings"})
    return settings

@app.post("/api/v1/signals/backtest")
async def signal_engine_backtest(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .signal_engine import (
        MarketDataError, aggregate_minutes, fetch_binance_historical_candles,
        get_binance_spot_symbol_info, is_binance_spot_symbol,
    )
    from .signal_backtest import run_signal_walk_forward
    symbol = str(payload.get("symbol") or "BTCUSDT").strip().upper()
    try:
        if not await is_binance_spot_symbol(symbol):
            raise HTTPException(status_code=422, detail="Choose a currently tradable Binance Spot pair.")
        try:
            settings = payload.get("settings") or json.loads(
                _preference(db, user.id, "signal_settings", json.dumps(DEFAULT_SIGNAL_SETTINGS))
            )
        except (ValueError, TypeError):
            settings = DEFAULT_SIGNAL_SETTINGS
        if not isinstance(settings, dict):
            raise ValueError("Signal settings must be an object.")
        enabled_raw = settings.get("enabled", ["60", "30", "15", "5", "1"])
        if not isinstance(enabled_raw, list):
            raise ValueError("Enabled replay timeframes must be a list.")
        settings = {
            **settings,
            "primary": str(settings.get("primary", "5")),
            "trend": str(settings.get("trend", "60")),
            "enabled": [str(item) for item in enabled_raw],
            "min_score": int(settings.get("min_score", 7)),
            "estimated_taker_fee_bps_per_side": float(payload.get("taker_fee_bps_per_side", 10.0)),
            "estimated_maker_fee_bps_per_side": float(payload.get("maker_fee_bps_per_side", 8.0)),
            "estimated_slippage_bps_per_side": float(payload.get("slippage_bps_per_side", 2.5)),
        }
        if settings["primary"] not in {"1", "5", "15", "30", "50", "60"} or settings["trend"] not in {"15", "30", "60"}:
            raise ValueError("Signal replay supports 1m/5m/15m/30m/M50/1h entry timeframes with 15m/30m/1h trend timeframes.")
        days = int(payload.get("days", 14 if settings["primary"] == "1" else 30))
        minimum_days = 21 if settings["primary"] == "60" else 18 if settings["primary"] == "50" else 14
        maximum_days = 14 if settings["primary"] == "1" else 30
        if not minimum_days <= days <= maximum_days:
            raise ValueError(f"Selected timeframe requires between {minimum_days} and {maximum_days} days of historical data.")
        allowed_timeframes = {"1", "5", "15", "30", "50", "60"}
        if not settings["enabled"] or any(tf not in allowed_timeframes for tf in settings["enabled"]):
            raise ValueError("Enabled replay timeframes must be selected from 1m, 5m, 15m, 30m, M50 and 1h.")
        if not 6 <= settings["min_score"] <= 10:
            raise ValueError("Minimum signal confluence must be between 6 and 10.")
        history = await fetch_binance_historical_candles(symbol, "1m", days, max_candles=days * 1440)
        if not history:
            raise MarketDataError("Binance returned no closed 1m candles for the selected replay window.")
        candles_by_tf = {"1": history}
        for timeframe in (5, 15, 30, 50, 60):
            candles_by_tf[str(timeframe)] = aggregate_minutes(history, timeframe, require_complete=True)
        symbol_info = await get_binance_spot_symbol_info(symbol)
        include_order_flow_replay = payload.get("include_order_flow_replay", True)
        if not isinstance(include_order_flow_replay, bool):
            raise ValueError("include_order_flow_replay must be a boolean.")
        order_flow_observations = None
        if include_order_flow_replay:
            from .order_flow_recorder import load_order_flow_observations

            first_candle = datetime.fromisoformat(str(history[0]["time"]).replace("Z", "+00:00"))
            last_candle = datetime.fromisoformat(str(history[-1]["time"]).replace("Z", "+00:00"))
            if first_candle.tzinfo is None:
                first_candle = first_candle.replace(tzinfo=timezone.utc)
            if last_candle.tzinfo is None:
                last_candle = last_candle.replace(tzinfo=timezone.utc)
            history_start = first_candle.astimezone(timezone.utc)
            history_end = last_candle.astimezone(timezone.utc) + timedelta(minutes=1)
            order_flow_observations = load_order_flow_observations(
                db, symbol, history_start, history_end, limit=20000
            )
        result = await run_signal_walk_forward(
            symbol, candles_by_tf, symbol_info, settings,
            train_ratio=float(payload.get("train_ratio", 0.7)),
            assumed_spread_bps=float(payload.get("assumed_spread_bps", 5.0)),
            assumed_depth_usd=float(payload.get("assumed_depth_usd", 10000.0)),
            order_flow_observations=order_flow_observations,
        )
        result["order_flow_capture"] = {
            "requested": include_order_flow_replay,
            "status": (
                "AVAILABLE" if order_flow_observations
                else "NO_CAPTURED_ORDER_FLOW_DATA" if include_order_flow_replay
                else "DISABLED"
            ),
            "observation_count": len(order_flow_observations or []),
            "retention_days": 7,
            "sampling": "At most one sequence-validated feature snapshot per active symbol per UTC minute.",
            "window_start": history_start.isoformat() if include_order_flow_replay else None,
            "window_end": history_end.isoformat() if include_order_flow_replay else None,
        }
    except HTTPException:
        raise
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Historical Binance market data is temporarily unavailable.") from exc
    db.add(StrategyLabRun(
        user_id=user.id, run_type="SIGNAL_WALK_FORWARD", symbol=symbol,
        timeframe=settings["primary"] + "m", strategy_json=json.dumps(settings),
        result_json=json.dumps(result),
    ))
    record_audit_event(db, "signals.walk_forward_backtest", {
        "symbol": symbol, "days": days,
        "training_trades": result["training"]["trade_count"],
        "out_of_sample_trades": result["out_of_sample"]["trade_count"],
        "order_flow_snapshots": len(order_flow_observations or []),
    })
    db.commit()
    event_hub.publish("strategy.research.changed", "strategy", "signal_walk_forward_saved", {"symbol": symbol})
    return result


@app.post("/api/v1/signals/scan")
async def scan_market_signal(symbol: str = "BTCUSDT", user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .signal_engine import build_signal, MarketDataError, is_binance_spot_symbol, gold_feed_configured
    symbol = symbol.upper()
    try:
        supported_crypto = await is_binance_spot_symbol(symbol)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not supported_crypto and symbol != "XAUUSD":
        raise HTTPException(status_code=422, detail="Choose a currently tradable Binance Spot pair or XAUUSD.")
    if symbol == "XAUUSD" and not gold_feed_configured():
        raise HTTPException(status_code=503,detail="Gold market feed not configured. Enable the local MT5 feed or add TWELVE_DATA_API_KEY to backend/.env, then restart the API.")
    try: settings=json.loads(_preference(db,user.id,"signal_settings",json.dumps(DEFAULT_SIGNAL_SETTINGS)))
    except ValueError: settings=DEFAULT_SIGNAL_SETTINGS
    try:
        result=await build_signal(settings, symbol)
    except MarketDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Could not retrieve "+symbol+" candles from the configured market-data provider.")
    signal=result.get("signal")
    if signal:
        from .signal_lifecycle import record_signal
        tracked, created = record_signal(db, user.id, signal, "MULTI_TF_SCAN")
        if created:
            event_hub.publish("signals.lifecycle.changed", "signal_trade", "created", {"trade_id": tracked.id, "symbol": tracked.symbol})
        token_enc=_preference(db,user.id,"telegram_bot_token_enc")
        chat_id=_preference(db,user.id,"telegram_chat_id")
        if token_enc and chat_id and created:
            try:
                token=decrypt_secret(token_enc)
                market_symbol=result.get("symbol",symbol)
                message=("QUANTNEX · "+market_symbol+" "+signal["side"]+" SIGNAL\nMarket data: "+str(result.get("provider","Unknown"))+
                    "\nEntry type: "+str(signal.get("entry_type","REFERENCE"))+"\nEntry: "+("MARKET ("+str(signal["entry"])+")" if signal.get("entry_type")=="MARKET" else "LIMIT ("+str(signal.get("limit_price") or signal["entry"])+")")+
                    ("\nEntry reference: "+str(signal.get("entry_reference_note")) if signal.get("entry_reference_note") else "")+
                    ("\nLimit price: "+str(signal["limit_price"]) if signal.get("entry_type")=="LIMIT" else "")+
                    ("\nEntry expires: "+str(signal["entry_expires_at"]) if signal.get("entry_expires_at") else "")+
                    "\nEntry logic: "+str(signal.get("entry_selection_reason",""))+
                    ("\nSpread: "+str(signal["execution_quality"]["spread_bps"])+" bps · estimated round-trip cost: "+str(signal["execution_quality"]["estimated_round_trip_cost_bps"])+" bps" if signal.get("execution_quality") else "")+
                    "\nSL: "+str(signal["stop_loss"])+
                    "\nTP1: "+str(signal["tp1"])+"\nTP2: "+str(signal["tp2"])+"\nTP3: "+str(signal["tp3"])+
                    "\nConfluence: "+str(signal["score"])+"/10 (rule count, not win probability)\n"
                    +"TF alignment: "+", ".join(str(tf)+"m "+str(bias) for tf,bias in (signal.get("timeframe_alignment") or {}).items())+"\n"
                    +"Confirmations: "+", ".join(signal["confirmations"])+
                    "\nSignal only. Verify spread, fees and execution. No broker order is placed.")
                async with httpx.AsyncClient(timeout=12) as client:
                    response=await client.post("https://api.telegram.org/bot"+token+"/sendMessage",
                        json={"chat_id":chat_id,"text":message,"disable_web_page_preview":True})
                    response.raise_for_status()
                result["telegram_sent"]=True
            except Exception: result["telegram_sent"]=False
        else:
            result["telegram_sent"]=False
            result["telegram_note"]="Connect your Telegram bot to send this signal."
    elif symbol=="XAUUSD":
        _save_preference(db,user.id,"active_signal","")
    db.commit()
    event_hub.publish("signals.changed", "signals", "scan_completed", {"symbol": result.get("symbol")})
    return result

@app.post("/api/v1/telegram/connect")
async def connect_telegram_bot(payload: TelegramConnectRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not re.fullmatch(r"[0-9]{5,12}:[A-Za-z0-9_-]{20,}",payload.bot_token):
        raise HTTPException(status_code=422,detail="Telegram bot token format is invalid.")
    if not re.fullmatch(r"(?:@[A-Za-z0-9_]{5,}|-?[0-9]{1,20})",payload.chat_id.strip()):
        raise HTTPException(status_code=422,detail="Use a numeric chat ID or @channel username.")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            bot_response=await client.get("https://api.telegram.org/bot"+payload.bot_token+"/getMe")
            bot_data=bot_response.json()
            if bot_response.status_code>=400 or not isinstance(bot_data,dict) or not bot_data.get("ok"):
                raise HTTPException(status_code=422,detail="Telegram rejected this bot token. Check the BotFather token.")
            bot=bot_data.get("result",{})
            chat_response=await client.get(
                "https://api.telegram.org/bot"+payload.bot_token+"/getChat",
                params={"chat_id":payload.chat_id.strip()},
            )
            chat_data=chat_response.json()
            if chat_response.status_code>=400 or not isinstance(chat_data,dict) or not chat_data.get("ok"):
                raise HTTPException(
                    status_code=422,
                    detail="Telegram cannot resolve this destination. Send /start to your bot or add it to the intended group/channel, then check the chat ID.",
                )
            chat=chat_data.get("result",{})
            if str(chat.get("id",""))==str(bot.get("id","")):
                raise HTTPException(
                    status_code=422,
                    detail="This chat ID points to the bot itself. Use your private chat ID or the intended group/channel ID.",
                )
            chat_type=str(chat.get("type",""))
            if chat_type in {"channel","group","supergroup"}:
                member_response=await client.get(
                    "https://api.telegram.org/bot"+payload.bot_token+"/getChatMember",
                    params={"chat_id":chat.get("id"),"user_id":bot.get("id")},
                )
                member_data=member_response.json()
                if member_response.status_code>=400 or not isinstance(member_data,dict) or not member_data.get("ok"):
                    raise HTTPException(
                        status_code=422,
                        detail="Telegram could not verify the bot's membership in this group/channel. Add the bot and check its permissions.",
                    )
                member=member_data.get("result",{})
                member_status=str(member.get("status",""))
                if chat_type=="channel":
                    if member_status=="creator":
                        pass
                    elif member_status!="administrator" or member.get("can_post_messages") is not True:
                        raise HTTPException(status_code=422,detail="The bot must be a channel administrator with permission to post messages.")
                elif member_status not in {"member","administrator","creator"} and not (
                    member_status=="restricted" and member.get("can_send_messages") is True
                ):
                    raise HTTPException(status_code=422,detail="The bot is not allowed to send messages in this group.")
            elif chat_type!="private":
                raise HTTPException(status_code=422,detail="Choose a private chat, group, supergroup or channel as the Telegram destination.")
    except HTTPException:
        raise
    except (httpx.HTTPError,ValueError):
        raise HTTPException(status_code=502,detail="Could not verify the Telegram bot and destination. Check your connection and try again.")
    _save_preference(db,user.id,"telegram_bot_token_enc",encrypt_secret(payload.bot_token))
    _save_preference(db,user.id,"telegram_chat_id",payload.chat_id.strip())
    _save_preference(db,user.id,"telegram_bot_username",bot.get("username",""))
    _save_preference(db,user.id,"telegram_bot_display_name",payload.display_name.strip() or bot.get("first_name","QUANTNEX Bot"))
    record_audit_event(db, "telegram.connected", {"bot_username": bot.get("username", ""), "destination_type": chat_type})
    db.commit()
    event_hub.publish("integration.changed", "telegram", "connected", {"bot_username": bot.get("username", "")})
    return {"connected":True,"bot_username":bot.get("username"),"chat_id":payload.chat_id.strip(),
            "destination_type":chat_type,"destination_title":chat.get("title") or chat.get("first_name"),
            "commands":["/help","/timeframes","/settf 5","/settrend 60","/setanalysis 1,5,15,30,60","/scan BTCUSDT","/scan ETHUSDT","/scan SOLUSDT","/scan XAUUSD","/status"],
            "note":"The bot and destination were verified. The local API must remain running for bot commands and TP1/SL level alerts."}

@app.get("/api/v1/telegram/status")
def telegram_status(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    return {"connected":connected,"bot_username":_preference(db,user.id,"telegram_bot_username") if connected else None,
            "display_name":_preference(db,user.id,"telegram_bot_display_name") if connected else None,
            "chat_id":_preference(db,user.id,"telegram_chat_id") if connected else None,
            "worker":"active while this API process is running"}

@app.delete("/api/v1/telegram/connect")
def disconnect_telegram_bot(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    for key in ["telegram_bot_token_enc","telegram_chat_id","telegram_bot_username","telegram_bot_display_name","telegram_update_offset","active_signal","telegram_daily_report_enabled","telegram_daily_report_sent_date","auto_signal_settings","auto_signal_last_fingerprint","auto_signal_last_fingerprint_btcusdt","auto_signal_last_fingerprint_ethusdt","auto_signal_last_fingerprint_solusdt","auto_signal_last_fingerprint_xauusd"]:
        row=db.scalar(select(Preference).where(Preference.user_id==user.id,Preference.key==key))
        if row:db.delete(row)
    record_audit_event(db, "telegram.disconnected")
    db.commit()
    event_hub.publish("integration.changed", "telegram", "disconnected", {"connected": False})
    return {"connected":False}

def backup_legacy_database(db: Session) -> None:
    """Create a recoverable SQLite snapshot before clearing legacy login data."""
    users = list(db.scalars(select(User).order_by(User.id)))
    if not users:
        return
    needs_migration = len(users) > 1 or users[0].email != "local@quantnex.invalid" or bool(users[0].password_hash)
    if not needs_migration or not DATABASE_URL.startswith("sqlite:///"):
        return

    raw_path = DATABASE_URL[len("sqlite:///"):].split("?", 1)[0]
    if raw_path == ":memory:":
        return
    database_path = Path(raw_path)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    if not database_path.is_file():
        return

    backup_dir = Path(__file__).resolve().parents[2] / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / ("quantnex-pre-local-only-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
    try:
        source = sqlite3.connect(str(database_path))
        target = sqlite3.connect(str(backup_path))
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    print(f"[QUANTNEX] Legacy database backup created: {backup_path}", flush=True)


async def prepare_local_workspace():
    """Back up and migrate legacy accounts before the Telegram worker starts."""
    db = SessionLocal()
    try:
        backup_legacy_database(db)
        local_workspace(db)
    finally:
        db.close()


async def start_telegram_background_worker():
    from .telegram_worker import telegram_worker
    app.state.telegram_worker_task=asyncio.create_task(telegram_worker())

async def start_signal_lifecycle_worker():
    from .signal_lifecycle import signal_lifecycle_worker
    app.state.signal_lifecycle_task = asyncio.create_task(signal_lifecycle_worker())


async def stop_signal_lifecycle_worker():
    task = getattr(app.state, "signal_lifecycle_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def stop_telegram_background_worker():
    task=getattr(app.state,"telegram_worker_task",None)
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass

async def start_prop_challenge_guardian():
    app.state.prop_challenge_guardian_task = asyncio.create_task(mt5_guardian_worker())


async def stop_prop_challenge_guardian():
    task = getattr(app.state, "prop_challenge_guardian_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

@app.get("/api/v1/telegram/auto-signals")
def get_auto_signal_settings(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    raw=_preference(
        db,user.id,"auto_signal_settings",
        '{"enabled":false,"interval_seconds":180,"universe_mode":"ALL_BINANCE_SPOT","scan_batch_size":20,"symbols":[]}',
    )
    from .telegram_worker import _normalise_auto_signal_settings
    settings=_normalise_auto_signal_settings(raw)
    settings["telegram_connected"]=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    from .signal_engine import gold_feed_configured
    settings["crypto_feed_configured"]=True
    settings["gold_feed_configured"]=gold_feed_configured()
    return settings

@app.put("/api/v1/telegram/auto-signals")
async def set_auto_signal_settings(payload: AutoSignalSettingsRequest, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    if payload.enabled and not connected:
        raise HTTPException(status_code=409,detail="Connect and test your personal Telegram bot before enabling Auto Signals.")
    from .signal_engine import (
        gold_feed_configured, get_binance_spot_symbols, is_binance_spot_symbol, MarketDataError,
    )
    universe_mode = payload.universe_mode or (
        "SELECTED" if payload.symbols else "ALL_BINANCE_SPOT"
    )
    if universe_mode == "SELECTED" and not payload.symbols:
        raise HTTPException(status_code=422, detail="Select at least one market for a custom watchlist.")
    if universe_mode == "ALL_BINANCE_SPOT":
        unsupported_additions = [symbol for symbol in payload.symbols if symbol != "XAUUSD"]
        if unsupported_additions:
            raise HTTPException(
                status_code=422,
                detail="All Binance Spot mode discovers pairs automatically. Use Custom watchlist for selected Binance pairs.",
            )
    if payload.enabled and "XAUUSD" in payload.symbols and not gold_feed_configured():
        raise HTTPException(status_code=503,detail="XAUUSD is selected but no historical Gold feed is configured. Enable the local MT5 feed or add TWELVE_DATA_API_KEY to backend/.env.")
    if payload.enabled and universe_mode == "ALL_BINANCE_SPOT":
        try:
            universe = await get_binance_spot_symbols()
        except MarketDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if not universe:
            raise HTTPException(status_code=503, detail="Binance returned no eligible Spot pairs for automatic scanning.")
    if payload.enabled and universe_mode == "SELECTED":
        try:
            invalid = [symbol for symbol in payload.symbols
                       if symbol != "XAUUSD" and not await is_binance_spot_symbol(symbol)]
        except MarketDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if invalid:
            raise HTTPException(status_code=422, detail="These symbols are not currently tradable Binance Spot pairs: " + ", ".join(invalid))
    settings=payload.model_dump()
    settings["universe_mode"]=universe_mode
    _save_preference(db,user.id,"auto_signal_settings",json.dumps(settings))
    record_audit_event(db, "signals.auto_settings_updated", {
        "enabled": settings["enabled"], "interval_seconds": settings["interval_seconds"],
        "universe_mode": settings["universe_mode"], "scan_batch_size": settings["scan_batch_size"],
        "symbols": settings["symbols"],
    })
    db.commit()
    event_hub.publish("preferences.changed", "signals", "auto_settings_updated", {
        "key": "auto_signal_settings", "enabled": settings["enabled"],
        "universe_mode": settings["universe_mode"], "symbols": settings["symbols"],
    })
    return {
        **settings, "telegram_connected": connected, "gold_feed_configured": gold_feed_configured(),
        "note": "Auto Signals rotates through the full eligible Binance Spot universe in bounded batches while the local QUANTNEX API and Telegram worker are running. No live orders are placed.",
    }

@app.get("/api/v1/telegram/reports")
def get_telegram_report_settings(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    enabled=_preference(db,user.id,"telegram_daily_report_enabled","false")=="true"
    return {"enabled":enabled,"schedule":"20:00","timezone":"Asia/Colombo","telegram_connected":connected}

@app.put("/api/v1/telegram/reports")
def set_telegram_report_settings(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    enabled=payload.get("enabled")
    if not isinstance(enabled,bool):
        raise HTTPException(status_code=422,detail="enabled must be true or false.")
    connected=bool(_preference(db,user.id,"telegram_bot_token_enc") and _preference(db,user.id,"telegram_chat_id"))
    if enabled and not connected:
        raise HTTPException(status_code=409,detail="Connect your Telegram bot before enabling daily PDF reports.")
    _save_preference(db,user.id,"telegram_daily_report_enabled","true" if enabled else "false")
    record_audit_event(db,"telegram.daily_report_settings_updated",{"enabled":enabled,"schedule":"20:00","timezone":"Asia/Colombo"})
    db.commit()
    return {"enabled":enabled,"schedule":"20:00","timezone":"Asia/Colombo","telegram_connected":connected}

@app.post("/api/v1/telegram/notify")
async def notify_connected_telegram(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    message=payload.get("message")
    if not isinstance(message,str) or not message.strip() or len(message)>4096:
        raise HTTPException(status_code=422,detail="Message must contain 1–4096 characters.")
    notification_key=payload.get("notification_key")
    if notification_key is not None and (
        not isinstance(notification_key,str) or not notification_key.strip()
        or len(notification_key)>145
        or not re.fullmatch(r"[A-Za-z0-9:_-]+",notification_key)
    ):
        raise HTTPException(status_code=422,detail="notification_key must be 1–145 safe characters.")
    token_enc=_preference(db,user.id,"telegram_bot_token_enc")
    chat_id=_preference(db,user.id,"telegram_chat_id")
    if not token_enc or not chat_id:
        raise HTTPException(status_code=409,detail="Connect your Telegram bot first.")
    try: token=decrypt_secret(token_enc)
    except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc))
    delivery_key="client-notice:"+notification_key if notification_key else ""
    claimed=False
    if delivery_key:
        from .telegram_worker import _claim_telegram_delivery, _finish_telegram_delivery
        claimed=_claim_telegram_delivery(db,user.id,delivery_key)
        if not claimed:
            return {"ok":True,"duplicate":True}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.post("https://api.telegram.org/bot"+token+"/sendMessage",
                json={"chat_id":chat_id,"text":message,"disable_web_page_preview":True})
            data=response.json()
        if response.status_code>=400 or not data.get("ok"):
            if claimed:
                _finish_telegram_delivery(db,user.id,delivery_key,False)
            raise HTTPException(status_code=502,detail="Telegram rejected the message. Check bot permissions and chat ID.")
        if claimed:
            _finish_telegram_delivery(db,user.id,delivery_key,True)
        return {"ok":True,"duplicate":False,"message_id":data.get("result",{}).get("message_id")}
    except httpx.HTTPError:
        if claimed:
            _finish_telegram_delivery(db,user.id,delivery_key,False)
        raise HTTPException(status_code=502,detail="Could not reach Telegram.")

async def start_daily_backup_worker():
    app.state.daily_backup_task = asyncio.create_task(daily_backup_worker())


async def stop_daily_backup_worker():
    task = getattr(app.state, "daily_backup_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.get("/api/v1/signals/markets")
async def signal_markets(user: User = Depends(local_workspace)):
    """List the current tradable Binance Spot universe for the signal selector."""
    from .signal_engine import get_binance_spot_symbols, MarketDataError
    try:
        symbols = await get_binance_spot_symbols()
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "market_type": "BINANCE_SPOT",
        "count": len(symbols),
        "symbols": symbols,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "Dynamically loaded from Binance exchangeInfo. Inactive and non-Spot symbols are excluded.",
    }


# ---------------------------------------------------------------------------
# Phase 07 — multi-market intelligence, paper trading, performance and risk.
# All trading endpoints are simulation-only. No broker execution is available.
# ---------------------------------------------------------------------------
@app.get("/api/v1/intelligence/markets")
async def intelligence_markets(user: User = Depends(local_workspace)):
    from .phase07_engine import get_market_board
    return await get_market_board()

# Phase 10 — source-time and candle-integrity validation.
@app.get("/api/v1/data-reliability/markets")
async def data_reliability_markets(user: User = Depends(local_workspace)):
    from .phase07_engine import get_market_board
    from .phase10_engine import assess_quote
    board=await get_market_board()
    items=[]
    for item in board.get("items",[]):
        if item.get("status")!="ok":
            items.append({"symbol":item.get("symbol"),"provider":item.get("provider"),
                          "status":"UNSAFE","trading_safe":False,"issues":["PROVIDER_UNAVAILABLE"]})
        else:
            health=item.get("data_health") or assess_quote(item)
            items.append({"symbol":item.get("symbol"),"label":item.get("label"),"provider":item.get("provider"),
                          "price":item.get("price"),"change_percent":item.get("change_percent"),
                          "health":health,"status":health["status"],"trading_safe":health["trading_safe"]})
    return {"items":items,"timestamp":board.get("timestamp"),
            "trading_safe":all(x.get("trading_safe",False) for x in items),
            "note":"A failed market is isolated; it does not imply every supported market is unavailable."}

@app.get("/api/v1/data-reliability/market/{symbol}")
async def data_reliability_market(symbol: str, timeframe: str = "15m",
                                  user: User = Depends(local_workspace)):
    from .phase07_engine import get_quote,get_candles,market_info,IntelligenceDataError
    from .phase10_engine import assess_market_snapshot
    try:
        info=market_info(symbol)
        quote=await get_quote(info["symbol"])
        candles=_closed_strategy_candles(await get_candles(info["symbol"],timeframe,250),timeframe)
        health=assess_market_snapshot(quote,candles,timeframe)
        return {**health,"timeframe":timeframe,"price":quote["price"]}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail={"message":str(exc),"trading_safe":False})
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail={"message":"Market provider request failed.","trading_safe":False})

@app.get("/api/v1/intelligence/market/{symbol}/candles")
async def intelligence_candles(symbol: str, timeframe: str = "15m",
                                user: User = Depends(local_workspace)):
    from .phase07_engine import get_candles, market_info, IntelligenceDataError
    try:
        info=market_info(symbol)
        candles=await get_candles(info["symbol"],timeframe)
        return {"symbol":info["symbol"],"timeframe":timeframe,"provider":info["provider"],
                "candles":candles,"count":len(candles)}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")

@app.get("/api/v1/intelligence/market/{symbol}/orderbook")
async def intelligence_orderbook(symbol: str, user: User = Depends(local_workspace)):
    from .phase07_engine import get_order_book, market_info
    try:
        return await get_order_book(market_info(symbol)["symbol"])
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Order-book provider is temporarily unavailable.")

@app.get("/api/v1/order-flow/spot/{symbol}")
async def quantnex_view_spot_order_flow(symbol: str, wait_seconds: float = 0.0, user: User = Depends(local_workspace)):
    """Read-only, sequence-validated Binance Spot L2 and observed AggTrade flow."""
    from .signal_engine import MarketDataError, get_binance_spot_symbol_info, is_binance_spot_symbol
    from .binance_order_flow_manager import BinanceSpotOrderFlowManagerError, get_binance_spot_order_flow_manager
    from .order_flow import OrderFlowDataError, calculate_order_book_metrics

    normalized = str(symbol or "").strip().upper()
    if not math.isfinite(wait_seconds) or not 0.0 <= wait_seconds <= 1.5:
        raise HTTPException(status_code=422, detail="wait_seconds must be between 0 and 1.5.")
    try:
        if not await is_binance_spot_symbol(normalized):
            raise HTTPException(status_code=422, detail="Symbol is not an active, eligible Binance Spot pair.")
        info = await get_binance_spot_symbol_info(normalized)
        filters = info.get("filters") if isinstance(info, dict) else None
        price_filter = filters.get("PRICE_FILTER") if isinstance(filters, dict) else None
        tick_size = price_filter.get("tickSize") if isinstance(price_filter, dict) else None
        if not tick_size:
            raise HTTPException(status_code=422, detail="Binance Spot symbol metadata has no valid PRICE_FILTER tickSize.")
        snapshot = await get_binance_spot_order_flow_manager().get_snapshot(
            normalized, str(tick_size), wait_seconds=wait_seconds,
            max_trade_age_seconds=15.0, max_depth_age_seconds=5.0,
        )
        depth = snapshot.get("depth_book") if isinstance(snapshot, dict) else None
        depth_age = snapshot.get("depth_age_seconds") if isinstance(snapshot, dict) else None
        depth_ready = bool(
            isinstance(depth, dict) and depth.get("valid") is True
            and depth.get("sequence_validated") is True
            and isinstance(depth_age, (int, float)) and not isinstance(depth_age, bool)
            and math.isfinite(float(depth_age)) and 0.0 <= float(depth_age) <= 5.0
            and isinstance(depth.get("bids"), list) and depth["bids"]
            and isinstance(depth.get("asks"), list) and depth["asks"]
        )
        liquidity = None
        if depth_ready:
            try:
                metrics = calculate_order_book_metrics(depth["bids"], depth["asks"], depth_levels=10)
            except OrderFlowDataError:
                depth_ready = False
            else:
                liquidity = {
                    **metrics, "bids": depth["bids"][:100], "asks": depth["asks"][:100],
                    "depth_update_id": depth.get("last_update_id"),
                    "depth_age_seconds": round(float(depth_age), 3),
                    "observed_at": snapshot.get("last_message_at"), "sequence_validated": True,
                }
        raw_flow = snapshot.get("order_flow") if isinstance(snapshot, dict) else None
        trade_ready = bool(
            isinstance(raw_flow, dict)
            and isinstance(raw_flow.get("trade_data_age_seconds"), (int, float))
            and not isinstance(raw_flow.get("trade_data_age_seconds"), bool)
            and math.isfinite(float(raw_flow["trade_data_age_seconds"]))
            and 0.0 <= float(raw_flow["trade_data_age_seconds"]) <= 15.0
        )
        trade_flow = None
        if trade_ready:
            trade_flow = {
                key: raw_flow.get(key) for key in (
                    "trade_count", "buy_volume", "sell_volume", "delta", "delta_ratio",
                    "window_cumulative_delta", "window_delta_scope", "cvd_value",
                    "cvd_status", "cvd_scope", "quote_delta", "session_timezone",
                    "session_date_utc", "session_delta", "session_delta_sample",
                    "session_delta_coverage_complete", "session_delta_scope",
                    "session_start_trade_id", "trade_data_age_seconds", "last_trade_at",
                    "footprint", "volume_profile", "data_provenance", "quality",
                ) if key in raw_flow
            }
            trade_flow["footprint"] = trade_flow.get("footprint", [])[:40] if isinstance(trade_flow.get("footprint"), list) else []
        trade_state = snapshot.get("trade_state") if isinstance(snapshot, dict) else {}
        manager = snapshot.get("manager") if isinstance(snapshot, dict) else {}
        reason = None
        if not depth_ready:
            reason = "DEPTH_NOT_SEQUENCE_VALIDATED_OR_STALE"
        elif not trade_ready:
            reason = str((trade_state or {}).get("cvd_status") or snapshot.get("status") or "TRADE_FLOW_WARMING_UP")
        return {
            "symbol": normalized, "market_type": "BINANCE_SPOT", "quote_asset": info.get("quote_asset"),
            "status": snapshot.get("status", "NOT_READY"),
            "signal_ready": depth_ready and trade_ready, "depth_ready": depth_ready,
            "trade_flow_ready": trade_ready, "reason": reason, "liquidity": liquidity,
            "trade_flow": trade_flow,
            "freshness": {
                "trade_age_seconds": raw_flow.get("trade_data_age_seconds") if isinstance(raw_flow, dict) else None,
                "depth_age_seconds": depth_age, "max_trade_age_seconds": 15.0,
                "max_depth_age_seconds": 5.0, "last_message_at": snapshot.get("last_message_at"),
            },
            "data_provenance": snapshot.get("data_provenance") or {},
            "stream": {
                "feed_mode": "PUBLIC_WEBSOCKET_STREAM", "depth_sequence_validated": depth_ready,
                "active_streams": manager.get("active_streams") if isinstance(manager, dict) else None,
                "max_streams": manager.get("max_streams") if isinstance(manager, dict) else None,
            },
        }
    except HTTPException:
        raise
    except MarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (BinanceSpotOrderFlowManagerError, OrderFlowDataError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(status_code=503, detail="Validated Binance Spot order-flow snapshot is temporarily unavailable.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Binance public order-flow feed is temporarily unavailable.") from exc


@app.post("/api/v1/intelligence/signals/scan")
async def intelligence_signal_scan(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import scan_market_signal, market_info, IntelligenceDataError
    symbol=payload.get("symbol","XAUUSD")
    threshold=payload.get("min_score",6)
    if not isinstance(threshold,int) or not 4<=threshold<=10:
        raise HTTPException(status_code=422,detail="min_score must be an integer between 4 and 10.")
    try:
        info=market_info(symbol)
        result=await scan_market_signal(info["symbol"],threshold)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")
    if result.get("signal"):
        from .signal_lifecycle import record_signal
        tracked, created = record_signal(db, user.id, result["signal"], "CROSS_MARKET_SCAN")
        record_audit_event(db,"phase07.signal_generated",{"symbol":result["symbol"],"side":result["signal"]["side"],
            "score":result["signal"]["score"],"mode":"paper_only","tracked_trade_id":tracked.id})
        db.commit()
        if created:
            event_hub.publish("signals.lifecycle.changed", "signal_trade", "created", {"trade_id": tracked.id, "symbol": tracked.symbol})
    return result

@app.get("/api/v1/intelligence/news")
async def intelligence_news(days: int = 7, user: User = Depends(local_workspace)):
    from .phase07_engine import get_economic_calendar, IntelligenceDataError
    try:
        return await get_economic_calendar(days)
    except (httpx.HTTPError, IntelligenceDataError):
        raise HTTPException(
            status_code=502,
            detail="Finnhub economic calendar is unavailable. Check FINNHUB_API_KEY, provider quota and network connection.",
        )

@app.post("/api/v1/intelligence/risk/calculate")
def intelligence_risk_calculate(payload: dict, user: User = Depends(local_workspace)):
    from .phase07_engine import calculate_risk
    try:
        return calculate_risk(float(payload.get("equity",0)),float(payload.get("risk_percent",0)),
                              float(payload.get("entry",0)),float(payload.get("stop_loss",0)))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.get("/api/v1/paper-trading/trades")
def list_paper_trades(limit: int = 100, status: str = "ALL",
                      user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1<=limit<=500: raise HTTPException(status_code=422,detail="Limit must be between 1 and 500.")
    query=select(PaperTrade).where(PaperTrade.user_id==user.id)
    if status.upper() in {"OPEN","CLOSED"}: query=query.where(PaperTrade.status==status.upper())
    elif status.upper()!="ALL": raise HTTPException(status_code=422,detail="Status must be OPEN, CLOSED or ALL.")
    rows=list(db.scalars(query.order_by(PaperTrade.id.desc()).limit(limit)))
    return [{"id":x.id,"symbol":x.symbol,"side":x.side,"quantity":x.quantity,"entry_price":x.entry_price,
             "stop_loss":x.stop_loss,"take_profit":x.take_profit,"status":x.status,"exit_price":x.exit_price,
             "realized_pnl":x.realized_pnl,"created_at":x.created_at.isoformat(),
             "closed_at":x.closed_at.isoformat() if x.closed_at else None} for x in rows]

@app.post("/api/v1/paper-trading/trades",status_code=201)
async def open_paper_trade(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import get_quote, market_info, IntelligenceDataError
    try:
        info=market_info(str(payload.get("symbol","")))
        side=str(payload.get("side","")).upper()
        quantity=float(payload.get("quantity",0))
        stop=float(payload.get("stop_loss",0))
        target=float(payload.get("take_profit",0))
        if side not in {"BUY","SELL"} or not all(math.isfinite(x) for x in (quantity,stop,target)) or not 0<quantity<=1000000 or stop<=0 or target<=0:
            raise ValueError("Side, quantity, stop loss and take profit are invalid.")
        quote=await get_quote(info["symbol"])
        from .phase10_engine import execution_gate
        data_gate=execution_gate(quote)
        if not data_gate["allowed"]:
            raise HTTPException(status_code=503,detail={"message":data_gate["reason"],"data_health":data_gate["health"]})
        entry=float(quote["price"])
        if (side=="BUY" and not stop<entry<target) or (side=="SELL" and not target<entry<stop):
            raise ValueError("For BUY, Stop Loss < live entry < Take Profit. For SELL, Take Profit < live entry < Stop Loss.")
        item=PaperTrade(user_id=user.id,symbol=info["symbol"],side=side,quantity=quantity,
                        entry_price=entry,stop_loss=stop,take_profit=target,status="OPEN")
        db.add(item)
        db.flush()
        db.add(PaperTradeEvent(user_id=user.id, trade_id=item.id, event_type="MANUAL_OPENED",
            price=entry, quantity=quantity, pnl=0.0, details_json=json.dumps({"source":"manual_ui","mode":"PAPER"})))
        record_audit_event(db,"paper_trade.opened",{"trade_id":item.id,"symbol":item.symbol,"side":side,
            "quantity":quantity,"entry":entry,"mode":"paper"})
        db.commit()
        db.refresh(item)
        event_hub.publish("paper_trade.changed", "paper_trade", "opened", {"trade_id": item.id, "symbol": item.symbol, "side": item.side, "status": item.status})
        return {"id":item.id,"symbol":item.symbol,"side":item.side,"quantity":item.quantity,
                "entry_price":item.entry_price,"stop_loss":item.stop_loss,"take_profit":item.take_profit,
                "status":item.status,"mode":"PAPER"}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check API key, quota or network connection.")

@app.post("/api/v1/paper-trading/trades/{trade_id}/close")
async def close_paper_trade(trade_id: int, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import get_quote, IntelligenceDataError
    from .phase10_engine import execution_gate

    user_id = user.id
    item = db.scalar(select(PaperTrade).where(
        PaperTrade.id == trade_id, PaperTrade.user_id == user_id
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Paper trade not found.")
    if item.status != "OPEN":
        raise HTTPException(status_code=409, detail="Paper trade is already closed.")

    try:
        quote = await get_quote(item.symbol)
        data_gate = execution_gate(quote)
        if not data_gate["allowed"]:
            raise HTTPException(
                status_code=503,
                detail={"message": "Paper close blocked by Market Data Guardian.", "data_health": data_gate["health"]},
            )
        exit_price = float(quote["price"])
        if not math.isfinite(exit_price) or exit_price <= 0:
            raise HTTPException(status_code=503, detail="Provider returned an invalid paper exit price.")
        pnl = (exit_price - item.entry_price) * item.quantity * (1 if item.side == "BUY" else -1)
        if not math.isfinite(pnl):
            raise HTTPException(status_code=503, detail="Paper close P&L is not finite; position remains open.")
    except HTTPException:
        raise
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=502,
            detail="Market provider returned an invalid close quote. Check provider data, API key, quota or network.",
        )

    realized_pnl = round(pnl, 8)
    closed_at = datetime.now(timezone.utc)
    try:
        updated_id = db.execute(
            update(PaperTrade)
            .where(
                PaperTrade.id == trade_id,
                PaperTrade.user_id == user_id,
                PaperTrade.status == "OPEN",
            )
            .values(
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                status="CLOSED",
                closed_at=closed_at,
            )
            .returning(PaperTrade.id)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
    except OperationalError as exc:
        db.rollback()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            current = db.scalar(select(PaperTrade).where(
                PaperTrade.id == trade_id, PaperTrade.user_id == user_id
            ))
            if current is None:
                raise HTTPException(status_code=404, detail="Paper trade not found.") from None
            if current.status != "OPEN":
                raise HTTPException(status_code=409, detail="Paper trade was closed by another request.") from None
            raise HTTPException(status_code=503, detail="Paper close is busy. Refresh the ledger and try again.") from None
        raise
    if updated_id is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Paper trade was closed by another request.")

    db.add(PaperTradeEvent(user_id=user_id, trade_id=trade_id, event_type="MANUAL_CLOSED",
        price=exit_price, quantity=item.quantity, pnl=realized_pnl,
        details_json=json.dumps({"provider": quote.get("provider", "market_quote"), "mode": "PAPER",
                                 "data_health": data_gate["health"]})))
    record_audit_event(db, "paper_trade.closed", {
        "trade_id": trade_id, "symbol": item.symbol,
        "exit": exit_price, "realized_pnl": realized_pnl, "mode": "paper",
    })
    db.commit()
    db.refresh(item)
    event_hub.publish("paper_trade.changed", "paper_trade", "closed", {
        "trade_id": item.id, "symbol": item.symbol, "status": item.status,
        "realized_pnl": item.realized_pnl,
    })
    return {"id": item.id, "status": item.status, "exit_price": item.exit_price,
            "realized_pnl": item.realized_pnl, "mode": "PAPER"}

@app.get("/api/v1/paper-trading/summary")
def paper_trading_summary(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
    closed=[x for x in rows if x.status=="CLOSED"]
    wins=[x for x in closed if (x.realized_pnl or 0)>0]
    losses=[x for x in closed if (x.realized_pnl or 0)<0]
    gross_profit=sum(x.realized_pnl or 0 for x in wins)
    gross_loss=abs(sum(x.realized_pnl or 0 for x in losses))
    return {"mode":"PAPER ONLY","open_trades":sum(x.status=="OPEN" for x in rows),
            "closed_trades":len(closed),"wins":len(wins),"losses":len(losses),
            "win_rate":round(len(wins)/len(closed)*100,2) if closed else None,
            "realized_pnl":round(sum(x.realized_pnl or 0 for x in closed),2),
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else (None if not gross_profit else "infinite"),
            "note":"Separate virtual ledger. Existing wallet and journal balances are not changed."}

@app.get("/api/v1/intelligence/performance")
def intelligence_performance(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id,PaperTrade.status=="CLOSED")))
    wins=[x for x in rows if (x.realized_pnl or 0)>0]
    losses=[x for x in rows if (x.realized_pnl or 0)<0]
    gross_profit=sum(x.realized_pnl or 0 for x in wins)
    gross_loss=abs(sum(x.realized_pnl or 0 for x in losses))
    return {"mode":"PAPER ONLY","total_trades":len(rows),"wins":len(wins),"losses":len(losses),
            "breakeven":len(rows)-len(wins)-len(losses),
            "win_rate":round(len(wins)/len(rows)*100,2) if rows else None,
            "gross_profit":round(gross_profit,2),"gross_loss":round(gross_loss,2),
            "net_pnl":round(gross_profit-gross_loss,2),
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else None,
            "average_win":round(gross_profit/len(wins),2) if wins else None,
            "average_loss":round(gross_loss/len(losses),2) if losses else None,
            "note":"Statistics use closed QUANTNEX paper trades only; no performance or win-rate guarantee."}


@app.get("/api/v1/performance/advanced")
def advanced_paper_performance(period_days: int = 0,
                               user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase11_engine import advanced_performance
    if period_days not in {0,7,30,90,365}:
        raise HTTPException(status_code=422,detail="period_days must be one of 0, 7, 30, 90 or 365.")
    rows=list(db.scalars(select(PaperTrade).where(
        PaperTrade.user_id==user.id,PaperTrade.status=="CLOSED"
    ).order_by(PaperTrade.closed_at,PaperTrade.id)))
    return advanced_performance(rows,period_days)


# Manual paper positions are deliberately user-controlled. The legacy
# paper_trade_monitor auto-closed every open position, including manual ones,
# and raced the opt-in autopilot worker. Automatic positions are managed only
# by paper_autopilot_worker, which checks AUTO_OPENED ledger events.


def _closed_strategy_candles(candles: list[dict], timeframe: str) -> list[dict]:
    """Keep strategy research and forward observations on fully closed market bars."""
    from .signal_engine import closed_candles
    interval = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}.get(timeframe)
    if interval is None:
        raise ValueError("Unsupported strategy timeframe.")
    result = closed_candles(candles, interval)
    if len(result) < 210:
        raise ValueError(f"Not enough fully closed {timeframe} candles for strategy research ({len(result)} received).")
    return result


# ---------------------------------------------------------------------------
# Phase 08 — Strategy Laboratory (historical research + forward observation)
# ---------------------------------------------------------------------------
@app.get("/api/v1/strategy-lab/replay")
async def strategy_lab_replay(symbol: str = "BTCUSDT", timeframe: str = "15m",
                              user: User = Depends(local_workspace)):
    from .phase07_engine import market_info, get_candles
    try:
        info=market_info(symbol)
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        candles=_closed_strategy_candles(await get_candles(info["symbol"],timeframe,250),timeframe)
        return {"symbol":info["symbol"],"timeframe":timeframe,"candles":candles,
                "count":len(candles),"mode":"HISTORICAL_REPLAY"}
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Historical market data unavailable. Check provider configuration and quota.") from exc

@app.post("/api/v1/strategy-lab/backtest")
async def strategy_lab_backtest(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import run_backtest, validate_strategy
    try:
        info=market_info(payload.get("symbol","BTCUSDT"))
        timeframe=payload.get("timeframe","15m")
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        strategy=validate_strategy(payload.get("strategy") or {})
        candles=_closed_strategy_candles(await get_candles(info["symbol"],timeframe,500),timeframe)
        result=run_backtest(candles,strategy)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Backtest data unavailable. Check market provider configuration and quota.") from exc
    db.add(StrategyLabRun(user_id=user.id,run_type="BACKTEST",symbol=info["symbol"],timeframe=timeframe,
        strategy_json=json.dumps(strategy),result_json=json.dumps(result)))
    record_audit_event(db,"strategy_lab.backtest",{"symbol":info["symbol"],"timeframe":timeframe,
        "trades":result["trade_count"],"strategy":strategy})
    db.commit()
    event_hub.publish("strategy.research.changed", "strategy", "backtest_saved", {"symbol": info["symbol"], "timeframe": timeframe})
    return {"symbol":info["symbol"],"timeframe":timeframe,**result}

@app.post("/api/v1/strategy-lab/optimize")
async def strategy_lab_optimize(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import optimize
    try:
        info=market_info(payload.get("symbol","BTCUSDT"))
        timeframe=payload.get("timeframe","15m")
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        candles=_closed_strategy_candles(await get_candles(info["symbol"],timeframe,500),timeframe)
        result=optimize(candles)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Optimizer data unavailable. Check provider configuration and quota.") from exc
    db.add(StrategyLabRun(user_id=user.id,run_type="OPTIMIZER",symbol=info["symbol"],timeframe=timeframe,
        strategy_json="{}",result_json=json.dumps(result)))
    record_audit_event(db,"strategy_lab.optimizer",{"symbol":info["symbol"],"timeframe":timeframe,"tested":result["tested"]})
    db.commit()
    event_hub.publish("strategy.research.changed", "strategy", "optimizer_saved", {"symbol": info["symbol"], "timeframe": timeframe})
    return {"symbol":info["symbol"],"timeframe":timeframe,**result}

@app.post("/api/v1/strategy-lab/forward/evaluate")
async def strategy_lab_forward_evaluate(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import ema, validate_strategy
    try:
        info=market_info(payload.get("symbol","BTCUSDT"))
        timeframe=payload.get("timeframe","15m")
        if timeframe not in {"5m","15m","1h","4h"}: raise ValueError("Unsupported timeframe. Choose 5m, 15m, 1h or 4h.")
        strategy=validate_strategy(payload.get("strategy") or {})
        candles=_closed_strategy_candles(await get_candles(info["symbol"],timeframe,250),timeframe)
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502,detail="Forward observation data unavailable. Check provider configuration and quota.") from exc
    closes=[float(x["close"]) for x in candles]
    fast=ema(closes,strategy["fast_ema"]); slow=ema(closes,strategy["slow_ema"])
    side="BUY" if fast[-1]>slow[-1] else "SELL" if fast[-1]<slow[-1] else "WAIT"
    observation={"side":side,"price":closes[-1],"candle_time":candles[-1].get("time"),
                 "fast_ema":round(fast[-1],8),"slow_ema":round(slow[-1],8),
                 "note":"Observation only. This endpoint does not open paper or broker positions."}
    db.add(StrategyLabRun(user_id=user.id,run_type="FORWARD_OBSERVATION",symbol=info["symbol"],timeframe=timeframe,
        strategy_json=json.dumps(strategy),result_json=json.dumps(observation)))
    record_audit_event(db,"strategy_lab.forward_observation",{"symbol":info["symbol"],"side":side,"timeframe":timeframe})
    db.commit()
    event_hub.publish("strategy.research.changed", "strategy", "forward_observation_saved", {"symbol": info["symbol"], "timeframe": timeframe})
    return {"symbol":info["symbol"],"timeframe":timeframe,"strategy":strategy,**observation}

@app.get("/api/v1/strategy-lab/research")
def strategy_lab_research(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    runs=list(db.scalars(select(StrategyLabRun).where(StrategyLabRun.user_id==user.id)
                         .order_by(StrategyLabRun.created_at.desc()).limit(50)))
    closed=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id,PaperTrade.status=="CLOSED")))
    wins=[x for x in closed if (x.realized_pnl or 0)>0]
    losses=[x for x in closed if (x.realized_pnl or 0)<0]
    return {"runs":[{"id":x.id,"type":x.run_type,"symbol":x.symbol,"timeframe":x.timeframe,
                     "created_at":x.created_at.isoformat(),"strategy":json.loads(x.strategy_json),
                     "result":json.loads(x.result_json)} for x in runs],
            "paper_trades":{"closed":len(closed),"wins":len(wins),"losses":len(losses),
                "win_rate":round(len(wins)/len(closed)*100,2) if closed else None,
                "net_pnl":round(sum(x.realized_pnl or 0 for x in closed),2)},
            "guidance":"Research summaries describe historical and paper observations only; they are not a prediction or guarantee."}


# ---------------------------------------------------------------------------
# Phase 09 — advanced risk and portfolio intelligence (paper-only).
# ---------------------------------------------------------------------------
@app.get("/api/v1/risk/portfolio")
def risk_portfolio(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase09_engine import portfolio_snapshot
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
    return portfolio_snapshot(rows)

@app.post("/api/v1/risk/position-size")
def risk_position_size(payload: dict, user: User = Depends(local_workspace)):
    from .phase09_engine import calculate_position_size
    try:
        return calculate_position_size(payload.get("equity"),payload.get("risk_percent"),
            payload.get("entry"),payload.get("stop_loss"),payload.get("contract_multiplier"))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.post("/api/v1/risk/guardian")
def risk_guardian(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase09_engine import drawdown_guard
    try:
        rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
        return drawdown_guard(rows,payload.get("equity"),payload.get("daily_loss_limit_percent",3),
            payload.get("max_drawdown_percent",8),payload.get("max_consecutive_losses",4))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

@app.post("/api/v1/risk/stress")
def risk_stress(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase09_engine import stress_test
    rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
    try:
        return stress_test(rows,payload.get("shocks"))
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))

async def _smart_open_quote(info: dict) -> dict:
    """Use the same configured XAUUSD provider as chart history for paper entries."""
    from .phase07_engine import get_quote
    if info["symbol"] == "XAUUSD":
        quote = await chart_quote("XAUUSD", "15m")
        if quote.get("stale"):
            raise HTTPException(status_code=503, detail="The configured Gold quote is stale; paper entry is blocked.")
        return {**quote, "kind": info["kind"]}
    return await get_quote(info["symbol"])


@app.post("/api/v1/paper-trading/smart-open",status_code=201)
async def smart_open_paper_trade(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    """Risk-checked paper entry; explicit multiplier required; never sends broker orders."""
    from .phase07_engine import market_info, IntelligenceDataError
    from .phase09_engine import calculate_position_size, drawdown_guard
    try:
        info=market_info(str(payload.get("symbol","")))
        side=str(payload.get("side","")).upper()
        if side not in {"BUY","SELL"}: raise ValueError("Side must be BUY or SELL.")
        equity=float(payload.get("equity",0))
        risk_percent=float(payload.get("risk_percent",0.5))
        rows=list(db.scalars(select(PaperTrade).where(PaperTrade.user_id==user.id)))
        guard=drawdown_guard(rows,equity,payload.get("daily_loss_limit_percent",3),
            payload.get("max_drawdown_percent",8),payload.get("max_consecutive_losses",4))
        if not guard["trading_allowed"]:
            raise HTTPException(status_code=409,detail={"message":"Risk Guardian blocked this paper entry.","guardian":guard})
        quote=await _smart_open_quote(info)
        from .phase10_engine import execution_gate
        data_gate=execution_gate(quote)
        if not data_gate["allowed"]:
            raise HTTPException(status_code=503,detail={"message":data_gate["reason"],"data_health":data_gate["health"]})
        entry=float(quote["price"])
        stop=float(payload.get("stop_loss",0)); target=float(payload.get("take_profit",0))
        if (side=="BUY" and not stop<entry<target) or (side=="SELL" and not target<entry<stop):
            raise ValueError("For BUY, Stop Loss < live entry < Take Profit. For SELL, Take Profit < live entry < Stop Loss.")
        sizing=calculate_position_size(equity,risk_percent,entry,stop,payload.get("contract_multiplier"))
        quantity=sizing["estimated_units"]
        if not math.isfinite(quantity) or quantity<=0 or quantity>1000000:
            raise ValueError("Calculated quantity is outside the safe supported range.")
        item=PaperTrade(user_id=user.id,symbol=info["symbol"],side=side,quantity=quantity,
            entry_price=entry,stop_loss=stop,take_profit=target,status="OPEN")
        db.add(item); db.flush()
        record_audit_event(db,"phase09.smart_paper_trade.opened",{"trade_id":item.id,"symbol":item.symbol,
            "side":side,"quantity":quantity,"risk_amount":sizing["risk_amount"],"provider":quote.get("provider"),"mode":"paper"})
        db.commit(); db.refresh(item)
        event_hub.publish("paper_trade.changed", "paper_trade", "opened", {"trade_id": item.id, "symbol": item.symbol, "side": item.side, "status": item.status, "source": "risk_guardian"})
        return {"id":item.id,"symbol":item.symbol,"side":side,"quantity":quantity,"entry_price":entry,
            "stop_loss":stop,"take_profit":target,"risk":sizing,"guardian":guard,"status":"OPEN","mode":"PAPER"}
    except HTTPException:
        raise
    except (ValueError,TypeError) as exc:
        raise HTTPException(status_code=422,detail=str(exc))
    except IntelligenceDataError as exc:
        raise HTTPException(status_code=502,detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502,detail="Market provider request failed. Check provider configuration and quota.")


@app.get("/api/v1/goals/certificate-designs")
def list_goal_certificate_designs(user: User = Depends(local_workspace)):
    """Return the curated 50 portrait + 50 landscape certificate design catalog."""
    from .certificate_designs import certificate_design_catalog
    return {"designs": certificate_design_catalog(), "count": 100,
            "portrait_count": 50, "landscape_count": 50}


@app.get("/api/v1/goals/demo-certificate")
@app.post("/api/v1/goals/demo-certificate")
def download_demo_goal_certificate(payload: dict | None = None, user: User = Depends(local_workspace)):
    """Render a personalized sample only; it never creates or unlocks a real certificate."""
    from .goal_certificates import build_goal_certificate_pdf
    payload = payload or {}
    # Defaults apply only when a field is omitted. Explicitly supplied empty or
    # zero values must reach validation rather than silently becoming demo data.
    display_name = str(payload.get("display_name", "QUANTNEX Demo User")).strip()
    goal_title = str(payload.get("goal_title", "Sample Personal Goal")).strip()
    achievement_text = str(payload.get("achievement_text", "I just achieved gold")).strip()
    currency = str(payload.get("currency", "USD")).strip().upper()
    try:
        target_amount = float(payload.get("target_amount", 1000))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Demo goal amount must be numeric.")
    if not display_name or len(display_name) > 80:
        raise HTTPException(status_code=422, detail="Enter a display name between 1 and 80 characters.")
    if not goal_title or len(goal_title) > 120 or not achievement_text or len(achievement_text) > 240:
        raise HTTPException(status_code=422, detail="Enter a goal name and achievement message within the allowed length.")
    if currency not in {"USD","LKR","EUR","GBP","AUD","CAD"} or not (0 < target_amount <= 1000000000000):
        raise HTTPException(status_code=422, detail="Enter a valid demo goal amount and currency.")
    from .certificate_designs import get_certificate_design
    design_id = str(payload.get("design_id") or "P-01")
    orientation = str(payload.get("orientation") or "").lower() or None
    try:
        get_certificate_design(design_id, orientation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    achieved = datetime.now(timezone.utc)
    created = datetime.fromtimestamp(achieved.timestamp() - 21 * 86400 - 5 * 3600, tz=timezone.utc)
    pdf = build_goal_certificate_pdf(
        display_name=display_name, goal_title=goal_title, achievement_text=achievement_text,
        created_at=created, achieved_at=achieved, elapsed_days=21, elapsed_hours=509,
        certificate_id="DEMO-NOT-VALID", integrity_fingerprint="0" * 64,
        target_amount=target_amount, saved_amount=target_amount, currency=currency,
        goal_image_url=str(payload.get("image_url") or ""), demo_only=True,
        design_id=design_id, orientation=orientation,
    )
    return Response(content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="QUANTNEX-DEMO-CERTIFICATE-NOT-VALID.pdf"',
                 "Cache-Control": "no-store"})

@app.get("/api/v1/goals")
def list_personal_goals(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goals=list(db.scalars(select(PersonalGoal).where(PersonalGoal.user_id==user.id).order_by(PersonalGoal.created_at.desc())))
    output=[]
    for goal in goals:
        contributions=float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(
            GoalContribution.goal_id==goal.id,GoalContribution.user_id==user.id)) or 0)
        saved=float(goal.initial_amount or 0)+contributions
        output.append({"id":goal.id,"title":goal.title,"description":goal.description,
            "target_amount":goal.target_amount,"currency":goal.currency,"initial_amount":goal.initial_amount,
            "saved_amount":round(saved,2),"remaining_amount":round(max(0,goal.target_amount-saved),2),
            "progress_percent":round(min(100,saved/goal.target_amount*100),2) if goal.target_amount>0 else 0,
            "image_url":goal.image_url,"target_date":goal.target_date.isoformat() if goal.target_date else None,
            "created_at":goal.created_at.isoformat(),"achieved_at":goal.achieved_at.isoformat() if goal.achieved_at else None,
            "achieved":bool(goal.achieved_at and saved>=goal.target_amount),
            "certificate_available":bool(goal.certificate_id and goal.certificate_hash)})
    return {"goals":output,"accounting_note":"Only user-confirmed manual real-account profit/savings contributions count. Bot paper trades, backtests and wallet estimates are excluded."}


@app.post("/api/v1/goals")
def create_personal_goal(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    title=str(payload.get("title","")).strip()
    description=str(payload.get("description","")).strip()
    currency=str(payload.get("currency","USD")).strip().upper()
    try:
        target=float(payload.get("target_amount"))
        initial=float(payload.get("initial_amount",0) or 0)
    except (TypeError,ValueError):
        raise HTTPException(status_code=422,detail="Target and starting amount must be valid numbers.")
    import math
    if not math.isfinite(target) or not math.isfinite(initial):
        raise HTTPException(status_code=422,detail="Target and starting amount must be finite numbers.")
    if not title or len(title)>120 or len(description)>2000:
        raise HTTPException(status_code=422,detail="Enter a goal title (1–120 characters) and a description up to 2,000 characters.")
    if currency not in {"USD","LKR","EUR","GBP","AUD","CAD"}:
        raise HTTPException(status_code=422,detail="Unsupported goal currency.")
    if not (0 < target <= 1000000000000) or not (0 <= initial <= target):
        raise HTTPException(status_code=422,detail="Target must be positive and starting savings must be between zero and target.")
    if initial>0 and payload.get("confirmed_available_real_funds") is not True:
        raise HTTPException(status_code=422,detail="Confirm that the starting amount is genuinely available real money.")
    image_url=str(payload.get("image_url","")).strip()
    if image_url and (len(image_url)>2048 or not image_url.startswith("https://")):
        raise HTTPException(status_code=422,detail="Goal image must be an HTTPS image URL.")
    target_date=None
    if payload.get("target_date"):
        try: target_date=datetime.fromisoformat(str(payload["target_date"]).replace("Z","+00:00"))
        except ValueError: raise HTTPException(status_code=422,detail="Target date must be a valid ISO date.")
    goal=PersonalGoal(user_id=user.id,title=title,description=description,target_amount=target,
        currency=currency,initial_amount=initial,image_url=image_url,target_date=target_date)
    if initial>=target: goal.achieved_at=datetime.now(timezone.utc)
    db.add(goal);db.commit();db.refresh(goal)
    return {"id":goal.id,"title":goal.title,"target_amount":goal.target_amount,"currency":goal.currency,
        "saved_amount":goal.initial_amount,"remaining_amount":max(0,target-initial),
        "progress_percent":round(initial/target*100,2),"achieved":bool(goal.achieved_at)}


@app.put("/api/v1/goals/{goal_id}")
def update_personal_goal(goal_id: int, payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goal=db.scalar(select(PersonalGoal).where(PersonalGoal.id==goal_id,PersonalGoal.user_id==user.id))
    if goal is None: raise HTTPException(status_code=404,detail="Goal not found.")
    if goal.achieved_at: raise HTTPException(status_code=409,detail="An achieved goal is locked to preserve its certificate record.")
    if "title" in payload:
        title=str(payload["title"]).strip()
        if not title or len(title)>120: raise HTTPException(status_code=422,detail="Goal title must be 1–120 characters.")
        goal.title=title
    if "description" in payload:
        description=str(payload["description"]).strip()
        if len(description)>2000: raise HTTPException(status_code=422,detail="Description is too long.")
        goal.description=description
    if "target_amount" in payload:
        try: target=float(payload["target_amount"])
        except (TypeError,ValueError): raise HTTPException(status_code=422,detail="Target amount must be numeric.")
        if not math.isfinite(target) or target<=0 or target>1000000000000:
            raise HTTPException(status_code=422,detail="Target amount must be finite, positive and within the supported limit.")
        goal.target_amount=target
    if "target_date" in payload:
        try: goal.target_date=datetime.fromisoformat(str(payload["target_date"]).replace("Z","+00:00")) if payload["target_date"] else None
        except ValueError: raise HTTPException(status_code=422,detail="Target date must be a valid ISO date.")
    if "image_url" in payload:
        image_url=str(payload["image_url"] or "").strip()
        if image_url and (len(image_url)>2048 or not image_url.startswith("https://")):
            raise HTTPException(status_code=422,detail="Goal image must be an HTTPS image URL.")
        goal.image_url=image_url
    current_contributions=float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(
        GoalContribution.goal_id==goal.id,GoalContribution.user_id==user.id)) or 0)
    current_saved=float(goal.initial_amount or 0)+current_contributions
    if current_saved>=goal.target_amount and goal.achieved_at is None:
        goal.achieved_at=datetime.now(timezone.utc)
    db.commit()
    return {"updated":True,"id":goal.id,"achieved":bool(goal.achieved_at)}


@app.post("/api/v1/goals/{goal_id}/contributions")
def add_goal_contribution(goal_id: int, payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goal=db.scalar(select(PersonalGoal).where(PersonalGoal.id==goal_id,PersonalGoal.user_id==user.id))
    if goal is None: raise HTTPException(status_code=404,detail="Goal not found.")
    if goal.achieved_at is not None:
        raise HTTPException(status_code=409,detail="This goal is already achieved and its certificate record is locked.")
    if payload.get("confirmed_available_real_funds") is not True:
        raise HTTPException(status_code=422,detail="Confirm this is genuinely available real-account profit or savings, not simulated P&L.")
    try: amount=float(payload.get("amount"))
    except (TypeError,ValueError): raise HTTPException(status_code=422,detail="Contribution amount must be numeric.")
    currency=str(payload.get("currency",goal.currency)).upper()
    if not math.isfinite(amount) or not (0<amount<=1000000000) or currency!=goal.currency:
        raise HTTPException(status_code=422,detail="Contribution must be finite, positive and use the goal currency.")
    note=str(payload.get("note","")).strip()
    if len(note)>240: raise HTTPException(status_code=422,detail="Contribution note is too long.")
    row=GoalContribution(goal_id=goal.id,user_id=user.id,amount=amount,currency=currency,
        source="manual_real_account",note=note)
    db.add(row);db.flush()
    total_contributions=float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(
        GoalContribution.goal_id==goal.id,GoalContribution.user_id==user.id)) or 0)
    saved=float(goal.initial_amount or 0)+total_contributions
    if saved>=goal.target_amount and goal.achieved_at is None:
        goal.achieved_at=datetime.now(timezone.utc)
    db.commit()
    return {"contribution_id":row.id,"saved_amount":round(saved,2),
        "remaining_amount":round(max(0,goal.target_amount-saved),2),
        "progress_percent":round(min(100,saved/goal.target_amount*100),2),
        "achieved":bool(goal.achieved_at),"source":"manual_real_account"}


def _goal_certificate_signature(db: Session, user_id: int, goal: PersonalGoal, saved_amount: float) -> tuple[str,str]:
    import hashlib, hmac, secrets
    secret_enc=_preference(db,user_id,"goal_certificate_secret")
    if not secret_enc:
        secret=secrets.token_hex(32)
        _save_preference(db,user_id,"goal_certificate_secret",encrypt_secret(secret))
    else:
        secret=decrypt_secret(secret_enc)
    if not goal.certificate_id:
        import uuid
        goal.certificate_id="QX-"+uuid.uuid4().hex[:20].upper()
    payload="|".join([str(goal.id),goal.title,str(goal.target_amount),str(round(saved_amount,2)),goal.currency,
        goal.created_at.isoformat(),goal.achieved_at.isoformat(),goal.certificate_id])
    digest=hmac.new(secret.encode("utf-8"),payload.encode("utf-8"),hashlib.sha256).hexdigest()
    return goal.certificate_id,digest


@app.post("/api/v1/goals/{goal_id}/certificate")
def generate_goal_certificate(goal_id: int, payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goal=db.scalar(select(PersonalGoal).where(PersonalGoal.id==goal_id,PersonalGoal.user_id==user.id))
    if goal is None: raise HTTPException(status_code=404,detail="Goal not found.")
    saved=float(goal.initial_amount or 0)+float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(
        GoalContribution.goal_id==goal.id,GoalContribution.user_id==user.id)) or 0)
    if saved<goal.target_amount or goal.achieved_at is None:
        raise HTTPException(status_code=409,detail="This goal is not achieved yet. Certificate generation is locked.")
    display_name=str(payload.get("display_name","")).strip()
    if not display_name or len(display_name)>80:
        raise HTTPException(status_code=422,detail="Enter the display name to print on the certificate (max 80 characters).")
    from .certificate_designs import get_certificate_design
    design_id = str(payload.get("design_id") or "P-01")
    orientation = str(payload.get("orientation") or "").lower() or None
    try:
        get_certificate_design(design_id, orientation)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    certificate_id,digest=_goal_certificate_signature(db,user.id,goal,saved)
    if goal.certificate_hash and not __import__("hmac").compare_digest(goal.certificate_hash,digest):
        raise HTTPException(status_code=409,detail="Certificate integrity check failed. The stored goal record has changed.")
    goal.certificate_hash=digest;db.commit()
    from .goal_certificates import build_goal_certificate_pdf
    achieved=goal.achieved_at
    if achieved.tzinfo is None: achieved=achieved.replace(tzinfo=timezone.utc)
    created=goal.created_at
    if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
    elapsed_seconds=max(0,int((achieved-created).total_seconds()))
    elapsed=elapsed_seconds//86400
    elapsed_hours=elapsed_seconds//3600
    pdf=build_goal_certificate_pdf(display_name=display_name,goal_title=goal.title,
        created_at=created,achieved_at=achieved,elapsed_days=elapsed,elapsed_hours=elapsed_hours,
        certificate_id=certificate_id,integrity_fingerprint=digest,
        target_amount=goal.target_amount,saved_amount=saved,currency=goal.currency,
        achievement_text=goal.description or "A meaningful result built through patience, consistency and self-discipline.",
        goal_image_url=goal.image_url or "",design_id=design_id,orientation=orientation)
    safe_name="".join(ch for ch in display_name if ch.isalnum() or ch in "-_")[:32] or "Trader"
    return Response(content=pdf,media_type="application/pdf",
        headers={"Content-Disposition":f'attachment; filename="QUANTNEX-Achievement-{safe_name}.pdf"'})


@app.get("/api/v1/goals/{goal_id}/certificate/verify")
def verify_goal_certificate(goal_id: int, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goal=db.scalar(select(PersonalGoal).where(PersonalGoal.id==goal_id,PersonalGoal.user_id==user.id))
    if goal is None: raise HTTPException(status_code=404,detail="Goal not found.")
    if not goal.certificate_hash or not goal.certificate_id:
        return {"verified":False,"reason":"No certificate has been issued."}
    saved=float(goal.initial_amount or 0)+float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(
        GoalContribution.goal_id==goal.id,GoalContribution.user_id==user.id)) or 0)
    certificate_id,digest=_goal_certificate_signature(db,user.id,goal,saved)
    return {"verified":__import__("hmac").compare_digest(goal.certificate_hash,digest),
        "certificate_id":certificate_id,"verification_scope":"local workspace integrity only"}


# Phases 12–20 local paper platform APIs. All automated orders remain simulated.
@app.get("/api/v1/paper-engine")
async def paper_engine_status(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase12_20_engine import DEFAULT_SETTINGS, normalize_settings, risk_snapshot, open_position_risk_snapshot
    raw = _preference(db, user.id, "paper_autopilot_settings", "")
    try:
        settings = normalize_settings(json.loads(raw)) if raw else normalize_settings(DEFAULT_SETTINGS)
    except (ValueError, TypeError, json.JSONDecodeError):
        settings = normalize_settings(DEFAULT_SETTINGS)
    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.user_id == user.id)))
    unrealized_pnl, unpriced_open_position = await open_position_risk_snapshot(trades)
    risk = risk_snapshot(
        trades, settings, unrealized_pnl=unrealized_pnl,
        unpriced_open_position=unpriced_open_position,
    )
    return {"settings": settings, "risk": risk,
            "last_error": _preference(db, user.id, "paper_autopilot_last_error"),
            "last_block": json.loads(_preference(db, user.id, "paper_autopilot_last_block", "[]") or "[]"),
            "worker": "LOCAL_BACKGROUND_WORKER", "mode": "PAPER_ONLY",
            "note": "Risk status includes current provider marks for open paper positions. Unpriced/stale positions block new automatic entries. Automatic mode is opt-in and runs only while this local QUANTNEX API is running. No broker orders."}


@app.put("/api/v1/paper-engine")
def update_paper_engine(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase12_20_engine import normalize_settings
    try:
        current_raw = _preference(db, user.id, "paper_autopilot_settings", "")
        current = json.loads(current_raw) if current_raw else {}
        settings = normalize_settings({**current, **payload})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _save_preference(db, user.id, "paper_autopilot_settings", json.dumps(settings))
    _save_preference(db, user.id, "paper_autopilot_last_error", "")
    record_audit_event(db, "paper_engine.settings_updated",
                       {"enabled": settings["enabled"], "symbols": settings["symbols"], "mode": "PAPER"})
    db.commit()
    event_hub.publish("preferences.changed", "paper_engine", "settings_updated",
                      {"enabled": settings["enabled"], "mode": "PAPER"})
    return {"settings": settings, "mode": "PAPER_ONLY", "saved": True}


@app.get("/api/v1/paper-engine/events")
def paper_engine_events(limit: int = 100, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500.")
    rows = list(db.scalars(select(PaperTradeEvent).where(PaperTradeEvent.user_id == user.id)
                           .order_by(PaperTradeEvent.id.desc()).limit(limit)))
    return [{"id": x.id, "trade_id": x.trade_id, "event_type": x.event_type,
             "price": x.price, "quantity": x.quantity, "pnl": x.pnl,
             "details": json.loads(x.details_json or "{}"), "created_at": x.created_at.isoformat()}
            for x in rows]


@app.get("/api/v1/paper-engine/performance")
def paper_engine_performance(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase12_20_engine import performance_metrics, DEFAULT_SETTINGS
    raw = _preference(db, user.id, "paper_autopilot_settings", "")
    try:
        settings = json.loads(raw) if raw else DEFAULT_SETTINGS
        starting = float(settings.get("paper_equity", 10000))
    except (ValueError, TypeError):
        starting = 10000.0
    trades = list(db.scalars(select(PaperTrade).where(PaperTrade.user_id == user.id)))
    return performance_metrics(trades, starting)


@app.get("/api/v1/market/universe")
async def market_universe(limit: int = 1000, user: User = Depends(local_workspace)):
    from .phase12_20_engine import discover_binance_spot_universe
    try:
        return await discover_binance_spot_universe(limit)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Binance exchange metadata is temporarily unavailable.") from exc


@app.post("/api/v1/strategy-lab/walk-forward")
async def strategy_lab_walk_forward(payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import market_info, get_candles
    from .phase08_engine import run_backtest, validate_strategy
    from .phase12_20_engine import walk_forward_slices
    try:
        info = market_info(payload.get("symbol", "BTCUSDT"))
        timeframe = payload.get("timeframe", "15m")
        if timeframe not in {"5m", "15m", "1h", "4h"}:
            raise ValueError("Choose 5m, 15m, 1h or 4h.")
        strategy = validate_strategy(payload.get("strategy") or {})
        candles = _closed_strategy_candles(await get_candles(info["symbol"], timeframe, 500), timeframe)
        train, holdout = walk_forward_slices(candles, float(payload.get("train_ratio", 0.7)))
        training = run_backtest(train, strategy)
        validation = run_backtest(holdout, strategy)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Walk-forward market data unavailable.") from exc
    result = {"symbol": info["symbol"], "timeframe": timeframe, "strategy": strategy,
              "training": training, "out_of_sample": validation,
              "method": "Chronological holdout; no parameter fitting on holdout data.",
              "warning": "A single historical holdout is not proof of future profitability."}
    db.add(StrategyLabRun(user_id=user.id, run_type="WALK_FORWARD", symbol=info["symbol"],
        timeframe=timeframe, strategy_json=json.dumps(strategy), result_json=json.dumps(result)))
    record_audit_event(db, "strategy_lab.walk_forward", {"symbol": info["symbol"], "timeframe": timeframe})
    db.commit()
    event_hub.publish("strategy.research.changed", "strategy", "walk_forward_saved", {"symbol": info["symbol"]})
    return result


@app.get("/api/v1/goals/{goal_id}/journal-preview")
def goal_journal_import_preview(goal_id: int, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goal = db.scalar(select(PersonalGoal).where(PersonalGoal.id == goal_id, PersonalGoal.user_id == user.id))
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found.")
    rows = list(db.scalars(select(Trade).where(Trade.user_id == user.id, Trade.pnl > 0).order_by(Trade.created_at.desc()).limit(200)))
    already = {str(c.note).removeprefix("journal_import:") for c in db.scalars(
        select(GoalContribution).where(GoalContribution.user_id == user.id,
                                       GoalContribution.source == "manual_journal_import"))}
    return {"goal_id": goal.id, "goal_currency": goal.currency,
            "candidates": [{"trade_id": t.id, "created_at": t.created_at.isoformat(),
                "symbol": t.symbol, "direction": t.direction, "recorded_pnl": t.pnl,
                "eligible": str(t.id) not in already, "note": "Manual journal P&L only; confirm it is actually available real-account savings before importing."}
                for t in rows],
            "warning": "A journal win is not automatically cash savings. Only import amounts you have actually received and can allocate to this goal."}


@app.post("/api/v1/goals/{goal_id}/journal-import")
def import_goal_journal_records(goal_id: int, payload: dict, user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    goal = db.scalar(select(PersonalGoal).where(PersonalGoal.id == goal_id, PersonalGoal.user_id == user.id))
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found.")
    if goal.achieved_at:
        raise HTTPException(status_code=409, detail="Achieved goals are locked.")
    if payload.get("confirmed_available_real_funds") is not True:
        raise HTTPException(status_code=422, detail="Confirm these selected journal profits are genuinely received and available real funds.")
    ids = payload.get("trade_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(x, int) for x in ids):
        raise HTTPException(status_code=422, detail="Select between 1 and 100 journal entries.")
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Duplicate journal IDs were supplied.")
    rows = list(db.scalars(select(Trade).where(Trade.user_id == user.id, Trade.id.in_(ids), Trade.pnl > 0)))
    if len(rows) != len(ids):
        raise HTTPException(status_code=422, detail="One or more selected journal entries are missing or have no positive recorded P&L.")
    existing = {str(c.note).removeprefix("journal_import:") for c in db.scalars(
        select(GoalContribution).where(GoalContribution.user_id == user.id,
                                       GoalContribution.source == "manual_journal_import"))}
    duplicates = [str(t.id) for t in rows if str(t.id) in existing]
    if duplicates:
        raise HTTPException(status_code=409, detail={"message": "Some journal entries were already imported.", "duplicate_trade_ids": duplicates})
    # Trade.pnl has no currency field; only allow import into USD goals and clearly
    # preserve the original amount. Never infer FX conversion.
    if goal.currency != "USD":
        raise HTTPException(status_code=409, detail="Journal entries have no stored currency. Import is limited to USD goals; no FX conversion is inferred.")
    for trade in rows:
        db.add(GoalContribution(goal_id=goal.id, user_id=user.id, amount=trade.pnl,
            currency="USD", source="manual_journal_import", note="journal_import:" + str(trade.id)))
    db.flush()
    total = sum(float(t.pnl) for t in rows)
    saved = float(goal.initial_amount or 0) + float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount), 0)).where(
        GoalContribution.goal_id == goal.id, GoalContribution.user_id == user.id)) or 0)
    if saved >= goal.target_amount and goal.achieved_at is None:
        goal.achieved_at = datetime.now(timezone.utc)
    record_audit_event(db, "goal.journal_records_imported", {"goal_id": goal.id, "trade_ids": ids, "amount": total})
    db.commit()
    event_hub.publish("goals.changed", "goals", "journal_imported", {"goal_id": goal.id, "amount": total})
    return {"imported": len(rows), "amount": round(total, 2), "saved_amount": round(saved, 2),
            "achieved": bool(goal.achieved_at), "currency": "USD"}


async def start_paper_autopilot_worker():
    from .phase12_20_engine import paper_autopilot_worker
    app.state.paper_autopilot_task = asyncio.create_task(paper_autopilot_worker())


async def stop_paper_autopilot_worker():
    task = getattr(app.state, "paper_autopilot_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.get("/api/v1/paper-engine/monitor")
async def paper_engine_monitor(user: User = Depends(local_workspace), db: Session = Depends(get_db)):
    from .phase07_engine import get_quote, IntelligenceDataError
    from .phase10_engine import assess_quote
    rows = list(db.scalars(select(PaperTrade).where(PaperTrade.user_id == user.id, PaperTrade.status == "OPEN").order_by(PaperTrade.id.desc())))
    output = []
    for item in rows[:50]:
        try:
            quote = await get_quote(item.symbol)
            health = assess_quote(quote)
            mark = float(quote["price"])
            pnl = (mark - item.entry_price) * item.quantity * (1 if item.side == "BUY" else -1)
            output.append({"trade_id": item.id, "symbol": item.symbol, "side": item.side,
                "entry_price": item.entry_price, "mark_price": mark,
                "unrealized_pnl_estimate": round(pnl, 8), "provider": quote["provider"],
                "data_health": health, "timestamp": quote["timestamp"]})
        except (IntelligenceDataError, httpx.HTTPError, ValueError, KeyError):
            output.append({"trade_id": item.id, "symbol": item.symbol, "side": item.side,
                "entry_price": item.entry_price, "mark_price": None,
                "unrealized_pnl_estimate": None, "data_health": {"status":"UNAVAILABLE","trading_safe":False},
                "timestamp": None})
    return {"positions": output, "count": len(output),
            "note": "Indicative provider marks only. Stale/unavailable quotes are not treated as current prices or broker-executable values."}


@app.get("/api/v1/market/mt5/status")
async def mt5_market_status():
    """Connection health for the local, read-only MT5 market-data bridge."""
    from .mt5_feed import get_status, MT5FeedError
    try:
        result = await get_status()
        result["configured_for_gold_candles"] = QUANTNEX_MT5_ENABLED
        return result
    except MT5FeedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/v1/market/mt5/quote")
async def mt5_market_quote(symbol: str = QUANTNEX_MT5_GOLD_SYMBOL):
    """Return a local MT5 bid/ask quote; this endpoint cannot place orders."""
    from .mt5_feed import get_quote, MT5FeedError
    try:
        return await get_quote(symbol)
    except MT5FeedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/v1/market/mt5/candles")
async def mt5_market_candles(symbol: str = QUANTNEX_MT5_GOLD_SYMBOL, interval: str = "15m", limit: int = 500):
    """Return normalized, read-only OHLC candles from the connected local MT5 terminal."""
    from .mt5_feed import get_candles, MT5FeedError
    try:
        rows = await get_candles(symbol, interval, limit)
        return {"symbol": symbol.upper(), "interval": interval, "provider": "MetaTrader 5 local terminal",
                "candles": rows, "count": len(rows), "mode": "read_only_market_data",
                "orders_enabled": False, "timestamp": datetime.now(timezone.utc).isoformat()}
    except MT5FeedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))



async def start_binance_spot_auto_worker():
    from .binance_spot_engine import binance_spot_auto_worker
    app.state.binance_spot_auto_task = asyncio.create_task(binance_spot_auto_worker())


async def stop_binance_spot_auto_worker():
    task = getattr(app.state, "binance_spot_auto_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
