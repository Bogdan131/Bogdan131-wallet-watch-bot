import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import load_dotenv

from .handlers import build_router
from .prices import DexPrices
from .rpc import BscRpc
from .service import WalletMonitor
from .storage import WalletStorage


DEFAULT_RPC_URL = "https://bsc-rpc.publicnode.com"
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str = field(repr=False)
    rpc_url: str = field(repr=False)
    rpc_rps: int
    check_seconds: int
    db_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(".env")
        token = os.getenv("BOT_TOKEN", "").strip()
        try:
            validate_token(token)
        except TokenValidationError:
            raise ValueError("Set BOT_TOKEN in .env using the token from @BotFather.") from None

        rpc_url = os.getenv("BSC_RPC_URL", DEFAULT_RPC_URL).strip()
        try:
            url = httpx.URL(rpc_url)
        except (ValueError, httpx.InvalidURL):
            raise ValueError("BSC_RPC_URL must be an HTTP or HTTPS URL.") from None
        if url.scheme not in {"http", "https"} or not url.host:
            raise ValueError("BSC_RPC_URL must be an HTTP or HTTPS URL.")

        db_path = os.getenv("DB_PATH", "data/wallets.sqlite3").strip()
        if not db_path:
            raise ValueError("DB_PATH must point to a SQLite file.")
        return cls(token, rpc_url, _positive_int("RPC_RPS", 3), _positive_int("CHECK_SECONDS", 5), Path(db_path))


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = 0
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


async def _wait_for_telegram(bot: Bot) -> None:
    delay = 1
    while True:
        try:
            await bot.me()
            return
        except TelegramRetryAfter as error:
            pause = error.retry_after
        except (TelegramNetworkError, TelegramServerError):
            pause = delay
            delay = min(delay * 2, 30)
        log.warning("Telegram is temporarily unavailable. Retrying in %s seconds", pause)
        await asyncio.sleep(pause)


async def main(settings: Settings) -> None:
    storage = WalletStorage(settings.db_path)
    await asyncio.to_thread(storage.initialize)
    path = Path(__file__).with_name("data") / "exchanges.json"
    labels: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router())

    async with Bot(settings.bot_token) as bot, httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4)) as client:
        await _wait_for_telegram(bot)
        rpc = BscRpc(client, settings.rpc_url, settings.rpc_rps)
        monitor = WalletMonitor(bot, storage, rpc, DexPrices(client), labels)
        async with asyncio.TaskGroup() as tasks:
            scanner = tasks.create_task(monitor.run(settings.check_seconds))
            try:
                await dispatcher.start_polling(
                    bot, storage=storage, allowed_updates=dispatcher.resolve_used_update_types(),
                    close_bot_session=False,
                )
            finally:
                scanner.cancel()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    try:
        asyncio.run(main(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
