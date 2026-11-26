from decimal import Decimal
from string import Formatter

import pytest

from bot.models import Language, TokenMetadata, Transfer, Watch
from bot.texts import TRANSLATIONS, alert_message, watch_list


ADDRESS = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
TOKEN = "0x" + "11" * 20
TRANSACTION = "0x" + "ff" * 32


def test_translation_keys_and_placeholders_match() -> None:
    reference = TRANSLATIONS["en"]
    formatter = Formatter()
    assert set(TRANSLATIONS) == {"uk", "ru", "en"}
    for language, messages in TRANSLATIONS.items():
        assert messages.keys() == reference.keys()
        for key, message in messages.items():
            fields = {name for _, name, _, _ in formatter.parse(message) if name is not None}
            expected = {name for _, name, _, _ in formatter.parse(reference[key]) if name is not None}
            assert fields == expected, (language, key)


@pytest.mark.parametrize(
    ("lang", "direction", "deposit"),
    [("uk", "надіслав", "депозит"), ("ru", "отправил", "депозит"), ("en", "sent", "deposit")],
)
def test_outgoing_alert_includes_exchange_and_usd(
    lang: Language, direction: str, deposit: str
) -> None:
    watch = Watch(11, 100, ADDRESS, "Main", Decimal(1000), lang)
    transfer = Transfer(TRANSACTION, 7, 42, TOKEN, ADDRESS, OTHER, 1500)
    message = alert_message(
        watch, transfer, TokenMetadata(2, "TOKEN"), Decimal("15.000"), Decimal(1200), {OTHER: "Binance"}
    )
    assert message.splitlines() == [
        f"Main · {direction}",
        "15 TOKEN · $1,200.00",
        f"→ Binance ({deposit})",
        f"https://bscscan.com/tx/{TRANSACTION}",
    ]


def test_incoming_alert_shortens_unknown_address() -> None:
    watch = Watch(11, 100, ADDRESS, "Main", Decimal(1000), "en")
    transfer = Transfer(TRANSACTION, 7, 42, TOKEN, OTHER, ADDRESS, 1)
    message = alert_message(watch, transfer, TokenMetadata(0, "TOKEN"), Decimal(1), Decimal(1200), {})
    assert message.splitlines()[0] == "Main · received"
    assert "← 0xcdcd…cdcd" in message


@pytest.mark.parametrize(
    ("lang", "title", "threshold"),
    [("uk", "Твої гаманці", "Поріг"), ("ru", "Твои кошельки", "Порог"),
     ("en", "Your watched wallets", "Threshold")],
)
def test_watch_list_is_localized(lang: Language, title: str, threshold: str) -> None:
    watch = Watch(11, 100, ADDRESS, "Main", Decimal("500.25"), lang)
    assert watch_list(lang, [watch]) == [f"{title}\n\n#11 · Main\n{ADDRESS}\n{threshold} · $500.25"]


def test_watch_list_splits_long_telegram_messages() -> None:
    watches = [Watch(i, 100, ADDRESS, "😀" * 64, Decimal("1" * 64), "en") for i in range(1, 31)]
    pages = watch_list("en", watches)
    assert len(pages) > 1
    assert sum(page.count(ADDRESS) for page in pages) == 30
    assert all(len(page.encode("utf-16-le")) // 2 <= 3500 for page in pages)
