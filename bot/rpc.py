"""Async JSON-RPC reads for BNB Smart Chain."""

import math
import re
from asyncio import Lock, sleep
from collections.abc import Sequence
from email.utils import parsedate_to_datetime
from time import monotonic, time

import httpx

from .models import TRANSFER_TOPIC, TokenMetadata

_ADDRESS = re.compile(r"0x[0-9a-f]{40}", re.IGNORECASE)
_QUANTITY = re.compile(r"0x[0-9a-f]+", re.IGNORECASE)
_ABI_RESULT = re.compile(r"0x(?:[0-9a-f]{2})*", re.IGNORECASE)
_DECIMALS_SELECTOR = "0x313ce567"
_SYMBOL_SELECTOR = "0x95d89b41"
_ATTEMPTS = 3
_WORD_SIZE = 32
_MAX_BLOCK_NUMBER = 2**63 - 1


class RpcError(RuntimeError):
    """RPC could not return a valid result."""


class TokenMetadataError(RpcError):
    """A contract could not provide supported ERC-20 metadata."""


class _RangeLimit(RpcError):
    """The provider asked for a smaller log query."""

    def __init__(self, message: str, *, split_addresses: bool = False) -> None:
        super().__init__(message)
        self.split_addresses = split_addresses


class _TemporaryError(RpcError):
    def __init__(
        self, message: str, *, rate_limited: bool = False, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited
        self.retry_after = retry_after


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time()
        except (ValueError, TypeError, OverflowError, OSError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def _result(payload: object, method: str) -> object:
    if not isinstance(payload, dict):
        raise RpcError(f"{method}: invalid JSON-RPC response")
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = str(error.get("message", "")).lower()
        summary = f"{method}: JSON-RPC error"
        if type(code) is int:
            summary = f"{summary} {code}"
        if method == "eth_call" and (
            code in (3, -32015)
            or any(phrase in message for phrase in ("revert", "invalid opcode", "out of gas"))
        ):
            raise TokenMetadataError(summary)
        if method == "eth_getLogs" and any(
            phrase in message
            for phrase in (
                "too many addresses", "too many topics", "maximum number of addresses",
                "maximum number of topics",
            )
        ):
            raise _RangeLimit(summary, split_addresses=True)
        if method == "eth_getLogs" and (
            "block range" in message
            and any(word in message for word in ("exceed", "limit", "maximum", "too large"))
            or any(
                phrase in message
                for phrase in (
                    "query returned more than", "too many results", "response size exceeded",
                    "logs limit exceeded",
                )
            )
        ):
            raise _RangeLimit(summary)
        if code in (429, -32005, -32016) or "rate limit" in message or "too many requests" in message:
            raise _TemporaryError(summary, rate_limited=True)
        if code in (-32002, -32603):
            raise _TemporaryError(summary)
        raise RpcError(summary)
    if error is not None or "result" not in payload:
        raise RpcError(f"{method}: invalid JSON-RPC response")
    return payload["result"]


def _address_topic(address: str) -> str:
    if _ADDRESS.fullmatch(address) is None:
        raise ValueError("Expected a 20-byte wallet address")
    return "0x" + address[2:].lower().rjust(64, "0")


def _abi_data(result: object) -> bytes:
    if not isinstance(result, str) or _ABI_RESULT.fullmatch(result) is None:
        raise TokenMetadataError("eth_call: invalid ABI data")
    return bytes.fromhex(result[2:])


def _decode_decimals(result: object) -> int:
    data = _abi_data(result)
    if len(data) != _WORD_SIZE:
        raise TokenMetadataError("eth_call: invalid decimals")
    decimals = int.from_bytes(data)
    if decimals > 255:
        raise TokenMetadataError("eth_call: decimals outside uint8 range")
    return decimals


def _decode_symbol(result: object) -> str:
    data = _abi_data(result)
    if len(data) == _WORD_SIZE:
        # Some older ERC-20 contracts return bytes32.
        symbol_bytes = data.rstrip(b"\x00")
    else:
        offset = int.from_bytes(data[:_WORD_SIZE])
        data_start = offset + _WORD_SIZE
        if offset < _WORD_SIZE or offset % _WORD_SIZE != 0 or data_start > len(data):
            raise TokenMetadataError("eth_call: invalid symbol offset")
        length = int.from_bytes(data[offset:data_start])
        if length == 0 or data_start + length > len(data):
            raise TokenMetadataError("eth_call: invalid symbol length")
        symbol_bytes = data[data_start:data_start + length]
    try:
        symbol = symbol_bytes.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise TokenMetadataError("eth_call: invalid UTF-8 symbol") from None
    if not symbol or not symbol.isprintable() or len(symbol) > 128:
        raise TokenMetadataError("eth_call: invalid token symbol")
    return symbol


class BscRpc:
    def __init__(self, client: httpx.AsyncClient, url: str, requests_per_second: int) -> None:
        if requests_per_second <= 0:
            raise ValueError("RPC request rate must be positive")
        self._client = client
        self._url = url
        self._interval = 1 / requests_per_second
        self._next_request_at = 0.0
        self._rate_lock = Lock()

    async def _wait_for_slot(self) -> None:
        async with self._rate_lock:
            while (delay := self._next_request_at - monotonic()) > 0:
                await sleep(delay)
            self._next_request_at = monotonic() + self._interval

    async def _post(self, method: str, params: list[object]) -> object:
        try:
            response = await self._client.post(
                self._url, json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            )
        except httpx.RequestError:
            raise _TemporaryError(f"{method}: connection failed") from None
        except httpx.InvalidURL:
            raise RpcError(f"{method}: invalid RPC URL") from None

        status = response.status_code
        if status == 429:
            raise _TemporaryError(
                f"{method}: HTTP 429", rate_limited=True,
                retry_after=_retry_after(response.headers.get("Retry-After")),
            )
        if status == 413 and method == "eth_getLogs":
            raise _RangeLimit(f"{method}: HTTP {status}", split_addresses=True)
        if status == 408 or status >= 500:
            raise _TemporaryError(f"{method}: HTTP {status}")
        if not response.is_success:
            raise RpcError(f"{method}: HTTP {status}")
        try:
            payload = response.json()
        except ValueError:
            raise _TemporaryError(f"{method}: invalid JSON response") from None
        return _result(payload, method)

    async def _request(self, method: str, params: list[object]) -> object:
        for attempt in range(_ATTEMPTS):
            await self._wait_for_slot()
            try:
                return await self._post(method, params)
            except _TemporaryError as error:
                delay = error.retry_after if error.retry_after is not None else 2.0 ** attempt
                if error.rate_limited:
                    self._next_request_at = max(self._next_request_at, monotonic() + delay)
                if attempt + 1 == _ATTEMPTS:
                    raise RpcError(str(error)) from None
                if not error.rate_limited:
                    await sleep(delay)
        raise AssertionError("RPC retry loop exhausted without a result")

    async def block_number(self) -> int:
        result = await self._request("eth_blockNumber", [])
        if not isinstance(result, str) or _QUANTITY.fullmatch(result) is None:
            raise RpcError("eth_blockNumber: invalid block number")
        number = int(result, 16)
        if number > _MAX_BLOCK_NUMBER:
            raise RpcError("eth_blockNumber: block number outside SQLite INTEGER range")
        return number

    async def transfer_logs(
        self, start: int, end: int, addresses: Sequence[str]
    ) -> list[dict[str, object]]:
        if start < 0 or end < start:
            raise ValueError("Invalid log block interval")
        if not addresses:
            return []
        topics = sorted({_address_topic(address) for address in addresses})
        return await self._transfer_logs(start, end, topics)

    async def _transfer_logs(
        self, start: int, end: int, topics: list[str]
    ) -> list[dict[str, object]]:
        try:
            sent = await self._logs(start, end, [TRANSFER_TOPIC, topics])
            received = await self._logs(start, end, [TRANSFER_TOPIC, None, topics])
            return sent + received
        except _RangeLimit as error:
            if len(topics) > 1 and (start == end or error.split_addresses):
                middle_address = len(topics) // 2
                left = await self._transfer_logs(start, end, topics[:middle_address])
                right = await self._transfer_logs(start, end, topics[middle_address:])
                return left + right
            if start == end:
                raise
            middle = (start + end) // 2
            left = await self._transfer_logs(start, middle, topics)
            right = await self._transfer_logs(middle + 1, end, topics)
            return left + right

    async def _logs(self, start: int, end: int, topics: list[object]) -> list[dict[str, object]]:
        result = await self._request(
            "eth_getLogs", [{"fromBlock": hex(start), "toBlock": hex(end), "topics": topics}]
        )
        if not isinstance(result, list) or not all(isinstance(row, dict) for row in result):
            raise RpcError("eth_getLogs: invalid log list")
        return result

    async def token_metadata(self, token: str) -> TokenMetadata:
        decimals = _decode_decimals(
            await self._request("eth_call", [{"to": token, "data": _DECIMALS_SELECTOR}, "latest"])
        )
        symbol = _decode_symbol(
            await self._request("eth_call", [{"to": token, "data": _SYMBOL_SELECTOR}, "latest"])
        )
        return TokenMetadata(decimals=decimals, symbol=symbol)
