import asyncio
from unittest.mock import MagicMock, patch

from app import telegram_worker


def test_hidden_tools_command_returns_private_catalogue():
    db = MagicMock()
    with patch.object(telegram_worker, "_get", return_value='{"primary":"5","trend":"60","enabled":["5"]}'):
        result = asyncio.run(telegram_worker._handle_command(
            MagicMock(), db, 1, "token", "12345", "/hidden_tools"
        ))

    assert result is not None
    assert "HIDDEN TOOLS" in result
    assert "Photo → PDF" in result
    assert "PDF → Images" in result
    assert "100 capability targets" in result


def test_hidden_tools_category_filter_is_private_and_scoped():
    db = MagicMock()
    with patch.object(telegram_worker, "_get", return_value='{"primary":"5","trend":"60","enabled":["5"]}'):
        result = asyncio.run(telegram_worker._handle_command(
            MagicMock(), db, 1, "token", "12345", "/hidden_tools pdf"
        ))

    assert result is not None
    assert "HIDDEN TOOLS · PDF" in result
    assert "Extract embedded images" in result


def test_normal_help_does_not_disclose_hidden_tools():
    db = MagicMock()
    with patch.object(telegram_worker, "_get", return_value='{"primary":"5","trend":"60","enabled":["5"]}'):
        result = asyncio.run(telegram_worker._handle_command(
            MagicMock(), db, 1, "token", "12345", "/help"
        ))

    assert result is not None
    assert "hidden_tools" not in result.lower()
    assert "hidden tools" not in result.lower()


def test_telegram_update_offset_is_committed_independently():
    db = MagicMock()
    db.scalar.return_value = None

    telegram_worker._persist_update_offset(db, 7, 12345)

    preference = db.add.call_args.args[0]
    assert preference.user_id == 7
    assert preference.key == "telegram_update_offset"
    assert preference.value == "12345"
    db.commit.assert_called_once()


def test_telegram_update_loop_advances_offset_in_finally():
    import inspect

    source = inspect.getsource(telegram_worker.telegram_worker)
    assert "finally:" in source
    assert "_persist_update_offset(db,user_id,offset)" in source


def test_start_command_returns_current_bilingual_workspace_menu():
    db = MagicMock()
    with patch.object(telegram_worker, "_get", return_value='{"primary":"5","trend":"60","enabled":["5"]}'):
        result = asyncio.run(telegram_worker._handle_command(
            MagicMock(), db, 1, "token", "12345", "/start"
        ))

    assert result is not None
    assert "YOUR SMART TRADING COMPANION" in result
    assert "QUANTNEX වෙත සාදරයෙන් පිළිගනිමු" in result
