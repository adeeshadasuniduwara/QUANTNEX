from datetime import date, datetime, timezone
from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import PaperTrade, User
from app.telegram_reporting import build_daily_paper_pdf


def test_daily_pdf_contains_only_paper_ledger_and_computes_win_rate():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="local@quantnex.invalid", password_hash="")
        db.add(user)
        db.flush()
        # 2026-11-13 02:00 UTC is 07:30 in Colombo on the same local date.
        db.add_all([
            PaperTrade(user_id=user.id, symbol="BTCUSDT", side="BUY", quantity=1,
                       entry_price=100, stop_loss=90, take_profit=120, status="CLOSED",
                       exit_price=110, realized_pnl=10,
                       created_at=datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc),
                       closed_at=datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)),
            PaperTrade(user_id=user.id, symbol="ETHUSDT", side="SELL", quantity=2,
                       entry_price=100, stop_loss=110, take_profit=80, status="CLOSED",
                       exit_price=105, realized_pnl=-10,
                       created_at=datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc),
                       closed_at=datetime(2026, 11, 13, 4, 0, tzinfo=timezone.utc)),
            PaperTrade(user_id=user.id, symbol="SOLUSDT", side="BUY", quantity=1,
                       entry_price=50, stop_loss=45, take_profit=60, status="OPEN",
                       created_at=datetime(2026, 11, 13, 2, 0, tzinfo=timezone.utc)),
        ])
        db.commit()
        pdf, stats = build_daily_paper_pdf(db, user.id, report_day=date(2026, 11, 13))
        assert pdf.startswith(b"%PDF")
        assert stats["opened"] == 3
        assert stats["closed"] == 2
        assert stats["open_at_cutoff"] == 1
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["win_rate"] == 50.0
        assert stats["net"] == 0.0



def test_telegram_text_messages_get_branded_emoji_headers():
    from app.telegram_worker import _format_telegram_message

    assert _format_telegram_message("Status: connected") == "<b>✨ QUANTNEX</b>\n\n<b>Status: connected</b>"
    assert _format_telegram_message("QUANTNEX status: connected") == "<b>✨ QUANTNEX status: connected</b>"
    assert "&lt;script&gt;" in _format_telegram_message("<script>")
    assert "<b>STATUS</b>" in _format_telegram_message("QUANTNEX\nSTATUS")



def test_telegram_menu_is_button_first_and_has_all_primary_sections():
    from app.telegram_worker import MENU, SUBMENUS

    buttons = [button for row in MENU["inline_keyboard"] for button in row]
    labels = {button["text"] for button in buttons}
    assert {"📈 Markets & scans", "🧠 Signal controls", "🤖 Paper trading",
            "📊 Reports & goals", "⚙ Settings & status", "❔ Help & guide"} <= labels
    assert {"qx:menu:markets", "qx:menu:signals", "qx:menu:paper",
            "qx:menu:reports", "qx:menu:settings"} <= set(SUBMENUS)
    assert any(button["callback_data"] == "qx:settf:5"
               for row in SUBMENUS["qx:menu:signals"]["inline_keyboard"] for button in row)
    assert any(button["callback_data"] == "qx:scan:XAUUSD"
               for row in SUBMENUS["qx:menu:markets"]["inline_keyboard"] for button in row)


def test_signal_telegram_card_contains_side_levels_and_live_simulated_pnl():
    from types import SimpleNamespace
    from app.telegram_worker import _signal_live_message

    trade = SimpleNamespace(
        symbol="BTCUSDT", side="BUY", entry_price=100.0, last_price=102.5,
        risk_distance=5.0, status="OPEN", active_stop_loss=100.0,
        stop_loss=95.0, tp1=105.0, tp2=110.0, tp3=115.0,
        tp1_hit=True, tp2_hit=False, tp3_hit=False, realized_r=0.4,
    )
    message = _signal_live_message(trade)
    assert "BTCUSDT" in message and "BUY" in message
    assert "SL: 100" in message and "TP1: 105" in message and "TP3: 115" in message
    assert "Demo floating P&L: +0.50R" in message
    assert "LIVE · HOLDING UNTIL SL OR TP" in message


def test_signal_telegram_card_final_outcome_shows_realized_result():
    from types import SimpleNamespace
    from app.telegram_worker import _signal_live_message

    trade = SimpleNamespace(
        symbol="ETHUSDT", side="SELL", entry_price=100.0, last_price=94.0,
        risk_distance=5.0, status="TARGETS_COMPLETE", active_stop_loss=95.0,
        stop_loss=105.0, tp1=95.0, tp2=90.0, tp3=85.0,
        tp1_hit=True, tp2_hit=True, tp3_hit=True, realized_r=2.4,
    )
    message = _signal_live_message(trade)
    assert "ALL TARGETS COMPLETED" in message
    assert "Final realized result: +2.40R" in message
    assert "Demo floating P&L" not in message


def test_live_signal_updates_edit_the_original_telegram_message():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Preference, SignalTrade, User
    from app.telegram_worker import _sync_signal_trade_messages

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    async def run():
        with Session(engine) as db:
            user = User(email="local@quantnex.invalid", password_hash="")
            db.add(user)
            db.flush()
            trade = SignalTrade(
                user_id=user.id, fingerprint="BTCUSDT|BUY|5m|test", source="QUANTNEX_VIEW",
                symbol="BTCUSDT", side="BUY", timeframe="5m", entry_type="MARKET",
                entry_price=100, limit_price=None, stop_loss=95, active_stop_loss=95,
                tp1=105, tp2=110, tp3=115, risk_distance=5, status="OPEN",
                signal_time=datetime.now(timezone.utc), last_price=100,
            )
            db.add(trade)
            db.commit()
            with patch("app.telegram_worker._send", new=AsyncMock(return_value={"message_id": 321})) as send, \
                 patch("app.telegram_worker._edit_message", new=AsyncMock()) as edit:
                await _sync_signal_trade_messages(None, db, user.id, "token", "chat", edit_interval=0)
                assert send.await_count == 1
                mapping = db.scalar(select(Preference).where(
                    Preference.user_id == user.id, Preference.key == "telegram_signal_message_map"))
                assert '"message_id":321' in mapping.value
                trade.last_price = 102
                db.commit()
                await _sync_signal_trade_messages(None, db, user.id, "token", "chat", edit_interval=0)
                assert edit.await_count == 1
                assert edit.await_args.args[3] == 321

    from sqlalchemy import select
    asyncio.run(run())
    engine.dispose()
