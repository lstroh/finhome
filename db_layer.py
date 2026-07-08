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
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "finance.db"
MAX_BUDGET_AMOUNT = 100_000


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_budgets (
            category TEXT PRIMARY KEY,
            monthly_amount REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS import_runs (
            source_account TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_file TEXT NOT NULL,
            last_import_at TEXT NOT NULL,
            last_rows_inserted INTEGER NOT NULL DEFAULT 0,
            last_rows_skipped INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def source_type_from_account(source_account: str) -> str:
    """Derive import source type from source_account naming convention."""
    if source_account.startswith("credit_card_"):
        return "credit_card"
    return "bank"


def record_import_run(conn, source_account, source_type, source_file, inserted, skipped):
    """Upsert metadata for the most recent import of a source file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        """INSERT INTO import_runs
           (source_account, source_type, source_file, last_import_at,
            last_rows_inserted, last_rows_skipped)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_account) DO UPDATE SET
             source_type = excluded.source_type,
             source_file = excluded.source_file,
             last_import_at = excluded.last_import_at,
             last_rows_inserted = excluded.last_rows_inserted,
             last_rows_skipped = excluded.last_rows_skipped""",
        (source_account, source_type, source_file, now, inserted, skipped),
    )
    conn.commit()


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


def get_category_budgets(conn):
    """Return {category: monthly_amount} for all set budgets (amounts are negative)."""
    rows = conn.execute(
        "SELECT category, monthly_amount FROM category_budgets ORDER BY category"
    ).fetchall()
    return {category: amount for category, amount in rows}


def set_category_budget(conn, category: str, monthly_amount: float):
    """Upsert a monthly spending budget (negative amount)."""
    conn.execute(
        """INSERT INTO category_budgets (category, monthly_amount)
           VALUES (?, ?)
           ON CONFLICT(category) DO UPDATE SET monthly_amount = excluded.monthly_amount""",
        (category, monthly_amount),
    )
    conn.commit()


def clear_category_budget(conn, category: str):
    conn.execute("DELETE FROM category_budgets WHERE category = ?", (category,))
    conn.commit()


def delete_transactions(conn, transaction_ids: list[int]) -> int:
    """Delete transactions by id. Returns number of rows removed."""
    if not transaction_ids:
        return 0
    placeholders = ",".join("?" * len(transaction_ids))
    cur = conn.execute(
        f"DELETE FROM transactions WHERE id IN ({placeholders})",
        transaction_ids,
    )
    conn.commit()
    return cur.rowcount
