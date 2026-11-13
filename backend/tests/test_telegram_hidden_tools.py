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
        result = await telegram_worker._handle_command(
            MagicMock(), db, 1, "token", "12345", "/hidden_tools pdf"
        ))

    assert result is not None
    assert "HIDDEN TOOLS · PDF" in result
    assert "Extract embedded images" in result


def test_normal_help_does_not_disclose_hidden_tools():
    db = MagicMock()
    with patch.object(telegram_worker, "_get", return_value='{"primary":"5","trend":"60","enabled":["5"]}'):
        result = await telegram_worker._handle_command(
            MagicMock(), db, 1, "token", "12345", "/help"
        ))

    assert result is not None
    assert "hidden_tools" not in result.lower()
    assert "hidden tools" not in result.lower()
