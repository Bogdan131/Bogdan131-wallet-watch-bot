import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from bot.models import TokenMetadata, Watch, WatchSpec
from bot.storage import MAX_WATCHES, WalletStorage


def address(number: int) -> str:
    return f"0x{number:040x}"


def test_startup_migration_preserves_existing_watches(tmp_path: Path) -> None:
    path = tmp_path / "wallets.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(
            """
            CREATE TABLE users (user_id INTEGER PRIMARY KEY, lang TEXT NOT NULL);
            CREATE TABLE watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(user_id),
                address TEXT NOT NULL,
                label TEXT NOT NULL,
                minimum_usd TEXT NOT NULL,
                UNIQUE (user_id, address)
            );
            """
        )
        db.execute("INSERT INTO users VALUES (42, 'uk')")
        db.execute("INSERT INTO watches VALUES (7, 42, ?, 'Treasury', '1000.25')", (address(1),))

    storage = WalletStorage(path)
    storage.initialize()
    assert storage.ensure_language(42, "en") == "uk"
    assert storage.list_watches(42) == [Watch(7, 42, address(1), "Treasury", Decimal("1000.25"), "uk")]
    assert storage.get_checkpoint() is None
    storage.set_checkpoint(2500)
    assert storage.claim_delivery(42, "0x" + "ab" * 32, 1)

    reopened = WalletStorage(path)
    reopened.initialize()
    assert reopened.get_checkpoint() == 2500
    assert reopened.list_watches() == storage.list_watches()
    assert not reopened.claim_delivery(42, "0x" + "ab" * 32, 1)


def test_wallet_commands_are_scoped_to_the_owner(tmp_path: Path) -> None:
    storage = WalletStorage(tmp_path / "wallets.sqlite3")
    storage.initialize()
    storage.ensure_language(1, "uk")
    storage.ensure_language(2, "en")
    spec = WatchSpec(address(42), "Exchange", Decimal("1000"))

    watch_id, status = storage.add_watch(1, spec)
    assert status == "added"
    duplicate = WatchSpec(spec.address.upper(), "New label", Decimal(2000))
    assert storage.add_watch(1, duplicate) == (watch_id, "existing")
    assert storage.add_watch(2, spec)[1] == "added"
    assert not storage.delete_watch(2, watch_id)
    assert not storage.set_minimum(2, watch_id, Decimal(5))

    assert storage.set_minimum(1, watch_id, Decimal("1000.15"))
    storage.set_language(1, "ru")
    assert storage.ensure_language(1, "en") == "ru"
    assert storage.list_watches(1) == [Watch(watch_id, 1, spec.address, spec.label, Decimal("1000.15"), "ru")]
    assert storage.delete_watch(1, watch_id)
    assert storage.list_watches(1) == []
    assert len(storage.list_watches(2)) == 1


def test_wallet_limit_is_atomic(tmp_path: Path) -> None:
    storage = WalletStorage(tmp_path / "wallets.sqlite3")
    storage.initialize()
    storage.ensure_language(1, "en")

    def add_wallet(number: int) -> str:
        return storage.add_watch(1, WatchSpec(address(number), "", Decimal(1000)))[1]

    for number in range(1, MAX_WATCHES):
        assert add_wallet(number) == "added"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(add_wallet, (MAX_WATCHES, MAX_WATCHES + 1)))
    assert sorted(results) == ["added", "limit"]
    assert len(storage.list_watches(1)) == MAX_WATCHES
    assert add_wallet(1) == "existing"


def test_checkpoint_and_token_cache_persist(tmp_path: Path) -> None:
    path = tmp_path / "wallets.sqlite3"
    storage = WalletStorage(path)
    storage.initialize()
    assert storage.get_checkpoint() is None
    storage.set_checkpoint(1000)
    storage.set_checkpoint(999)
    storage.set_checkpoint(1020)

    token = address(99)
    assert storage.get_token(token) is None
    storage.save_token(token, TokenMetadata(18, "ABC"))
    reopened = WalletStorage(path)
    reopened.initialize()
    assert reopened.get_checkpoint() == 1020
    assert reopened.get_token(token.upper()) == TokenMetadata(18, "ABC")


def test_deliveries_deduplicate_by_user_transaction_and_log(tmp_path: Path) -> None:
    storage = WalletStorage(tmp_path / "wallets.sqlite3")
    storage.initialize()
    storage.ensure_language(1, "en")
    storage.ensure_language(2, "en")
    tx_hash = "0x" + "ab" * 32

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: storage.claim_delivery(1, tx_hash, 5), (0, 1)))
    assert sorted(results) == [False, True]
    assert not storage.claim_delivery(1, tx_hash.upper(), 5)
    assert storage.claim_delivery(2, tx_hash, 5)
    assert storage.claim_delivery(1, tx_hash, 6)

    storage.release_delivery(1, tx_hash, 5)
    assert storage.claim_delivery(1, tx_hash, 5)
    assert not storage.claim_delivery(2, tx_hash, 5)
