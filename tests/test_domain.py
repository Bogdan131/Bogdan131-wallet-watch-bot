import json
from decimal import Decimal

import pytest

from bot.domain import (
    CommandError,
    decode_transfer,
    default_language,
    meets_threshold,
    parse_language,
    parse_minimum,
    parse_watch,
    parse_watch_id,
    scan_bounds,
    should_skip_backlog,
    token_amount,
    usd_value,
)
from bot.models import TRANSFER_TOPIC, Language, Transfer, WatchSpec


SENDER = "0x" + "ab" * 20
RECIPIENT = "0x" + "cd" * 20
TOKEN = "0x" + "11" * 20
TRANSACTION = "0x" + "ff" * 32


@pytest.fixture
def transfer_log() -> dict[str, object]:
    return json.loads(
        f"""
        {{
            "address": "{TOKEN}",
            "topics": ["{TRANSFER_TOPIC}", "0x{SENDER[2:].zfill(64)}", "0x{RECIPIENT[2:].zfill(64)}"],
            "data": "0x{1500000000000000000:064x}",
            "transactionHash": "{TRANSACTION}",
            "logIndex": "0x7",
            "blockNumber": "0x2a",
            "removed": false
        }}
        """
    )


@pytest.mark.parametrize(
    ("options", "label", "minimum"),
    [
        ("", "0xabab…abab", "1000"),
        (" 500 ", "0xabab…abab", "500"),
        (" Main wallet ", "Main wallet", "1000"),
        (' "Main wallet" 1,25', "Main wallet", "1.25"),
        (' "Main wallet 2" 100', "Main wallet 2", "100"),
    ],
)
def test_parse_watch(options: str, label: str, minimum: str) -> None:
    assert parse_watch(SENDER.upper() + options) == WatchSpec(SENDER, label, Decimal(minimum))


@pytest.mark.parametrize(
    ("arguments", "key"),
    [
        (None, "watch_usage"),
        ("0xabcdef", "invalid_address"),
        (SENDER + ' "unclosed', "watch_usage"),
        (SENDER + " " + "a" * 65, "invalid_label"),
        (SENDER + " team -1", "invalid_usd"),
        (SENDER + " 0", "invalid_usd"),
        (SENDER + " NaN", "invalid_usd"),
        (SENDER + " Infinity", "invalid_usd"),
    ],
)
def test_parse_watch_errors(arguments: str | None, key: str) -> None:
    with pytest.raises(CommandError) as error:
        parse_watch(arguments)
    assert error.value.key == key


def test_parse_minimum_and_unwatch_id() -> None:
    assert parse_watch_id(" 9 ") == 9
    assert parse_minimum("9 1,25") == (9, Decimal("1.25"))


@pytest.mark.parametrize("number", ["0", "-1", "٩", "3 extra", str(2**63)])
def test_reject_invalid_watch_ids(number: str) -> None:
    with pytest.raises(CommandError, match="invalid_watch_id"):
        parse_watch_id(number)


def test_reject_invalid_minimum_arguments() -> None:
    with pytest.raises(CommandError, match="min_usage"):
        parse_minimum("1")
    with pytest.raises(CommandError, match="invalid_usd"):
        parse_minimum("1 -10")


@pytest.mark.parametrize(
    ("locale", "language"), [("uk-UA", "uk"), ("RU", "ru"), ("en-US", "en"), ("fr", "en"), (None, "en")]
)
def test_default_language(locale: str | None, language: Language) -> None:
    assert default_language(locale) == language


def test_parse_language() -> None:
    assert parse_language(None) is None
    assert parse_language(" UK ") == "uk"
    assert parse_language("ru") == "ru"
    assert parse_language("en") == "en"
    with pytest.raises(CommandError, match="language_usage"):
        parse_language("fr")


def test_decode_transfer(transfer_log: dict[str, object]) -> None:
    assert decode_transfer(transfer_log) == Transfer(
        TRANSACTION, 7, 42, TOKEN, SENDER, RECIPIENT, 1500000000000000000
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("removed", True),
        ("transactionHash", "0x1234"),
        ("address", "0xg00"),
        ("data", "0x"),
        ("logIndex", "7"),
        ("blockNumber", "-0x2"),
        ("topics", [TRANSFER_TOPIC] * 4),
        ("topics", [TRANSFER_TOPIC] * 3),
        ("topics", ["wrong"]),
    ],
)
def test_decode_ignores_non_erc20_and_malformed_logs(
    transfer_log: dict[str, object], key: str, value: object
) -> None:
    transfer_log[key] = value
    assert decode_transfer(transfer_log) is None


def test_usd_valuation_is_exact_and_includes_the_threshold() -> None:
    amount = token_amount(10**37 + 123, 18)
    assert amount == Decimal("10000000000000000000.000000000000000123")
    value = usd_value(amount, Decimal(2))
    assert value == Decimal("20000000000000000000.000000000000000246")
    assert meets_threshold(value, value)
    assert not meets_threshold(value, Decimal("20000000000000000000.000000000000000247"))
    assert meets_threshold(usd_value(token_amount(500000, 3), Decimal(2)), Decimal(1000))


def test_scan_bounds_and_backlog_limit() -> None:
    assert scan_bounds(10, 10) is None
    assert scan_bounds(10, 11) == (11, 11)
    assert scan_bounds(10, 1000) == (11, 510)
    assert not should_skip_backlog(100, 2100)
    assert should_skip_backlog(100, 2101)
