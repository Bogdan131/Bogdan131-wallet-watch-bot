import re
import shlex
from decimal import Decimal, InvalidOperation, localcontext

from .models import TRANSFER_TOPIC, Language, Transfer, WatchSpec


DEFAULT_MINIMUM_USD = Decimal(1000)
MAX_SCAN_BLOCKS = 500
MAX_BACKLOG_BLOCKS = 2000

_ADDRESS = re.compile(r"0x[0-9a-f]{40}", re.IGNORECASE)
_ADDRESS_TOPIC = re.compile(r"0x0{24}[0-9a-f]{40}", re.IGNORECASE)
_WORD = re.compile(r"0x[0-9a-f]{64}", re.IGNORECASE)
_HEX_INTEGER = re.compile(r"0x[0-9a-f]{1,16}", re.IGNORECASE)
_WATCH_ID = re.compile(r"[0-9]{1,19}")
_AMOUNT = re.compile(r"[0-9]+(?:[.,][0-9]+)?|[.,][0-9]+")
_SQLITE_MAX_INTEGER = 2**63 - 1


class CommandError(ValueError):
    """An invalid command with a localizable error key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _parse_usd(text: str) -> Decimal:
    if len(text) <= 64 and _AMOUNT.fullmatch(text):
        value = Decimal(text.replace(",", "."))
        if value > 0:
            return value
    raise CommandError("invalid_usd")


def _is_number(text: str) -> bool:
    try:
        Decimal(text.replace(",", "."))
    except InvalidOperation:
        return False
    return True


def parse_watch(arguments: str | None) -> WatchSpec:
    try:
        parts = shlex.split(arguments or "")
    except ValueError as error:
        raise CommandError("watch_usage") from error
    if not parts:
        raise CommandError("watch_usage")

    address, *options = parts
    if not _ADDRESS.fullmatch(address):
        raise CommandError("invalid_address")
    address = address.lower()
    minimum = DEFAULT_MINIMUM_USD
    if options and _is_number(options[-1]):
        minimum = _parse_usd(options.pop())

    label = " ".join(" ".join(options).split()) or short_address(address)
    if len(label) > 64:
        raise CommandError("invalid_label")
    return WatchSpec(address, label, minimum)


def parse_watch_id(arguments: str | None) -> int:
    number = (arguments or "").strip()
    if _WATCH_ID.fullmatch(number) and 0 < int(number) <= _SQLITE_MAX_INTEGER:
        return int(number)
    raise CommandError("invalid_watch_id")


def parse_minimum(arguments: str | None) -> tuple[int, Decimal]:
    parts = (arguments or "").split()
    if len(parts) != 2:
        raise CommandError("min_usage")
    return parse_watch_id(parts[0]), _parse_usd(parts[1])


def parse_language(arguments: str | None) -> Language | None:
    language = (arguments or "").strip().lower()
    if not language:
        return None
    if language == "uk" or language == "ru" or language == "en":
        return language
    raise CommandError("language_usage")


def default_language(language_code: str | None) -> Language:
    code = (language_code or "").lower()
    if code.startswith("uk"):
        return "uk"
    if code.startswith("ru"):
        return "ru"
    return "en"


def decode_transfer(log: object) -> Transfer | None:
    if not isinstance(log, dict) or log.get("removed", False) is not False:
        return None
    topics = log.get("topics")
    if (
        not isinstance(topics, list)
        or len(topics) != 3
        or not isinstance(topics[0], str)
        or topics[0].lower() != TRANSFER_TOPIC
    ):
        return None

    sender, recipient = topics[1:]
    if not all(isinstance(topic, str) and _ADDRESS_TOPIC.fullmatch(topic) for topic in (sender, recipient)):
        return None

    tx_hash = log.get("transactionHash")
    token_address = log.get("address")
    data = log.get("data")
    log_index = log.get("logIndex")
    block = log.get("blockNumber")
    if (
        not isinstance(tx_hash, str) or not _WORD.fullmatch(tx_hash)
        or not isinstance(token_address, str) or not _ADDRESS.fullmatch(token_address)
        or not isinstance(data, str) or not _WORD.fullmatch(data)
        or not isinstance(log_index, str) or not _HEX_INTEGER.fullmatch(log_index)
        or not isinstance(block, str) or not _HEX_INTEGER.fullmatch(block)
    ):
        return None
    index = int(log_index, 16)
    block_number = int(block, 16)
    if max(index, block_number) > _SQLITE_MAX_INTEGER:
        return None
    return Transfer(
        tx_hash=tx_hash.lower(),
        log_index=index,
        block_number=block_number,
        token_address=token_address.lower(),
        sender="0x" + sender[-40:].lower(),
        recipient="0x" + recipient[-40:].lower(),
        raw_amount=int(data, 16),
    )


def scan_bounds(checkpoint: int, head: int) -> tuple[int, int] | None:
    if checkpoint >= head:
        return None
    return checkpoint + 1, min(checkpoint + MAX_SCAN_BLOCKS, head)


def should_skip_backlog(checkpoint: int, head: int) -> bool:
    return head - checkpoint > MAX_BACKLOG_BLOCKS


def token_amount(raw_amount: int, decimals: int) -> Decimal:
    return Decimal(f"{raw_amount}E{-decimals}")


def usd_value(amount: Decimal, price: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = len(amount.as_tuple().digits) + len(price.as_tuple().digits)
        return amount * price


def meets_threshold(usd: Decimal, minimum: Decimal) -> bool:
    return usd >= minimum


def short_address(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}"
