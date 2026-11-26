from collections.abc import Mapping, Sequence
from decimal import Decimal

from .domain import short_address
from .models import Language, TokenMetadata, Transfer, Watch


_LANGUAGE_COMMANDS = "/lang uk · /lang ru · /lang en"

TRANSLATIONS: dict[Language, dict[str, str]] = {
    "uk": {
        "start": (
            "Надсилаю сповіщення про перекази токенів у BNB Chain.\n\n"
            "/watch <адреса> [мітка] [мін_usd] — стежити за гаманцем. Типовий поріг — $1000.\n"
            "/unwatch <номер> — прибрати гаманець зі списку\n"
            "/list — показати гаманці\n"
            "/min <номер> <usd> — змінити поріг\n"
            "/lang [uk|ru|en] — показати або змінити мову\n"
            "/start — допомога"
        ),
        "watch_usage": "Використай /watch <адреса> [мітка] [мін_usd].",
        "invalid_address": "Введи адресу BNB Chain з префіксом 0x і 40 шістнадцятковими символами.",
        "invalid_label": "Мітка може містити до 64 символів.",
        "invalid_usd": "Введи додатне число в USD. Для дробової частини підійде крапка або кома.",
        "invalid_watch_id": "Введи номер гаманця з /list.",
        "min_usage": "Використай /min <номер> <usd>.",
        "language_usage": f"Обери мову однією з команд.\n{_LANGUAGE_COMMANDS}",
        "language_current": f"Поточна мова — українська.\n{_LANGUAGE_COMMANDS}",
        "language_changed": "Мову змінено на українську.",
        "watch_added": "Гаманець #{id} додано до списку.",
        "watch_existing": "Ти вже стежиш за цим гаманцем під номером #{id}.",
        "watch_limit": "Можна стежити за {limit} гаманцями. Щоб звільнити місце, використай /unwatch.",
        "watch_removed": "Гаманець #{id} прибрано зі списку.",
        "watch_missing": "У твоєму списку немає гаманця #{id}.",
        "minimum_changed": "Поріг для гаманця #{id} змінено на ${usd}.",
        "list_title": "Твої гаманці",
        "list_more": "Твої гаманці · продовження",
        "list_empty": "Список поки порожній. Додай гаманець через /watch.",
        "list_entry": "#{id} · {label}\n{address}\nПоріг · ${usd}",
        "sent": "надіслав",
        "received": "отримав",
        "deposit": "{exchange} (депозит)",
        "transfer_alert": "{label} · {direction}\n{amount} {symbol} · ${usd}\n{counterparty}\n{url}",
    },
    "ru": {
        "start": (
            "Присылаю уведомления о переводах токенов в BNB Chain.\n\n"
            "/watch <адрес> [метка] [мин_usd] — следить за кошельком. Порог по умолчанию $1000.\n"
            "/unwatch <номер> — убрать кошелёк из списка\n"
            "/list — показать кошельки\n"
            "/min <номер> <usd> — изменить порог\n"
            "/lang [uk|ru|en] — показать или изменить язык\n"
            "/start — помощь"
        ),
        "watch_usage": "Используй /watch <адрес> [метка] [мин_usd].",
        "invalid_address": "Введи адрес BNB Chain с префиксом 0x и 40 шестнадцатеричными символами.",
        "invalid_label": "Метка может содержать до 64 символов.",
        "invalid_usd": "Введи положительное число в USD. Дробную часть можно отделить точкой или запятой.",
        "invalid_watch_id": "Введи номер кошелька из /list.",
        "min_usage": "Используй /min <номер> <usd>.",
        "language_usage": f"Выбери язык одной из команд.\n{_LANGUAGE_COMMANDS}",
        "language_current": f"Текущий язык — русский.\n{_LANGUAGE_COMMANDS}",
        "language_changed": "Язык изменён на русский.",
        "watch_added": "Кошелёк #{id} добавлен в список.",
        "watch_existing": "Ты уже следишь за этим кошельком под номером #{id}.",
        "watch_limit": "Можно следить за {limit} кошельками. Чтобы освободить место, используй /unwatch.",
        "watch_removed": "Кошелёк #{id} убран из списка.",
        "watch_missing": "В твоём списке нет кошелька #{id}.",
        "minimum_changed": "Порог для кошелька #{id} изменён на ${usd}.",
        "list_title": "Твои кошельки",
        "list_more": "Твои кошельки · продолжение",
        "list_empty": "Список пока пуст. Добавь кошелёк через /watch.",
        "list_entry": "#{id} · {label}\n{address}\nПорог · ${usd}",
        "sent": "отправил",
        "received": "получил",
        "deposit": "{exchange} (депозит)",
        "transfer_alert": "{label} · {direction}\n{amount} {symbol} · ${usd}\n{counterparty}\n{url}",
    },
    "en": {
        "start": (
            "I send alerts for token transfers on BNB Chain.\n\n"
            "/watch <address> [label] [min_usd] — watch a wallet. The default threshold is $1000.\n"
            "/unwatch <number> — remove a wallet\n"
            "/list — show your wallets\n"
            "/min <number> <usd> — change the USD threshold\n"
            "/lang [uk|ru|en] — show or change your language\n"
            "/start — show help"
        ),
        "watch_usage": "Use /watch <address> [label] [min_usd].",
        "invalid_address": "Enter a BNB Chain address with a 0x prefix and 40 hexadecimal characters.",
        "invalid_label": "A label can contain up to 64 characters.",
        "invalid_usd": "Enter a positive USD amount. Use a dot or a comma as the decimal separator.",
        "invalid_watch_id": "Enter a wallet number from /list.",
        "min_usage": "Use /min <number> <usd>.",
        "language_usage": f"Choose a language with one of these commands.\n{_LANGUAGE_COMMANDS}",
        "language_current": f"Your current language is English.\n{_LANGUAGE_COMMANDS}",
        "language_changed": "Your language is now English.",
        "watch_added": "Wallet #{id} added to your watchlist.",
        "watch_existing": "You already watch this wallet as #{id}.",
        "watch_limit": "You can watch up to {limit} wallets. Use /unwatch to free up a slot.",
        "watch_removed": "Wallet #{id} removed from your watchlist.",
        "watch_missing": "Wallet #{id} is missing from your watchlist.",
        "minimum_changed": "Wallet #{id} now has a threshold of ${usd}.",
        "list_title": "Your watched wallets",
        "list_more": "Your watched wallets · continued",
        "list_empty": "Your watchlist is empty. Add a wallet with /watch.",
        "list_entry": "#{id} · {label}\n{address}\nThreshold · ${usd}",
        "sent": "sent",
        "received": "received",
        "deposit": "{exchange} (deposit)",
        "transfer_alert": "{label} · {direction}\n{amount} {symbol} · ${usd}\n{counterparty}\n{url}",
    },
}


