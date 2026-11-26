import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from bot import rpc as rpc_module
from bot.models import TRANSFER_TOPIC, TokenMetadata
from bot.rpc import BscRpc, RpcError, TokenMetadataError

RPC_URL = "https://rpc.example.invalid"
ADDRESS = "0x" + "ab" * 20
TOKEN = "0x" + "12" * 20


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Callable[[], float]:
    current = 100.0

    def now() -> float:
        return current

    async def advance(seconds: float) -> None:
        nonlocal current
        current += seconds

    monkeypatch.setattr(rpc_module, "monotonic", now)
    monkeypatch.setattr(rpc_module, "sleep", advance)
    return now


def test_rpc_retries_429_and_connection_error(clock: Callable[[], float]) -> None:
    attempts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == RPC_URL
        assert payload == {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
        attempts.append(clock())
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "2.5"})
        if len(attempts) == 2:
            raise httpx.ReadTimeout("transport details", request=request)
        return httpx.Response(200, json={"result": "0x1a"})

    async def run() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BscRpc(client, RPC_URL, 3).block_number()

    assert asyncio.run(run()) == 26
    assert attempts == pytest.approx([100.0, 102.5, 104.5])


def test_failed_rpc_respects_retry_budget(clock: Callable[[], float]) -> None:
    attempts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(clock())
        return httpx.Response(503)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await BscRpc(client, RPC_URL, 3).block_number()

    with pytest.raises(RpcError, match="eth_blockNumber: HTTP 503"):
        asyncio.run(run())
    assert attempts == pytest.approx([100.0, 101.0, 103.0])


def test_block_number_cannot_overflow_checkpoint(clock: Callable[[], float]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": hex(2**63)})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await BscRpc(client, RPC_URL, 3).block_number()

    with pytest.raises(RpcError, match="SQLite INTEGER range"):
        asyncio.run(run())


def test_transfer_logs_filter_each_indexed_address(clock: Callable[[], float]) -> None:
    filters: list[dict[str, object]] = []
    starts: list[float] = []
    address_topic = "0x" + "0" * 24 + ADDRESS[2:]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["method"] == "eth_getLogs"
        starts.append(clock())
        filters.append(payload["params"][0])
        return httpx.Response(200, json={"result": [{"logIndex": hex(len(filters))}]})

    async def run() -> list[dict[str, object]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BscRpc(client, RPC_URL, 3).transfer_logs(42, 541, [ADDRESS, ADDRESS.upper()])

    assert asyncio.run(run()) == [{"logIndex": "0x1"}, {"logIndex": "0x2"}]
    assert filters == [
        {"fromBlock": "0x2a", "toBlock": "0x21d", "topics": [TRANSFER_TOPIC, [address_topic]]},
        {"fromBlock": "0x2a", "toBlock": "0x21d", "topics": [TRANSFER_TOPIC, None, [address_topic]]},
    ]
    assert starts == pytest.approx([100.0, 100.0 + 1 / 3])


def test_transfer_logs_split_explicit_provider_range_limit(clock: Callable[[], float]) -> None:
    ranges: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log_filter = json.loads(request.content)["params"][0]
        interval = (int(log_filter["fromBlock"], 16), int(log_filter["toBlock"], 16))
        ranges.append(interval)
        if interval == (1, 500):
            return httpx.Response(
                200, json={"error": {"code": -32005, "message": "block range exceeds limit"}}
            )
        return httpx.Response(200, json={"result": []})

    async def run() -> list[dict[str, object]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BscRpc(client, RPC_URL, 3).transfer_logs(1, 500, [ADDRESS])

    assert asyncio.run(run()) == []
    assert ranges == [(1, 500), (1, 250), (1, 250), (251, 500), (251, 500)]


@pytest.mark.parametrize(
    ("end", "message"), [(42, "response size exceeded"), (160, "too many addresses")]
)
def test_transfer_logs_splits_oversized_address_filter(
    clock: Callable[[], float], end: int, message: str
) -> None:
    filter_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log_filter = json.loads(request.content)["params"][0]
        assert log_filter["fromBlock"] == hex(42) and log_filter["toBlock"] == hex(end)
        filter_sizes.append(len(log_filter["topics"][-1]))
        if filter_sizes[-1] > 1:
            return httpx.Response(200, json={"error": {"code": -32005, "message": message}})
        return httpx.Response(200, json={"result": []})

    async def run() -> list[dict[str, object]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BscRpc(client, RPC_URL, 3).transfer_logs(42, end, [ADDRESS, TOKEN])

    assert asyncio.run(run()) == []
    assert filter_sizes == [2, 1, 1, 1, 1]


@pytest.mark.parametrize("legacy", [False, True])
def test_token_metadata_decodes_both_symbol_formats(
    clock: Callable[[], float], legacy: bool
) -> None:
    symbol_word = b"USDT".ljust(32, b"\x00")
    symbol = symbol_word if legacy else (32).to_bytes(32) + (4).to_bytes(32) + symbol_word
    selectors: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["method"] == "eth_call"
        args, block = payload["params"]
        assert args["to"] == TOKEN and block == "latest"
        selector = args["data"]
        selectors.append(selector)
        data = (18).to_bytes(32) if selector == "0x313ce567" else symbol
        return httpx.Response(200, json={"result": "0x" + data.hex()})

    async def run() -> TokenMetadata:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BscRpc(client, RPC_URL, 3).token_metadata(TOKEN)

    assert asyncio.run(run()) == TokenMetadata(decimals=18, symbol="USDT")
    assert selectors == ["0x313ce567", "0x95d89b41"]


@pytest.mark.parametrize(
    "payload",
    [{"result": "0x"}, {"error": {"code": 3, "message": "execution reverted: rate limit"}}],
)
def test_unsupported_contract_is_distinct_from_transport_failure(
    clock: Callable[[], float], payload: dict[str, object]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await BscRpc(client, RPC_URL, 3).token_metadata(TOKEN)

    with pytest.raises(TokenMetadataError):
        asyncio.run(run())
