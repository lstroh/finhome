"""
web_server.py — local dashboard for finance reports.

Serves a browser UI and JSON API on 127.0.0.1 only. No outbound network
calls; data is read from and category edits are written to db/finance.db.
"""

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))

from db_layer import (
    DB_PATH,
    MAX_BUDGET_AMOUNT,
    clear_category_budget,
    get_connection,
    get_transaction_by_id,
    set_category_budget,
    update_category_for_description,
)
from importer import import_uploaded_csv
from report_data import (
    category_options,
    category_transactions,
    list_months,
    month_over_month,
    month_report,
    month_transactions,
    month_vs_year_avg,
    search_transactions,
    source_status,
    subscriptions,
    summary,
    uncategorised,
)

STATIC_DIR = (Path(__file__).parent / "web" / "static").resolve()
DATA_DIR = (Path(__file__).parent / "data").resolve()
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
YEAR_RE = re.compile(r"^\d{4}$")
MAX_CATEGORY_LEN = 100
MAX_SEARCH_QUERY_LEN = 200
MAX_IMPORT_BODY_BYTES = 6 * 1024 * 1024

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "FinanceDashboard/1.2"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/transaction/category":
            self._post_transaction_category()
        elif path == "/api/category/budget":
            self._post_category_budget()
        elif path == "/api/import":
            self._post_import_csv()
        else:
            self._json_error(404, "not found")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/":
            self._serve_static("index.html")
        elif path == "/import":
            self._serve_static("import.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        elif path == "/api/months":
            self._api(lambda conn: self._json_ok(list_months(conn)))
        elif path == "/api/summary":
            self._api(lambda conn: self._json_ok(summary(conn)))
        elif path == "/api/month":
            month = query.get("month", [None])[0]
            if not month or not MONTH_RE.match(month):
                self._json_error(400, "month must be YYYY-MM")
                return
            self._api(lambda conn: self._json_ok(month_report(conn, month)))
        elif path == "/api/trends":
            self._api(lambda conn: self._json_ok(month_over_month(conn)))
        elif path == "/api/vs-average":
            month = query.get("month", [None])[0]
            if not month or not MONTH_RE.match(month):
                self._json_error(400, "month must be YYYY-MM")
                return
            self._api(lambda conn: self._json_ok(month_vs_year_avg(conn, month)))
        elif path == "/api/subscriptions":
            self._api(lambda conn: self._json_ok(subscriptions(conn)))
        elif path == "/api/uncategorised":
            self._api(lambda conn: self._json_ok(uncategorised(conn)))
        elif path == "/api/transactions":
            month = query.get("month", [None])[0]
            category = query.get("category", [None])[0]
            if not month or not MONTH_RE.match(month):
                self._json_error(400, "month must be YYYY-MM")
                return
            if category and category.strip():
                if len(category) > MAX_CATEGORY_LEN:
                    self._json_error(400, "category too long")
                    return
                cat = category.strip()
                self._api(lambda conn: self._json_ok(category_transactions(conn, month, cat)))
            else:
                self._api(lambda conn: self._json_ok(month_transactions(conn, month)))
        elif path == "/api/categories":
            self._api(lambda conn: self._json_ok(category_options(conn)))
        elif path == "/api/search":
            self._api_search(query)
        elif path == "/api/sources":
            self._api_conn(lambda conn: self._json_ok(source_status(conn)))
        else:
            self._json_error(404, "not found")

    def _api_search(self, query):
        q = query.get("q", [None])[0]
        scope = query.get("scope", [None])[0]
        month = query.get("month", [None])[0]
        year = query.get("year", [None])[0]

        if not q or not q.strip():
            self._json_error(400, "q is required")
            return
        if len(q) > MAX_SEARCH_QUERY_LEN:
            self._json_error(400, "query too long")
            return
        if scope not in ("month", "year", "all"):
            self._json_error(400, "scope must be month, year, or all")
            return
        if scope == "month":
            if not month or not MONTH_RE.match(month):
                self._json_error(400, "month must be YYYY-MM")
                return
        elif scope == "year":
            if not year or not YEAR_RE.match(year):
                self._json_error(400, "year must be YYYY")
                return

        def handler(conn):
            try:
                data = search_transactions(conn, q, scope, month=month, year=year)
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._json_ok(data)

        self._api(handler)

    def _post_transaction_category(self):
        if not DB_PATH.exists():
            self._json_error(
                503,
                "Database not found. Drop CSVs into data/ and run importer.py first.",
            )
            return

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._json_error(400, "request body required")
            return

        try:
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_error(400, "invalid JSON")
            return

        if not isinstance(payload, dict):
            self._json_error(400, "body must be a JSON object")
            return

        transaction_id = payload.get("id")
        category = payload.get("category")

        if transaction_id is None:
            self._json_error(400, "id is required")
            return
        if not isinstance(transaction_id, int) or transaction_id <= 0:
            self._json_error(400, "id must be a positive integer")
            return
        if not isinstance(category, str) or not category.strip():
            self._json_error(400, "category is required")
            return

        category = category.strip()
        if len(category) > MAX_CATEGORY_LEN:
            self._json_error(400, "category too long")
            return

        conn = get_connection()
        try:
            row = get_transaction_by_id(conn, transaction_id)
            if row is None:
                self._json_error(404, "transaction not found")
                return

            _, _, description, _, _, _, _ = row
            updated_count = update_category_for_description(conn, description, category)
            self._json_ok({
                "updated_count": updated_count,
                "category": category,
                "description": description,
            })
        finally:
            conn.close()

    def _post_category_budget(self):
        if not DB_PATH.exists():
            self._json_error(
                503,
                "Database not found. Drop CSVs into data/ and run importer.py first.",
            )
            return

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._json_error(400, "request body required")
            return

        try:
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_error(400, "invalid JSON")
            return

        if not isinstance(payload, dict):
            self._json_error(400, "body must be a JSON object")
            return

        category = payload.get("category")
        amount = payload.get("amount")

        if not isinstance(category, str) or not category.strip():
            self._json_error(400, "category is required")
            return

        category = category.strip()
        if len(category) > MAX_CATEGORY_LEN:
            self._json_error(400, "category too long")
            return

        conn = get_connection()
        try:
            if amount is None:
                clear_category_budget(conn, category)
                self._json_ok({"cleared": True, "category": category})
                return

            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                self._json_error(400, "amount must be a number or null")
                return

            amount = float(amount)
            if amount < 0:
                self._json_error(400, "amount must be zero or positive")
                return
            if amount > MAX_BUDGET_AMOUNT:
                self._json_error(
                    400,
                    f"amount exceeds sanity threshold (£{MAX_BUDGET_AMOUNT:,.0f})",
                )
                return

            if amount == 0:
                clear_category_budget(conn, category)
                self._json_ok({"cleared": True, "category": category})
                return

            stored = -amount
            set_category_budget(conn, category, stored)
            self._json_ok({
                "category": category,
                "amount": stored,
                "amount_display": amount,
            })
        finally:
            conn.close()

    def _post_import_csv(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._json_error(400, "request body required")
            return
        if length > MAX_IMPORT_BODY_BYTES:
            self._json_error(400, "request body too large")
            return

        try:
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_error(400, "invalid JSON")
            return

        if not isinstance(payload, dict):
            self._json_error(400, "body must be a JSON object")
            return

        source_type = payload.get("type")
        filename = payload.get("filename")
        content = payload.get("content")

        if not isinstance(source_type, str) or source_type not in ("bank", "credit_card"):
            self._json_error(400, "type must be bank or credit_card")
            return
        if not isinstance(filename, str) or not filename.strip():
            self._json_error(400, "filename is required")
            return
        if not isinstance(content, str) or not content.strip():
            self._json_error(400, "content is required")
            return

        try:
            result = import_uploaded_csv(source_type, filename, content, DATA_DIR)
        except ValueError as exc:
            self._json_error(400, str(exc))
            return
        except Exception:
            self._json_error(500, "import failed")
            return

        self._json_ok(result)

    def _api(self, handler):
        if not DB_PATH.exists():
            self._json_error(
                503,
                "Database not found. Drop CSVs into data/ and run importer.py first.",
            )
            return
        conn = get_connection()
        try:
            handler(conn)
        finally:
            conn.close()

    def _api_conn(self, handler):
        """Run a handler with a DB connection (creates DB/schema if missing)."""
        conn = get_connection()
        try:
            handler(conn)
        finally:
            conn.close()

    def _json_ok(self, data):
        self._send_json(200, data)

    def _json_error(self, status, message):
        self._send_json(status, {"error": message})

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, rel_path):
        if not rel_path or ".." in rel_path.split("/"):
            self._json_error(404, "not found")
            return

        file_path = (STATIC_DIR / rel_path).resolve()
        try:
            file_path.relative_to(STATIC_DIR)
        except ValueError:
            self._json_error(404, "not found")
            return

        if not file_path.is_file():
            self._json_error(404, "not found")
            return

        body = file_path.read_bytes()
        content_type = CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Local web dashboard for finance reports.")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Finance dashboard running at {url}")
    print("Data stays on this machine — bound to 127.0.0.1 only.")
    print("API includes /api/transactions, POST /api/import, and GET /api/sources.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