def translate(lang: Language, key: str, /, **values: str | int | Decimal) -> str:
    return TRANSLATIONS[lang][key].format(**values)


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def watch_list(lang: Language, watches: Sequence[Watch]) -> list[str]:
    if not watches:
        return [translate(lang, "list_empty")]
    pages = []
    page = translate(lang, "list_title")
    for watch in watches:
        entry = translate(
            lang,
            "list_entry",
            id=watch.id,
            label=watch.label,
            address=watch.address,
            usd=_decimal_text(watch.minimum_usd),
        )
        combined = f"{page}\n\n{entry}"
        if len(combined.encode("utf-16-le")) // 2 > 3500:
            pages.append(page)
            page = f"{translate(lang, 'list_more')}\n\n{entry}"
        else:
            page = combined
    return [*pages, page]


def alert_message(
    watch: Watch,
    transfer: Transfer,
    metadata: TokenMetadata,
    amount: Decimal,
    usd: Decimal,
    exchange_labels: Mapping[str, str],
) -> str:
    lang = watch.lang
    sent = transfer.sender == watch.address
    counterparty = transfer.recipient if sent else transfer.sender
    exchange = exchange_labels.get(counterparty)
    if exchange:
        counterparty_text = translate(lang, "deposit", exchange=exchange) if sent else exchange
    else:
        counterparty_text = short_address(counterparty)

    return translate(
        lang,
        "transfer_alert",
        label=watch.label,
        direction=translate(lang, "sent" if sent else "received"),
        amount=_decimal_text(amount),
        symbol=metadata.symbol,
        usd=f"{usd:,.2f}",
        counterparty=f"{'→' if sent else '←'} {counterparty_text}",
        url=f"https://bscscan.com/tx/{transfer.tx_hash}",
    )
