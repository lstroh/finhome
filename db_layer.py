"""
SQLite database layer.

The database is a single file: db/finance.db
Nothing here ever touches the network — everything stays on your machine.

Schema
------
transactions(
    id              -- unique row id
    date            -- ISO format YYYY-MM-DD
    description     -- raw description from the bank/card
    amount          -- signed float; negative = money out, positive = money in
    source_account  -- e.g. "current_account", "savings", "credit_card"
    category        -- assigned by the categoriser
    balance         -- running balance, if known (bank files only)
    raw_hash        -- hash of the row used to prevent duplicate imports
)
"""

import sqlite3
import hashlib
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "finance.db"


def normalize_description(description: str) -> str:
    """Stable key for matching merchant/description across imports and edits."""
    return description.strip().upper()


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            source_account TEXT NOT NULL,
            category TEXT NOT NULL,
            balance REAL,
            raw_hash TEXT UNIQUE NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_date ON transactions(date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_category ON transactions(category)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_overrides (
            description_key TEXT PRIMARY KEY,
            category TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def make_hash(date, description, amount, source_account):
    """
    Create a stable fingerprint for a transaction so re-running the
    importer on the same file never creates duplicate rows.
    """
    raw = f"{date}|{description.strip()}|{amount:.2f}|{source_account}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def insert_transaction(conn, date, description, amount, source_account,
                        category, balance=None):
    h = make_hash(date, description, amount, source_account)
    try:
        conn.execute(
            """INSERT INTO transactions
               (date, description, amount, source_account, category, balance, raw_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date, description, amount, source_account, category, balance, h)
        )
        return True  # inserted
    except sqlite3.IntegrityError:
        return False  # duplicate, skipped


def update_category(conn, transaction_id, new_category):
    conn.execute(
        "UPDATE transactions SET category = ? WHERE id = ?",
        (new_category, transaction_id)
    )
    conn.commit()


def get_category_override(conn, description: str):
    """Return manual category for this description, or None."""
    key = normalize_description(description)
    row = conn.execute(
        "SELECT category FROM category_overrides WHERE description_key = ?",
        (key,),
    ).fetchone()
    return row[0] if row else None


def set_category_override(conn, description: str, category: str):
    key = normalize_description(description)
    conn.execute(
        """INSERT INTO category_overrides (description_key, category)
           VALUES (?, ?)
           ON CONFLICT(description_key) DO UPDATE SET category = excluded.category""",
        (key, category),
    )


def get_transaction_by_id(conn, transaction_id: int):
    row = conn.execute(
        "SELECT id, date, description, amount, source_account, category, balance "
        "FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()
    return row


def update_category_for_description(conn, description: str, new_category: str) -> int:
    """
    Apply a manual category to all transactions with the same normalized
    description and persist the override for future imports/recategorisation.
    """
    key = normalize_description(description)
    cur = conn.execute(
        "UPDATE transactions SET category = ? WHERE UPPER(TRIM(description)) = ?",
        (new_category, key),
    )
    updated_count = cur.rowcount
    set_category_override(conn, description, new_category)
    conn.commit()
    return updated_count


def resolve_category(conn, description: str, categorise_fn):
    """
    Use a manual override when present, otherwise fall back to keyword rules.
    categorise_fn is typically categoriser.categorise.
    """
    override = get_category_override(conn, description)
    if override is not None:
        return override
    return categorise_fn(description)
