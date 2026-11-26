import asyncio
import logging
import traceback
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from time import monotonic

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import LinkPreviewOptions

from .domain import (
    decode_transfer,
    meets_threshold,
    scan_bounds,
    should_skip_backlog,
    token_amount,
    usd_value,
)
from .models import TokenMetadata, Transfer, Watch
from .prices import DexPrices
from .rpc import BscRpc, RpcError, TokenMetadataError
from .storage import WalletStorage
from .texts import alert_message


log = logging.getLogger(__name__)


class WalletMonitor:
    def __init__(
        self,
        bot: Bot,
        storage: WalletStorage,
        rpc: BscRpc,
        prices: DexPrices,
        exchange_labels: Mapping[str, str],
    ) -> None:
        self._bot = bot
        self._storage = storage
        self._rpc = rpc
        self._prices = prices
        self._exchange_labels = exchange_labels
        self._telegram_paused_until = 0.0

    async def run(self, interval: int) -> None:
        while True:
            started = monotonic()
            try:
                await self.scan_once()
            except RpcError as error:
                log.warning("BSC scan deferred: %s", error)
            except Exception as error:
                # Keep the bot alive; log only the error type and location, never its text.
                frame = traceback.extract_tb(error.__traceback__)[-1]
                log.error(
                    "BSC scan failed: %s at %s:%s",
                    type(error).__name__, Path(frame.filename).name, frame.lineno,
                )
            await asyncio.sleep(max(0, interval - (monotonic() - started)))

    async def scan_once(self) -> None:
        if monotonic() < self._telegram_paused_until:
            return

        head = await self._rpc.block_number()
        checkpoint = await asyncio.to_thread(self._storage.get_checkpoint)
        if checkpoint is None:
            await asyncio.to_thread(self._storage.set_checkpoint, head)
            return
        if should_skip_backlog(checkpoint, head):
            log.warning("Skipped stale blocks %s–%s because the BSC scanner fell behind", checkpoint + 1, head)
            await asyncio.to_thread(self._storage.set_checkpoint, head)
            return

        bounds = scan_bounds(checkpoint, head)
        if bounds is None:
            return
        start, end = bounds
        by_address: dict[str, list[Watch]] = defaultdict(list)
        for watch in await asyncio.to_thread(self._storage.list_watches):
            by_address[watch.address].append(watch)
        if not by_address:
            await asyncio.to_thread(self._storage.set_checkpoint, head)
            return

        unique: dict[tuple[str, int], Transfer] = {}
        for entry in await self._rpc.transfer_logs(start, end, sorted(by_address)):
            transfer = decode_transfer(entry)
            if transfer is not None and start <= transfer.block_number <= end:
                unique.setdefault((transfer.tx_hash, transfer.log_index), transfer)

        valuations: dict[str, tuple[TokenMetadata, Decimal] | None] = {}
        for transfer in sorted(unique.values(), key=lambda entry: (entry.block_number, entry.log_index)):
            matches = by_address.get(transfer.sender, []) + by_address.get(transfer.recipient, [])
            if not matches or not transfer.raw_amount:
                continue
            token = transfer.token_address
            if token not in valuations:
                valuations[token] = await self._valuation(token)
            valuation = valuations[token]
            if valuation is None:
                continue

            metadata, price = valuation
            amount = token_amount(transfer.raw_amount, metadata.decimals)
            value = usd_value(amount, price)
            for watch in sorted(matches, key=lambda item: item.id):
                if meets_threshold(value, watch.minimum_usd):
                    if not await self._deliver(watch, transfer, metadata, amount, value):
                        return
        await asyncio.to_thread(self._storage.set_checkpoint, end)

    async def _valuation(self, token: str) -> tuple[TokenMetadata, Decimal] | None:
        price = await self._prices.price_usd(token)
        if price is None:
            log.info("Skipped transfers for token %s because its USD price is unavailable", token)
            return None
        metadata = await asyncio.to_thread(self._storage.get_token, token)
        if metadata is None:
            try:
                metadata = await self._rpc.token_metadata(token)
            except TokenMetadataError as error:
                log.info("Skipped token %s with unsupported metadata: %s", token, error)
                return None
            await asyncio.to_thread(self._storage.save_token, token, metadata)
        return metadata, price

    async def _deliver(
        self, watch: Watch, transfer: Transfer, metadata: TokenMetadata, amount: Decimal, value: Decimal
    ) -> bool:
        """Return false to pause the range without advancing its checkpoint."""
        key = (watch.user_id, transfer.tx_hash, transfer.log_index)
        if not await asyncio.to_thread(self._storage.claim_delivery, *key):
            return True
        try:
            await self._bot.send_message(
                watch.user_id,
                alert_message(watch, transfer, metadata, amount, value, self._exchange_labels),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramRetryAfter as error:
            await asyncio.to_thread(self._storage.release_delivery, *key)
            self._telegram_paused_until = monotonic() + error.retry_after
            return False
        except TelegramForbiddenError:
            removed = await asyncio.to_thread(self._storage.delete_user_watches, watch.user_id)
            log.info("Removed %s watches of a user who blocked the bot", removed)
        except TelegramAPIError as error:
            # An uncertain response may mean Telegram has already accepted the message.
            log.warning("Could not confirm alert delivery for %s (%s)", transfer.tx_hash, type(error).__name__)
        return True
