"""Unit tests for web_server.py — stdlib unittest only."""

import json
import sqlite3
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import db_layer
import web_server
from db_layer import make_hash


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, host, port


def _request(host, port, path, method="GET", body=None, headers=None):
    conn = HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    body_bytes = resp.read()
    content_type = resp.getheader("Content-Type")
    conn.close()
    return resp.status, content_type, body_bytes


def _get_json(host, port, path):
    status, content_type, body = _request(host, port, path)
    data = json.loads(body.decode()) if body else None
    return status, content_type, data


def _post_json(host, port, path, payload):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    status, content_type, body_bytes = _request(host, port, path, method="POST", body=body, headers=headers)
    data = json.loads(body_bytes.decode()) if body_bytes else None
    return status, content_type, data


def _create_db(db_path):
    conn = sqlite3.connect(db_path)
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
    conn.commit()
    conn.close()


def _insert_row(conn, date, description, amount, category, account="test"):
    h = make_hash(date, description, amount, account)
    conn.execute(
        """INSERT INTO transactions
           (date, description, amount, source_account, category, balance, raw_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (date, description, amount, account, category, None, h),
    )


class TestWebServerBind(unittest.TestCase):
    def test_bind_address_is_localhost(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.DashboardHandler)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()


class TestWebServerStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.host, cls.port = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_index_returns_html(self):
        status, content_type, body = _request(self.host, self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"Finance Tracker", body)

    def test_static_css(self):
        status, content_type, body = _request(self.host, self.port, "/static/style.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", content_type)
        self.assertGreater(len(body), 0)

    def test_path_traversal_rejected(self):
        status, content_type, data = _get_json(
            self.host, self.port, "/static/../../db/finance.db"
        )
        self.assertEqual(status, 404)
        self.assertEqual(data, {"error": "not found"})
        self.assertIn("application/json", content_type)

    def test_unknown_route_404(self):
        status, _, data = _get_json(self.host, self.port, "/api/nope")
        self.assertEqual(status, 404)
        self.assertEqual(data, {"error": "not found"})


class TestWebServerApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.host, cls.port = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_missing_db_returns_503(self):
        with patch.object(web_server, "DB_PATH") as mock_path:
            mock_path.exists.return_value = False
            status, _, data = _get_json(self.host, self.port, "/api/summary")
        self.assertEqual(status, 503)
        self.assertIn("Database not found", data["error"])

    def test_invalid_month_returns_400(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(self.host, self.port, "/api/month?month=bad")
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "month must be YYYY-MM"})

    def test_empty_db_summary(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(self.host, self.port, "/api/summary")
        self.assertEqual(status, 200)
        self.assertTrue(data["empty"])
        self.assertIn("message", data)

    def test_summary_with_data(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)
        conn = sqlite3.connect(db_path)
        _insert_row(conn, "2026-05-01", "TESCO", -100, "Groceries")
        _insert_row(conn, "2026-05-15", "SALARY", 3000, "Income")
        conn.commit()
        conn.close()

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(self.host, self.port, "/api/summary")
            months_status, _, months = _get_json(self.host, self.port, "/api/months")
            month_status, _, month = _get_json(
                self.host, self.port, "/api/month?month=2026-05"
            )

        self.assertEqual(status, 200)
        self.assertFalse(data["empty"])
        self.assertEqual(data["latest_month"], "2026-05")
        self.assertEqual(data["month"]["total_spend"], -100)

        self.assertEqual(months_status, 200)
        self.assertEqual(months, ["2026-05"])

        self.assertEqual(month_status, 200)
        self.assertEqual(month["income"], 3000)

    def test_transactions_invalid_month_returns_400(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(
                self.host, self.port, "/api/transactions?month=bad&category=Groceries"
            )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "month must be YYYY-MM"})

    def test_transactions_all_month(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)
        conn = sqlite3.connect(db_path)
        _insert_row(conn, "2026-05-03", "TESCO", -45.67, "Groceries", "credit_card")
        _insert_row(conn, "2026-05-12", "SALARY", 2500.00, "Income", "current_account")
        _insert_row(conn, "2026-05-15", "NETFLIX", -9.99, "Subscriptions")
        conn.commit()
        conn.close()

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(
                self.host, self.port, "/api/transactions?month=2026-05"
            )
        self.assertEqual(status, 200)
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["total"], 2500.00 - 45.67 - 9.99)
        amounts = [t["amount"] for t in data["transactions"]]
        self.assertIn(2500.00, amounts)
        self.assertIn(-45.67, amounts)

    def test_transactions_with_data(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)
        conn = sqlite3.connect(db_path)
        _insert_row(conn, "2026-05-03", "TESCO", -45.67, "Groceries", "credit_card")
        _insert_row(conn, "2026-05-10", "SAINSBURY", -30.00, "Groceries", "credit_card")
        conn.commit()
        conn.close()

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(
                self.host,
                self.port,
                "/api/transactions?month=2026-05&category=Groceries",
            )
        self.assertEqual(status, 200)
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 2)
        self.assertAlmostEqual(data["total"], -75.67)
        self.assertEqual(data["transactions"][0]["description"], "TESCO")
        self.assertIn("id", data["transactions"][0])
        self.assertEqual(data["transactions"][0]["category"], "Groceries")

    def test_categories_list(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)
        conn = sqlite3.connect(db_path)
        _insert_row(conn, "2026-05-01", "TESCO", -45.67, "Groceries")
        _insert_row(conn, "2026-05-02", "CUSTOM SHOP", -10, "My Custom")
        conn.commit()
        conn.close()

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(self.host, self.port, "/api/categories")
        self.assertEqual(status, 200)
        self.assertIn("Groceries", data)
        self.assertIn("My Custom", data)
        self.assertIn("Uncategorised", data)

    def test_post_category_invalid_json(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, body_bytes = _request(
                self.host,
                self.port,
                "/api/transaction/category",
                method="POST",
                body=b"not json",
                headers={"Content-Type": "application/json"},
            )
            data = json.loads(body_bytes.decode())
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "invalid JSON"})

    def test_post_category_missing_id(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _post_json(
                self.host, self.port, "/api/transaction/category", {"category": "Groceries"}
            )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "id is required"})

    def test_post_category_not_found(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _post_json(
                self.host, self.port, "/api/transaction/category", {"id": 99, "category": "Groceries"}
            )
        self.assertEqual(status, 404)
        self.assertEqual(data, {"error": "transaction not found"})

    def test_post_category_updates_matching_descriptions(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)
        conn = sqlite3.connect(db_path)
        _insert_row(conn, "2026-04-01", "TESCO", -10, "Uncategorised")
        _insert_row(conn, "2026-05-03", "TESCO", -45.00, "Uncategorised", "credit_card")
        _insert_row(conn, "2026-05-10", "NETFLIX", -9.99, "Subscriptions")
        conn.commit()
        txn_id = conn.execute(
            "SELECT id FROM transactions WHERE description = 'TESCO' LIMIT 1"
        ).fetchone()[0]
        conn.close()

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _post_json(
                self.host,
                self.port,
                "/api/transaction/category",
                {"id": txn_id, "category": "Groceries"},
            )
            month_status, _, month = _get_json(
                self.host, self.port, "/api/month?month=2026-05"
            )

        self.assertEqual(status, 200)
        self.assertEqual(data["updated_count"], 2)
        self.assertEqual(data["category"], "Groceries")
        self.assertEqual(month_status, 200)
        cats = {c["name"]: c["amount"] for c in month["categories"]}
        self.assertIn("Groceries", cats)
        self.assertNotIn("Uncategorised", cats)
        self.assertLess(month["total_spend"], 0)

    def test_search_missing_query_returns_400(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(self.host, self.port, "/api/search?scope=all")
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "q is required"})

    def test_search_invalid_scope_returns_400(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(
                self.host, self.port, "/api/search?q=BROMCOM&scope=week"
            )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "scope must be month, year, or all"})

    def test_search_invalid_month_returns_400(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(
                self.host, self.port, "/api/search?q=BROMCOM&scope=month&month=bad"
            )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "month must be YYYY-MM"})

    def test_search_invalid_year_returns_400(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            status, _, data = _get_json(
                self.host, self.port, "/api/search?q=BROMCOM&scope=year&year=20"
            )
        self.assertEqual(status, 400)
        self.assertEqual(data, {"error": "year must be YYYY"})

    def test_search_with_data(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.db"
        _create_db(db_path)
        conn = sqlite3.connect(db_path)
        _insert_row(conn, "2025-12-12", "BROMCOM BROMCOM", -80, "Education & Childcare")
        _insert_row(conn, "2026-01-02", "BROMCOM BROMCOM", -1218, "Education & Childcare")
        _insert_row(conn, "2026-05-03", "TESCO", -45.67, "Groceries")
        conn.commit()
        conn.close()

        with patch.object(web_server, "DB_PATH", db_path), patch.object(db_layer, "DB_PATH", db_path):
            all_status, _, all_data = _get_json(
                self.host, self.port, "/api/search?q=BROMCOM&scope=all"
            )
            year_status, _, year_data = _get_json(
                self.host, self.port, "/api/search?q=BROMCOM&scope=year&year=2026"
            )
            month_status, _, month_data = _get_json(
                self.host, self.port, "/api/search?q=BROMCOM&scope=month&month=2026-01"
            )

        self.assertEqual(all_status, 200)
        self.assertFalse(all_data["empty"])
        self.assertEqual(all_data["count"], 2)

        self.assertEqual(year_status, 200)
        self.assertFalse(year_data["empty"])
        self.assertEqual(year_data["count"], 1)

        self.assertEqual(month_status, 200)
        self.assertFalse(month_data["empty"])
        self.assertEqual(month_data["count"], 1)
        self.assertAlmostEqual(month_data["total"], -1218)


if __name__ == "__main__":
    unittest.main()
