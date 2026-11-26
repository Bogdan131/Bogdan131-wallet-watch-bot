import asyncio
from decimal import Decimal

import httpx
import pytest

from bot import prices as prices_module
from bot.prices import DexPrices

TOKEN = "0x" + "ab" * 20
OTHER_TOKEN = "0x" + "12" * 20


def test_price_uses_most_liquid_matching_bsc_pair_and_caches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(prices_module, "monotonic", lambda: now)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url == f"https://api.dexscreener.com/latest/dex/tokens/{TOKEN}"
        bsc_pair = {
            "chainId": "bsc",
            "baseToken": {"address": TOKEN},
            "quoteToken": {"address": OTHER_TOKEN},
            "priceUsd": str(calls),
            "liquidity": {"usd": 20000},
        }
        return httpx.Response(200, json={"pairs": [
            {**bsc_pair, "chainId": "ethereum", "priceUsd": "100", "liquidity": {"usd": 100000}},
            {**bsc_pair, "priceUsd": "80", "liquidity": {"usd": 5}},
            {**bsc_pair, "baseToken": {"address": OTHER_TOKEN}, "priceUsd": "65", "liquidity": {"usd": 200000}},
            bsc_pair,
        ]})

    async def run() -> None:
        nonlocal now
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            prices = DexPrices(client)
            assert await prices.price_usd(TOKEN.upper()) == Decimal(1)
            now += 299
            assert await prices.price_usd(TOKEN) == Decimal(1)
            assert calls == 1
            now += 1
            assert await prices.price_usd(TOKEN) == Decimal(2)
            assert calls == 2

    asyncio.run(run())


def test_quote_token_price_uses_quote_per_base_ratio() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pairs": [{
            "chainId": "bsc",
            "baseToken": {"address": OTHER_TOKEN},
            "quoteToken": {"address": TOKEN},
            "priceUsd": "75.00",
            "priceNative": "0.25",
        }]})

    async def run() -> Decimal | None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await DexPrices(client).price_usd(TOKEN)

    assert asyncio.run(run()) == Decimal(300)


@pytest.mark.parametrize(("status", "price"), [(200, None), (503, "1"), (200, "1E+1000000")])
def test_missing_price_is_cached(
    status: int, price: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    pauses: list[float] = []

    async def record_pause(delay: float) -> None:
        pauses.append(delay)

    monkeypatch.setattr(prices_module, "sleep", record_pause)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"pairs": [{
            "chainId": "bsc",
            "baseToken": {"address": TOKEN},
            "priceUsd": price,
        }]})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            prices = DexPrices(client)
            assert await prices.price_usd(TOKEN) is None
            assert await prices.price_usd(TOKEN) is None

    asyncio.run(run())
    assert calls == (3 if status == 503 else 1)
    assert pauses == ([1.0, 2.0] if status == 503 else [])


@pytest.mark.parametrize("status", [408, 429, 503, None])
def test_temporary_failure_is_retried(status: int | None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    pauses: list[float] = []

    async def record_pause(delay: float) -> None:
        pauses.append(delay)

    monkeypatch.setattr(prices_module, "sleep", record_pause)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if status is None:
                raise httpx.ReadTimeout("connection timed out", request=request)
            headers = {"Retry-After": "2.5"} if status == 429 else None
            return httpx.Response(status, headers=headers)
        return httpx.Response(200, json={"pairs": [{
            "chainId": "bsc",
            "baseToken": {"address": TOKEN},
            "priceUsd": "4",
        }]})

    async def run() -> Decimal | None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await DexPrices(client).price_usd(TOKEN)

    assert asyncio.run(run()) == Decimal(4)
    assert calls == 2
    assert pauses == ([2.5] if status == 429 else [1.0])


def test_long_retry_after_does_not_pause_scanner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def unexpected_pause(delay: float) -> None:
        pytest.fail(f"Long Retry-After should not delay scanning by {delay} seconds")

    monkeypatch.setattr(prices_module, "sleep", unexpected_pause)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "60"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            prices = DexPrices(client)
            assert await prices.price_usd(TOKEN) is None
            assert await prices.price_usd(TOKEN) is None

    asyncio.run(run())
    assert calls == 1
