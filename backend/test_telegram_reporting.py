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




def test_telegram_formatter_preserves_safe_html_tags_and_real_line_breaks():
    from app.telegram_worker import _format_telegram_message

    message = (
        "🌍 <b>QUANTNEX · NEW MARKET SESSION</b>\n\n"
        "🇺🇸 <b>New York SESSION OPENED</b>\n"
        "Closes in: 8h 59m\n"
        "Expected close (Sri Lanka): 03:30 AM\n\n"
        "<b>Currently running:</b> London + New York\n"
        "🇱🇰 All times are Sri Lanka time. Session hours follow local DST rules."
    )
    rendered = _format_telegram_message(message)

    assert "✨ 🌍 <b>QUANTNEX · NEW MARKET SESSION</b>" in rendered
    assert "🇺🇸 <b>New York SESSION OPENED</b>" in rendered
    assert "<b>Closes in:</b> 8h 59m" in rendered
    assert "<b>Expected close (Sri Lanka):</b> 03:30 AM" in rendered
    assert "<b>Currently running:</b> London + New York" in rendered
    assert "\\n" not in rendered
    assert "&lt;b&gt;" not in rendered
    assert "&lt;script&gt;" in _format_telegram_message("<script>")


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
