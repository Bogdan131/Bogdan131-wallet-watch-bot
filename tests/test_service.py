import asyncio
import logging
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from bot import service
from bot.models import TRANSFER_TOPIC, TokenMetadata, WatchSpec
from bot.prices import DexPrices
from bot.rpc import BscRpc, RpcError
from bot.service import WalletMonitor
from bot.storage import WalletStorage


WALLET = "0x" + "11" * 20
EXCHANGE = "0x" + "22" * 20
TOKEN = "0x" + "33" * 20
TX_HASH = "0x" + "44" * 32


def _log(block: int) -> dict[str, object]:
    return {
        "topics": [
            TRANSFER_TOPIC,
            "0x" + WALLET[2:].rjust(64, "0"),
            "0x" + EXCHANGE[2:].rjust(64, "0"),
        ],
        "address": TOKEN,
        "data": "0x" + f"{1000:064x}",
        "transactionHash": TX_HASH,
        "logIndex": "0x1",
        "blockNumber": hex(block),
        "removed": False,
    }


def _setup(tmp_path: Path) -> tuple[WalletStorage, Mock, Mock, Mock, WalletMonitor]:
    storage = WalletStorage(tmp_path / "wallets.sqlite3")
    storage.initialize()
    bot = Mock(spec=Bot)
    rpc = Mock(spec=BscRpc)
    rpc.block_number.return_value = 101
    rpc.transfer_logs.return_value = [_log(101), _log(101)]
    rpc.token_metadata.return_value = TokenMetadata(1, "TEST")
    prices = Mock(spec=DexPrices)
    prices.price_usd.return_value = Decimal("10")
    monitor = WalletMonitor(bot, storage, rpc, prices, {EXCHANGE: "Binance"})
    return storage, bot, rpc, prices, monitor


def test_scan_sends_once_to_each_owner_and_respects_threshold(tmp_path: Path) -> None:
    storage, bot, rpc, prices, monitor = _setup(tmp_path)
    storage.set_checkpoint(100)
    for user_id, lang, minimum in ((1, "en", "1000"), (2, "uk", "1000"), (3, "ru", "1000.01")):
        storage.ensure_language(user_id, lang)
        storage.add_watch(user_id, WatchSpec(WALLET, "Wallet", Decimal(minimum)))
    storage.add_watch(1, WatchSpec(EXCHANGE, "Exchange", Decimal(1000)))

    asyncio.run(monitor.scan_once())

    rpc.transfer_logs.assert_awaited_once_with(101, 101, sorted([WALLET, EXCHANGE]))
    rpc.token_metadata.assert_awaited_once_with(TOKEN)
    prices.price_usd.assert_awaited_once_with(TOKEN)
    messages = {call.args[0]: call.args[1] for call in bot.send_message.await_args_list}
    assert bot.send_message.await_count == 2
    assert messages.keys() == {1, 2}
    assert "→ Binance (deposit)" in messages[1]
    assert "→ Binance (депозит)" in messages[2]
    assert all(f"https://bscscan.com/tx/{TX_HASH}" in message for message in messages.values())
    assert storage.get_checkpoint() == 101
    assert storage.get_token(TOKEN) == TokenMetadata(1, "TEST")


@pytest.mark.parametrize("checkpoint", [None, 100])
def test_scan_starts_at_head_or_skips_excessive_backlog(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, checkpoint: int | None
) -> None:
    storage, bot, rpc, _, monitor = _setup(tmp_path)
    storage.ensure_language(1, "en")
    storage.add_watch(1, WatchSpec(WALLET, "Wallet", Decimal(1000)))
    if checkpoint is not None:
        storage.set_checkpoint(checkpoint)
    rpc.block_number.return_value = 2101

    with caplog.at_level(logging.WARNING):
        asyncio.run(monitor.scan_once())

    assert storage.get_checkpoint() == 2101
    rpc.transfer_logs.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    assert ("Skipped stale blocks" in caplog.text) is (checkpoint is not None)


def test_scan_retries_failed_range_without_advancing(tmp_path: Path) -> None:
    storage, bot, rpc, _, monitor = _setup(tmp_path)
    storage.set_checkpoint(100)
    storage.ensure_language(1, "en")
    storage.add_watch(1, WatchSpec(WALLET, "Wallet", Decimal(1000)))
    rpc.transfer_logs.side_effect = [RpcError("temporary"), [_log(101)]]

    async def check() -> None:
        with pytest.raises(RpcError, match="temporary"):
            await monitor.scan_once()
        assert storage.get_checkpoint() == 100
        await monitor.scan_once()

    asyncio.run(check())
    assert storage.get_checkpoint() == 101
    assert bot.send_message.await_count == 1


def test_scan_logs_missing_price_and_skips_alert(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    storage, bot, rpc, prices, monitor = _setup(tmp_path)
    storage.set_checkpoint(100)
    storage.ensure_language(1, "en")
    storage.add_watch(1, WatchSpec(WALLET, "Wallet", Decimal(1000)))
    prices.price_usd.return_value = None

    with caplog.at_level(logging.INFO):
        asyncio.run(monitor.scan_once())

    assert "USD price is unavailable" in caplog.text
    bot.send_message.assert_not_awaited()
    rpc.token_metadata.assert_not_awaited()
    assert storage.get_checkpoint() == 101


def test_telegram_rate_limit_retries_without_redelivering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, bot, rpc, _, monitor = _setup(tmp_path)
    storage.set_checkpoint(100)
    for user_id in (1, 2):
        storage.ensure_language(user_id, "en")
        storage.add_watch(user_id, WatchSpec(WALLET, "Wallet", Decimal(1000)))
    clock = 100.0
    monkeypatch.setattr(service, "monotonic", lambda: clock)
    bot.send_message.side_effect = [
        None,
        TelegramRetryAfter(
            method=SendMessage(chat_id=2, text="Alert"), message="Rate limited", retry_after=2
        ),
        None,
    ]

    async def check() -> None:
        nonlocal clock
        await monitor.scan_once()
        assert storage.get_checkpoint() == 100
        await monitor.scan_once()
        assert rpc.block_number.await_count == 1
        clock += 2
        await monitor.scan_once()

    asyncio.run(check())
    assert storage.get_checkpoint() == 101
    assert [call.args[0] for call in bot.send_message.await_args_list] == [1, 2, 2]
