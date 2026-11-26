import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from bot.handlers import build_router
from bot.main import Settings
from bot.storage import WalletStorage


def test_settings_require_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_TOKEN", "")
    with pytest.raises(ValueError, match="BOT_TOKEN"):
        Settings.from_env()


def test_private_command_flow(tmp_path: Path) -> None:
    storage = WalletStorage(tmp_path / "wallets.sqlite3")
    storage.initialize()
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())
    bot = AsyncMock(spec=Bot)
    bot.id = 9
    address = "0x" + "11" * 20
    commands = [
        "/list",
        f"/watch {address} Main wallet 1000",
        "/min 1 2100.25",
        "/lang en",
        "/list",
        "/unwatch 1",
        "/start",
    ]

    async def check() -> None:
        for index, text in enumerate(commands, start=1):
            update = Update.model_validate({
                "update_id": index,
                "message": {
                    "message_id": index,
                    "date": 0,
                    "chat": {"id": 1, "type": "private"},
                    "from": {"id": 1, "is_bot": False, "first_name": "User", "language_code": "uk-UA"},
                    "text": text,
                },
            })
            await dispatcher.feed_update(bot, update, storage=storage)

    asyncio.run(check())
    replies = [call.args[0].text for call in bot.await_args_list]
    assert len(replies) == len(commands)
    assert "Список поки порожній" in replies[0]
    assert "$2100.25" in replies[2]
    assert "English" in replies[3]
    assert "Main wallet" in replies[4]
    assert address in replies[4]
    assert "Wallet #1 removed" in replies[5]
    assert "/watch" in replies[6]
    assert storage.list_watches(1) == []
    assert storage.ensure_language(1, "uk") == "en"
