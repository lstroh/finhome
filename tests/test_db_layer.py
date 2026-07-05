"""Unit tests for db_layer category overrides — stdlib unittest only."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from categoriser import categorise
from db_layer import (
    clear_category_budget,
    get_category_budgets,
    get_category_override,
    make_hash,
    normalize_description,
    resolve_category,
    set_category_budget,
    set_category_override,
    update_category_for_description,
)


def make_test_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE transactions (
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
        CREATE TABLE category_overrides (
            description_key TEXT PRIMARY KEY,
            category TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE category_budgets (
            category TEXT PRIMARY KEY,
            monthly_amount REAL NOT NULL
        )
    """)
    return conn


def insert_row(conn, date, description, amount, category, account="test"):
    h = make_hash(date, description, amount, account)
    conn.execute(
        """INSERT INTO transactions
           (date, description, amount, source_account, category, balance, raw_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (date, description, amount, account, category, None, h),
    )


class TestNormalizeDescription(unittest.TestCase):
    def test_strip_and_upper(self):
        self.assertEqual(normalize_description("  Tesco Store  "), "TESCO STORE")


class TestCategoryOverrides(unittest.TestCase):
    def test_update_all_matching_descriptions(self):
        conn = make_test_conn()
        insert_row(conn, "2026-04-01", "TESCO", -10, "Uncategorised")
        insert_row(conn, "2026-05-01", "  tesco ", -20, "Uncategorised", "credit_card")
        insert_row(conn, "2026-05-02", "NETFLIX", -9.99, "Subscriptions")
        conn.commit()

        updated = update_category_for_description(conn, "TESCO", "Groceries")
        self.assertEqual(updated, 2)

        rows = conn.execute(
            "SELECT description, category FROM transactions ORDER BY id"
        ).fetchall()
        self.assertEqual(rows[0], ("TESCO", "Groceries"))
        self.assertEqual(rows[1], ("  tesco ", "Groceries"))
        self.assertEqual(rows[2], ("NETFLIX", "Subscriptions"))
        self.assertEqual(get_category_override(conn, "TESCO"), "Groceries")

    def test_resolve_category_uses_override(self):
        conn = make_test_conn()
        set_category_override(conn, "MY MERCHANT", "Shopping")
        conn.commit()
        self.assertEqual(resolve_category(conn, "my merchant", categorise), "Shopping")
        self.assertEqual(resolve_category(conn, "UNKNOWN SHOP", categorise), "Uncategorised")


class TestCategoryBudgets(unittest.TestCase):
    def test_set_get_and_clear(self):
        conn = make_test_conn()
        set_category_budget(conn, "Groceries", -400)
        budgets = get_category_budgets(conn)
        self.assertAlmostEqual(budgets["Groceries"], -400)

        set_category_budget(conn, "Groceries", -350)
        self.assertAlmostEqual(get_category_budgets(conn)["Groceries"], -350)

        clear_category_budget(conn, "Groceries")
        self.assertEqual(get_category_budgets(conn), {})


if __name__ == "__main__":
    unittest.main()
