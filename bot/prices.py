"""USD token prices from DexScreener."""

from asyncio import sleep
from decimal import Decimal, DecimalException
from time import monotonic
from urllib.parse import quote

import httpx

from .rpc import _retry_after

_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/"
_CACHE_SECONDS = 300
_RETRY_DELAYS = (1.0, 2.0)
_MAX_RETRY_WAIT = 5.0


def _usable_decimal(value: Decimal) -> bool:
    # Reject unusable API values before fixed-point formatting in a Telegram message.
    return value.is_finite() and value > 0 and -1000 <= value.adjusted() <= 1000


def _positive_decimal(raw: object) -> Decimal | None:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    try:
        value = Decimal(str(raw))
    except DecimalException:
        return None
    return value if _usable_decimal(value) else None


def _token_matches(value: object, token: str) -> bool:
    if not isinstance(value, dict):
        return False
    address = value.get("address")
    return isinstance(address, str) and address.lower() == token


def _pair_price(pair: dict[str, object], token: str) -> Decimal | None:
    base_usd = _positive_decimal(pair.get("priceUsd"))
    if base_usd is None:
        return None
    if _token_matches(pair.get("baseToken"), token):
        return base_usd
    if not _token_matches(pair.get("quoteToken"), token):
        return None
    quote_per_base = _positive_decimal(pair.get("priceNative"))
    if quote_per_base is None:
        return None
    try:
        quote_usd = base_usd / quote_per_base
    except DecimalException:
        return None
    return quote_usd if _usable_decimal(quote_usd) else None


def _best_price(payload: object, token: str) -> Decimal | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("pairs"), list):
        return None
    best_price = None
    best_liquidity = Decimal(-1)
    for pair in payload["pairs"]:
        if not isinstance(pair, dict) or pair.get("chainId") != "bsc":
            continue
        price = _pair_price(pair, token)
        if price is None:
            continue
        liquidity = pair.get("liquidity")
        usd_liquidity = (
            _positive_decimal(liquidity.get("usd")) if isinstance(liquidity, dict) else None
        ) or Decimal(0)
        if usd_liquidity > best_liquidity:
            best_liquidity, best_price = usd_liquidity, price
    return best_price


class DexPrices:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._cache: dict[str, tuple[float, Decimal | None]] = {}

    async def price_usd(self, token: str) -> Decimal | None:
        token = token.lower()
        cached = self._cache.get(token)
        if cached is not None and monotonic() < cached[0]:
            return cached[1]
        price = await self._fetch_price(token)
        self._cache[token] = (monotonic() + _CACHE_SECONDS, price)
        return price

    async def _fetch_price(self, token: str) -> Decimal | None:
        url = _TOKEN_URL + quote(token, safe="")
        for delay in (*_RETRY_DELAYS, None):
            retry_after = None
            try:
                response = await self._client.get(url)
            except httpx.RequestError:
                pass
            else:
                if response.is_success:
                    try:
                        return _best_price(response.json(), token)
                    except ValueError:
                        return None
                if response.status_code not in (408, 429) and response.status_code < 500:
                    return None
                retry_after = _retry_after(response.headers.get("Retry-After"))

            if delay is None or (retry_after is not None and retry_after > _MAX_RETRY_WAIT):
                break
            await sleep(max(delay, retry_after or 0.0))
        return None
