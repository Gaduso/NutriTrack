from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from config import settings

# Allowed meal categories (kept in sync with the API layer / frontend).
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")


def _dsn() -> str:
    url = settings.DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL ist nicht gesetzt. Bitte die PostgreSQL-Verbindung als "
            "Umgebungsvariable konfigurieren."
        )
    # SQLAlchemy-/Render-style "postgres://" -> psycopg expects "postgresql://".
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@contextmanager
def get_connection():
    """Yield a PostgreSQL connection; commit on success, rollback+close otherwise."""
    conn = psycopg.connect(_dsn(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if missing and apply additive migrations (idempotent)."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                kcal_goal     INTEGER NOT NULL DEFAULT 2200,
                protein_goal  DOUBLE PRECISION NOT NULL DEFAULT 150,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id        SERIAL PRIMARY KEY,
                user_id   INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
                raw_text  TEXT,
                name      TEXT NOT NULL,
                amount    TEXT,
                kcal      INTEGER NOT NULL DEFAULT 0,
                protein   DOUBLE PRECISION NOT NULL DEFAULT 0,
                meal_type TEXT NOT NULL DEFAULT 'snack'
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meals_user_ts ON meals (user_id, timestamp);"
        )
        # Friend graph: one row per relationship, status pending/accepted.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS friendships (
                id           SERIAL PRIMARY KEY,
                requester_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                addressee_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                status       TEXT NOT NULL DEFAULT 'pending',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (requester_id, addressee_id)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships (addressee_id, status);"
        )

        # --- Additive migrations for pre-existing tables ---
        conn.execute(
            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS kcal_goal INTEGER NOT NULL DEFAULT {settings.DAILY_KCAL_GOAL};"
        )
        conn.execute(
            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS protein_goal DOUBLE PRECISION NOT NULL DEFAULT {settings.DAILY_PROTEIN_GOAL};"
        )
        conn.execute(
            "ALTER TABLE meals ADD COLUMN IF NOT EXISTS meal_type TEXT NOT NULL DEFAULT 'snack';"
        )
