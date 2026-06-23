import json
import os
import sqlite3
from contextlib import contextmanager

from config import settings


def _ensure_parent_dir(db_path: str) -> None:
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


@contextmanager
def get_connection():
    """Yield a SQLite connection with row access by column name."""
    _ensure_parent_dir(settings.DATABASE_URL)
    conn = sqlite3.connect(settings.DATABASE_URL)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _columns(conn, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def init_db() -> None:
    """Create tables (one row per food item) and migrate older schemas in place."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                kcal_goal     INTEGER NOT NULL DEFAULT 2200,
                protein_goal  REAL    NOT NULL DEFAULT 150,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # --- Migration: add goal columns to pre-existing users tables ---
        ucols = _columns(conn, "users")
        if "kcal_goal" not in ucols:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN kcal_goal INTEGER NOT NULL DEFAULT {settings.DAILY_KCAL_GOAL}"
            )
        if "protein_goal" not in ucols:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN protein_goal REAL NOT NULL DEFAULT {settings.DAILY_PROTEIN_GOAL}"
            )

        # --- meals: one row per food item ---
        if _table_exists(conn, "meals") and "name" not in _columns(conn, "meals"):
            _migrate_meals_to_items(conn)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                raw_text  TEXT,
                name      TEXT NOT NULL,
                amount    TEXT,
                kcal      INTEGER NOT NULL DEFAULT 0,
                protein   REAL    NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meals_user_ts ON meals (user_id, timestamp);"
        )


def _migrate_meals_to_items(conn) -> None:
    """Convert the old grouped meals table (json_data) into one row per item."""
    old_rows = conn.execute(
        "SELECT user_id, timestamp, raw_text, json_data FROM meals"
    ).fetchall()
    conn.execute("ALTER TABLE meals RENAME TO meals_legacy")
    conn.execute(
        """
        CREATE TABLE meals (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            raw_text  TEXT,
            name      TEXT NOT NULL,
            amount    TEXT,
            kcal      INTEGER NOT NULL DEFAULT 0,
            protein   REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
        """
    )
    for r in old_rows:
        try:
            items = json.loads(r["json_data"]).get("items", [])
        except (TypeError, json.JSONDecodeError):
            items = []
        for it in items:
            conn.execute(
                """
                INSERT INTO meals (user_id, timestamp, raw_text, name, amount, kcal, protein)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["user_id"],
                    r["timestamp"],
                    r["raw_text"],
                    str(it.get("name", "Unbekannt")),
                    str(it.get("amount", "")),
                    int(it.get("kcal", 0) or 0),
                    float(it.get("protein", 0) or 0),
                ),
            )
    conn.execute("DROP TABLE meals_legacy")
