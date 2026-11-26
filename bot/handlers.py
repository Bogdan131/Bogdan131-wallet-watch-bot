import asyncio

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from . import texts
from .domain import (
    CommandError,
    default_language,
    parse_language,
    parse_minimum,
    parse_watch,
    parse_watch_id,
)
from .models import Language
from .storage import MAX_WATCHES, WalletStorage


async def _language(message: Message, storage: WalletStorage) -> Language | None:
    user = message.from_user
    if user is None:
        return None
    return await asyncio.to_thread(
        storage.ensure_language, user.id, default_language(user.language_code)
    )


async def start(message: Message, storage: WalletStorage) -> None:
    lang = await _language(message, storage)
    if lang is not None:
        await message.answer(texts.translate(lang, "start"))


async def watch(message: Message, command: CommandObject, storage: WalletStorage) -> None:
    user = message.from_user
    lang = await _language(message, storage)
    if user is None or lang is None:
        return

    try:
        spec = parse_watch(command.args)
    except CommandError as error:
        await message.answer(texts.translate(lang, error.key))
        return

    watch_id, status = await asyncio.to_thread(storage.add_watch, user.id, spec)
    if status == "limit":
        await message.answer(texts.translate(lang, "watch_limit", limit=MAX_WATCHES))
    else:
        await message.answer(texts.translate(lang, f"watch_{status}", id=watch_id))


async def unwatch(message: Message, command: CommandObject, storage: WalletStorage) -> None:
    user = message.from_user
    lang = await _language(message, storage)
    if user is None or lang is None:
        return

    try:
        watch_id = parse_watch_id(command.args)
    except CommandError as error:
        await message.answer(texts.translate(lang, error.key))
        return

    removed = await asyncio.to_thread(storage.delete_watch, user.id, watch_id)
    key = "watch_removed" if removed else "watch_missing"
    await message.answer(texts.translate(lang, key, id=watch_id))


async def list_watches(message: Message, storage: WalletStorage) -> None:
    user = message.from_user
    lang = await _language(message, storage)
    if user is None or lang is None:
        return

    watches = await asyncio.to_thread(storage.list_watches, user.id)
    for page in texts.watch_list(lang, watches):
        await message.answer(page)


async def minimum(message: Message, command: CommandObject, storage: WalletStorage) -> None:
    user = message.from_user
    lang = await _language(message, storage)
    if user is None or lang is None:
        return

    try:
        watch_id, usd = parse_minimum(command.args)
    except CommandError as error:
        await message.answer(texts.translate(lang, error.key))
        return

    updated = await asyncio.to_thread(storage.set_minimum, user.id, watch_id, usd)
    if updated:
        await message.answer(texts.translate(lang, "minimum_changed", id=watch_id, usd=usd))
    else:
        await message.answer(texts.translate(lang, "watch_missing", id=watch_id))


async def change_language(message: Message, command: CommandObject, storage: WalletStorage) -> None:
    user = message.from_user
    lang = await _language(message, storage)
    if user is None or lang is None:
        return

    try:
        requested = parse_language(command.args)
    except CommandError as error:
        await message.answer(texts.translate(lang, error.key))
        return
    if requested is None:
        await message.answer(texts.translate(lang, "language_current"))
        return

    await asyncio.to_thread(storage.set_language, user.id, requested)
    await message.answer(texts.translate(requested, "language_changed"))


def build_router() -> Router:
    router = Router()
    router.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user)
    router.message.register(start, CommandStart())
    router.message.register(watch, Command("watch"))
    router.message.register(unwatch, Command("unwatch"))
    router.message.register(list_watches, Command("list"))
    router.message.register(minimum, Command("min"))
    router.message.register(change_language, Command("lang"))
    return router
