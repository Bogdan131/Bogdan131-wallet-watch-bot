import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal

from .models import Language, TokenMetadata, Watch, WatchSpec


MAX_WATCHES = 30
AddStatus = Literal["added", "existing", "limit"]


class WalletStorage:
    """Short transactions using a fresh connection in each worker thread."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            yield db

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                BEGIN IMMEDIATE;

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    lang TEXT NOT NULL CHECK (lang IN ('uk', 'ru', 'en'))
                );

                CREATE TABLE IF NOT EXISTS watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(user_id),
                    address TEXT NOT NULL COLLATE NOCASE,
                    label TEXT NOT NULL,
                    minimum_usd TEXT NOT NULL,
                    UNIQUE (user_id, address)
                );

                CREATE TABLE IF NOT EXISTS scan_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    block_number INTEGER NOT NULL CHECK (block_number >= 0)
                );

                CREATE TABLE IF NOT EXISTS token_metadata (
                    address TEXT PRIMARY KEY NOT NULL,
                    decimals INTEGER NOT NULL CHECK (decimals BETWEEN 0 AND 255),
                    symbol TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    user_id INTEGER NOT NULL REFERENCES users(user_id),
                    tx_hash TEXT NOT NULL,
                    log_index INTEGER NOT NULL CHECK (log_index >= 0),
                    PRIMARY KEY (user_id, tx_hash, log_index)
                ) WITHOUT ROWID;

                COMMIT;
                """
            )

    def ensure_language(self, user_id: int, default: Language) -> Language:
        with self._connect() as db:
            db.execute(
                "INSERT INTO users (user_id, lang) VALUES (?, ?) ON CONFLICT (user_id) DO NOTHING",
                (user_id, default),
            )
            row = db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row["lang"]

    def set_language(self, user_id: int, lang: Language) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO users (user_id, lang) VALUES (?, ?)
                ON CONFLICT (user_id) DO UPDATE SET lang = excluded.lang
                """,
                (user_id, lang),
            )

    def add_watch(self, user_id: int, spec: WatchSpec) -> tuple[int, AddStatus]:
        address = spec.address.lower()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM watches WHERE user_id = ? AND address = ?",
                (user_id, address),
            ).fetchone()
            if existing is not None:
                return existing["id"], "existing"

            count = db.execute("SELECT COUNT(*) FROM watches WHERE user_id = ?", (user_id,)).fetchone()
            if count[0] >= MAX_WATCHES:
                return 0, "limit"

            inserted = db.execute(
                """
                INSERT INTO watches (user_id, address, label, minimum_usd)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, address, spec.label, str(spec.minimum_usd)),
            )
            if inserted.lastrowid is None:
                raise RuntimeError("Could not save wallet watch.")
            return inserted.lastrowid, "added"

    def list_watches(self, user_id: int | None = None) -> list[Watch]:
        query = """
            SELECT watches.*, users.lang
            FROM watches JOIN users USING (user_id)
        """
        params: tuple[int, ...] = ()
        if user_id is not None:
            query += " WHERE watches.user_id = ?"
            params = (user_id,)
        query += " ORDER BY watches.id"
        with self._connect() as db:
            return [
                Watch(
                    id=row["id"],
                    user_id=row["user_id"],
                    address=row["address"],
                    label=row["label"],
                    minimum_usd=Decimal(row["minimum_usd"]),
                    lang=row["lang"],
                )
                for row in db.execute(query, params)
            ]

    def delete_watch(self, user_id: int, watch_id: int) -> bool:
        with self._connect() as db:
            deleted = db.execute("DELETE FROM watches WHERE user_id = ? AND id = ?", (user_id, watch_id))
            return deleted.rowcount == 1

    def delete_user_watches(self, user_id: int) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM watches WHERE user_id = ?", (user_id,)).rowcount

    def set_minimum(self, user_id: int, watch_id: int, minimum_usd: Decimal) -> bool:
        with self._connect() as db:
            updated = db.execute(
                "UPDATE watches SET minimum_usd = ? WHERE user_id = ? AND id = ?",
                (str(minimum_usd), user_id, watch_id),
            )
            return updated.rowcount == 1

    def get_checkpoint(self) -> int | None:
        with self._connect() as db:
            row = db.execute("SELECT block_number FROM scan_state WHERE id = 1").fetchone()
            return row["block_number"] if row is not None else None

    def set_checkpoint(self, block_number: int) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO scan_state (id, block_number) VALUES (1, ?)
                ON CONFLICT (id) DO UPDATE SET block_number = excluded.block_number
                WHERE excluded.block_number > scan_state.block_number
                """,
                (block_number,),
            )

    def get_token(self, token: str) -> TokenMetadata | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT decimals, symbol FROM token_metadata WHERE address = ?", (token.lower(),)
            ).fetchone()
            if row is None:
                return None
            return TokenMetadata(decimals=row["decimals"], symbol=row["symbol"])

    def save_token(self, token: str, metadata: TokenMetadata) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO token_metadata (address, decimals, symbol) VALUES (?, ?, ?)
                ON CONFLICT (address) DO UPDATE SET
                    decimals = excluded.decimals, symbol = excluded.symbol
                """,
                (token.lower(), metadata.decimals, metadata.symbol),
            )

    def claim_delivery(self, user_id: int, tx_hash: str, log_index: int) -> bool:
        with self._connect() as db:
            inserted = db.execute(
                """
                INSERT INTO deliveries (user_id, tx_hash, log_index) VALUES (?, ?, ?)
                ON CONFLICT (user_id, tx_hash, log_index) DO NOTHING
                """,
                (user_id, tx_hash.lower(), log_index),
            )
            return inserted.rowcount == 1

    def release_delivery(self, user_id: int, tx_hash: str, log_index: int) -> None:
        """Release a claim only when Telegram explicitly declined to send."""
        with self._connect() as db:
            db.execute(
                "DELETE FROM deliveries WHERE user_id = ? AND tx_hash = ? AND log_index = ?",
                (user_id, tx_hash.lower(), log_index),
            )
