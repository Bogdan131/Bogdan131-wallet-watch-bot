from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


Language = Literal["uk", "ru", "en"]
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


@dataclass(frozen=True, slots=True)
class WatchSpec:
    address: str
    label: str
    minimum_usd: Decimal


@dataclass(frozen=True, slots=True)
class Watch:
    id: int
    user_id: int
    address: str
    label: str
    minimum_usd: Decimal
    lang: Language


@dataclass(frozen=True, slots=True)
class Transfer:
    tx_hash: str
    log_index: int
    block_number: int
    token_address: str
    sender: str
    recipient: str
    raw_amount: int


@dataclass(frozen=True, slots=True)
class TokenMetadata:
    decimals: int
    symbol: str
