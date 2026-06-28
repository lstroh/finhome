# Local Web Dashboard — Implementation Plan

**Approach:** Option 1 — stdlib-only local HTTP server (`http.server` + SQLite + HTML/CSS/JS)

**Goal:** A browser UI on `http://127.0.0.1` that shows the same insights as `python3 analyze.py`, reading live from `db/finance.db`. No pip dependencies, no network calls, no cloud.

**Status:** All four phases complete (2026-06-21). Post-implementation review and test hardening done same day — see [Post-implementation review](#post-implementation-review-2026-06-21). The dashboard is ready to use — see [How to run](#how-to-run) below.

---

## Principles (non-negotiable)

- **Stdlib only** — `http.server`, `sqlite3`, `json`, `pathlib`, etc. No Flask, Streamlit, or CDN assets.
- **Localhost only** — bind to `127.0.0.1`, not `0.0.0.0`. Financial data must not be reachable from other machines on the network.
- **Read-only web layer** — the dashboard queries SQLite; it does not import CSVs or edit categories. Import and rule changes stay CLI (`importer.py`, `recategorise.py`).
- **Single source of truth for logic** — report calculations live in shared Python functions reused by both `analyze.py` (CLI) and the web server. No duplicated business logic in JavaScript.
- **Fail loudly** — invalid API parameters return clear HTTP 400 responses with a JSON error message, matching the project's parsing philosophy.

---

## Current state

| Component | Role today |
|-----------|------------|
| `db_layer.py` | SQLite connection, schema, inserts |
| `report_data.py` | **Done (Phase 1)** — all report calculations; returns dicts/lists |
| `analyze.py` | **Done (Phase 1)** — thin CLI wrapper; imports `report_data`, formats via `print_*` |
| `rules/categories.py` | `NON_SPENDING_CATEGORIES`, `NEEDS_CATEGORIES`, `WANTS_CATEGORIES` |
| `recategorise.py` | Re-apply category rules without full re-import |
| `tests/__init__.py` | **Done (Phase 1 + review)** — empty package marker |
| `tests/test_report_data.py` | **Done (Phase 1)** — 15 stdlib unit tests with in-memory synthetic DB |
| `tests/test_web_server.py` | **Done (review)** — 9 stdlib HTTP/integration tests (temp DB, no real `finance.db`) |
| `web_server.py` | **Done (Phase 2)** — stdlib HTTP server on 127.0.0.1 |
| `web/static/` | **Done (Phase 3)** — single-page dashboard (HTML/CSS/JS) |
| `README.md` | **Done (Phase 4)** — web dashboard usage and commands |
| `.cursor/rules/project.mdc` | **Done (Phase 4)** — architecture docs for web layer |

The web dashboard exposes the **default `analyze.py` report** plus the individual flags (`--month`, `--trends`, `--subscriptions`, `--uncategorised`).

---

## How to run

### Prerequisites

- Python 3.8+ (stdlib only — no `pip install`)
- CSV exports in `data/accounts/` and/or `data/credit_card/`

### First-time setup or after adding new CSVs

From the project root (`finance_tracker/`):

```bash
# 1. Import CSVs into SQLite (safe to re-run — duplicates are skipped)
python importer.py

# 2. Start the local web server (default port 8765)
python web_server.py

# 3. Open in your browser
#    http://127.0.0.1:8765
```

On Windows, `python` and `python3` are equivalent if both point to Python 3.

### Optional: custom port

```bash
python web_server.py --port 9000
# → http://127.0.0.1:9000
```

### Terminal-only alternative

The CLI still works unchanged and shows the same numbers:

```bash
python analyze.py                    # full report (latest month + trends + subscriptions)
python analyze.py --month 2026-05    # one month
python analyze.py --trends           # month-over-month table only
python analyze.py --subscriptions    # recurring charges only
python analyze.py --uncategorised    # descriptions needing category rules
python analyze.py --export out.csv   # flat CSV export (CLI only)
```

### After editing category rules

Categorisation is applied at import time. To refresh existing rows:

1. Edit `rules/categories.py`, then either:
   - Run `python recategorise.py` (re-applies rules without re-import), **or**
   - Delete `db/finance.db` and re-run `python importer.py` (full rebuild from CSVs)
2. **Refresh the browser page** — the dashboard does not auto-reload when the DB changes.

### Stopping the server

Press **Ctrl+C** in the terminal where `web_server.py` is running.

### Quick API checks (optional)

With the server running:

```bash
# Default dashboard payload
curl http://127.0.0.1:8765/api/summary

# List months, single month, trends, subscriptions, uncategorised
curl http://127.0.0.1:8765/api/months
curl "http://127.0.0.1:8765/api/month?month=2026-05"
curl http://127.0.0.1:8765/api/trends
curl http://127.0.0.1:8765/api/subscriptions
curl http://127.0.0.1:8765/api/uncategorised
```

On Windows without `curl`, use Python:

```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8765/api/summary').read().decode())"
```

### Run unit tests

```bash
python -m unittest discover -s tests -v
```

---

## Architecture

```
Browser (HTML/CSS/JS)
        │
        │  GET /              → shell page (static)
        │  GET /api/...       → JSON from SQLite
        ▼
web_server.py  (http.server on 127.0.0.1:PORT)
        │
        ├── serves web/static/*  (CSS, JS)
        │
        └── calls report_data.py (pure data functions)
                    │
                    └── db_layer.get_connection() → db/finance.db
```

`analyze.py` CLI becomes a thin wrapper: call `report_data` functions, then `print()` the results. The web server calls the same functions and returns `json.dumps(...)`.

---

## File layout (as built)

```
finance_tracker/
├── analyze.py              # CLI; uses report_data, print_* formatters
├── report_data.py          # pure data functions (no print, no HTTP)
├── web_server.py           # stdlib HTTP server + routing
├── web/
│   └── static/
│       ├── index.html      # single-page shell + tab navigation
│       ├── style.css       # layout, tables, CSS category bars
│       └── app.js          # fetch API, render views, month selector
├── tests/
│   ├── __init__.py         # package marker
│   ├── test_report_data.py # 15 unit tests (in-memory DB)
│   └── test_web_server.py  # 9 HTTP/integration tests (temp DB)
└── db/finance.db           # SQLite database (gitignored)
```

Keep everything flat and small. No build step, no templates engine (stdlib `string` substitution is enough if needed; prefer static HTML + JS).

---

## Phase 1 — Extract shared report logic (`report_data.py`)

Move calculation code out of `analyze.py` into functions that return structured data (dicts/lists), not strings.

| Function | Returns | Replaces |
|----------|---------|----------|
| `list_months(conn)` | `["2026-04", "2026-05", ...]` | inline month discovery |
| `month_report(conn, target_month)` | dict with `total_spend`, `income`, `net`, `categories[]`, `benchmark`, `top_merchants[]` | `print_month_report` body |
| `month_over_month(conn)` | dict with `months[]`, `categories[]`, `grid`, `totals[]`, `anomalies[]` | `print_month_over_month` body |
| `uncategorised(conn)` | list of `{description, amount}` | `print_uncategorised` query |
| `subscriptions(conn)` | list of `{description, avg_amount, months_seen}`, plus `estimated_monthly`, `estimated_yearly` | `detect_subscriptions` + totals |
| `summary(conn)` | combined default report: latest month + trends + subscriptions + `uncategorised_count` | `main()` default branch |

Keep existing helpers (`fmt_gbp`, `month_key`, `category_breakdown`, `detect_subscriptions`) in `analyze.py` or move them to `report_data.py` — one place only.

**Refactor rule:** After Phase 1, running `python3 analyze.py` must produce identical CLI output to today. Verify before building the web layer.

---

## Phase 2 — HTTP server (`web_server.py`)

### Server setup

- Use `http.server.ThreadingHTTPServer` (or `HTTPServer` if concurrency is unnecessary) bound to `("127.0.0.1", port)`.
- Default port: `8765` (configurable via `--port` CLI arg).
- Subclass `BaseHTTPRequestHandler` (or `SimpleHTTPRequestHandler` for static files) with explicit routing in `do_GET`.
- On startup, print the URL and remind the user data stays local.

### Routes

| Route | Purpose |
|-------|---------|
| `GET /` | Serve `web/static/index.html` |
| `GET /static/*` | Serve CSS/JS from `web/static/` (path traversal protection required) |
| `GET /api/months` | List available months |
| `GET /api/summary` | Default dashboard payload (latest month + trends + subscriptions) |
| `GET /api/month?month=YYYY-MM` | Single-month report |
| `GET /api/trends` | Month-over-month table + anomalies |
| `GET /api/subscriptions` | Detected recurring charges |
| `GET /api/uncategorised` | Distinct uncategorised descriptions |

All `/api/*` responses: `Content-Type: application/json; charset=utf-8`.

### Security details

- **Bind address:** `127.0.0.1` only.
- **Static file serving:** resolve paths under `web/static/`; reject `..` in URLs.
- **No POST/PUT/DELETE** in v1 — read-only dashboard.
- **No auth in v1** — acceptable because localhost-only; document that exposing the port beyond the machine is out of scope.

### Error handling

| Case | Response |
|------|----------|
| Unknown route | `404` + `{"error": "not found"}` |
| Invalid `month` format | `400` + `{"error": "month must be YYYY-MM"}` |
| No data in DB | `200` + `{"empty": true, "message": "..."}` (same guidance as CLI) |
| SQLite missing | `503` + clear message to run `importer.py` first |

Open one DB connection per request (simple, safe for a personal tool). Close in a `finally` block.

---

## Phase 3 — Frontend (`web/static/`)

Single-page app: no framework. Vanilla HTML/CSS/JS only.

### Views (tabs or sections)

1. **Overview** (default) — mirrors `analyze.py` with no flags:
   - Summary cards: total spend, income, net (latest month)
   - Category breakdown table with percentage bars (CSS, not a chart library)
   - 50/30/20 benchmark row
   - Top 10 merchants
   - Uncategorised warning banner if count > 0

2. **Trends** — month-over-month category grid (scrollable table on small screens)
   - Anomaly callouts below the table (up/down %, same thresholds as CLI)

3. **Subscriptions** — table with monthly/yearly estimated total footer

4. **Uncategorised** — sortable table of descriptions needing rules in `rules/categories.py`

### Month selector

- Dropdown populated from `GET /api/months`
- Changing month refreshes Overview via `GET /api/month?month=...`
- Default selection: latest month

### Formatting

- Amounts formatted in JS for display (`£1,234.56`, negative shown with minus)
- Server sends raw floats; presentation stays in the browser (keeps API simple)

### Styling

- Clean, readable typography; works on a laptop-width viewport
- No external fonts or icons (offline-safe)
- Use CSS variables for a simple light theme; dark mode is optional later

### Charts (v1)

- **CSS bar charts** for category % — no charting library needed
- Defer line/bar chart libraries to a future phase unless a tiny inline SVG helper is added

---

## Phase 4 — CLI integration and docs

### `analyze.py`

- Import from `report_data`; keep `print_*` functions as formatters over the data dicts
- No user-facing behaviour change

### README

Add a short section:

```bash
python3 web_server.py          # open http://127.0.0.1:8765
python3 web_server.py --port 9000
```

Workflow: `importer.py` → `web_server.py` (or `analyze.py` for terminal-only).

### `.cursor/rules/project.mdc`

- **Done** — documents `report_data.py`, `web_server.py`, and the localhost constraint

---

## Implementation order (checklist)

- [x] **1.1** Create `report_data.py` with `month_report`, `month_over_month`, `subscriptions`, `uncategorised`, `summary`, `list_months`
- [x] **1.2** Refactor `analyze.py` to use `report_data`; verify CLI output unchanged
- [x] **2.1** Create `web_server.py` with static file serving + path safety
- [x] **2.2** Add `/api/*` JSON endpoints
- [x] **2.3** Manual test: `curl http://127.0.0.1:8765/api/summary`
- [x] **3.1** Build `index.html` shell + navigation
- [x] **3.2** Implement Overview + month selector in `app.js`
- [x] **3.3** Implement Trends, Subscriptions, Uncategorised sections
- [x] **3.4** Add `style.css` (layout, tables, category bars)
- [x] **4.1** Update README
- [x] **4.2** Smoke test full flow: import → web server → browser
- [x] **5.1** Post-implementation review: compare plan vs code, document findings
- [x] **5.2** Add `tests/__init__.py` (was documented in Phase 1 but missing on disk)
- [x] **5.3** Add `tests/test_web_server.py` — automated coverage for routes, errors, path traversal, bind address

---

## Testing strategy

No external test framework (stdlib `unittest` only). Automated and manual checks:

1. **Synthetic DB** — `test_report_data.py` uses in-memory SQLite; `test_web_server.py` uses temp-file DBs with fake merchants — neither touches `db/finance.db` or `data/`
2. **CLI parity** — compare key numbers from `analyze.py` and `/api/summary` for the same month (verified manually during implementation)
3. **Edge cases** — empty DB, single month (no trends), no subscriptions, all categorised (`test_report_data.py` + `test_web_server.py`)
4. **Security** — automated in `test_web_server.py`: path traversal rejected, unknown routes 404, bind address `127.0.0.1`, missing DB 503
5. **Browser UI** — manual smoke test recommended (`python web_server.py` → open http://127.0.0.1:8765); not automated in v1

Run all tests:

```bash
python -m unittest discover -s tests -v   # 24 tests (15 report_data + 9 web_server)
```

---

## Out of scope for v1

- Editing categories from the browser
- Running `importer.py` from the browser
- User authentication
- Binding to LAN (`0.0.0.0`)
- `--export` CSV from the web UI (CLI remains sufficient)
- `--year` flag (can add `/api/year?year=YYYY` in v2 if needed)
- Mobile-first polish
- Auto-refresh when DB changes (user refreshes the page)

---

## Future enhancements (v2+)

| Feature | Notes |
|---------|-------|
| Live reload | SSE or polling when `finance.db` mtime changes |
| Transaction drill-down | Click a category → list transactions for that month |
| Year view | Port `--year` when added to `analyze.py` |
| Print / save as PDF | Browser print stylesheet |
| Dark mode | CSS toggle only |

---

## Success criteria

- [x] `python3 web_server.py` starts without pip install
- [x] Browser shows the same totals and categories as `python3 analyze.py` for the latest month
- [x] Trends, subscriptions, and uncategorised views match CLI flags
- [x] Server listens only on `127.0.0.1`
- [x] No outbound network requests from the app
- [x] `analyze.py` CLI behaviour unchanged after refactor
- [x] Automated tests cover `report_data.py` and `web_server.py` security/routing (24 tests total, post-review)

---

## Phase 1 — Completed (2026-06-21)

Phase 1 extracted all report calculation logic from `analyze.py` into `report_data.py`. The CLI is unchanged in behaviour; the web server (Phase 2) should import from `report_data` directly — do not duplicate logic in JavaScript or in `web_server.py`.

### Files added or changed

| File | Change |
|------|--------|
| `report_data.py` | **New** — pure data layer (no `print`, no HTTP) |
| `analyze.py` | **Refactored** — imports `report_data`; keeps `fmt_gbp` and all `print_*` formatters |
| `tests/__init__.py` | **New** — empty package marker |
| `tests/test_report_data.py` | **New** — 15 unit tests |

Nothing else was changed. `web_server.py`, `web/static/`, and README were not touched.

### Where logic lives now

**In `report_data.py` only** (moved from `analyze.py`):

- `month_key`, `get_all_transactions`, `category_breakdown`, `detect_subscriptions`
- `list_months`, `month_report`, `month_over_month`, `uncategorised`, `subscriptions`, `summary`

**Still in `analyze.py` only** (presentation / CLI):

- `fmt_gbp` — currency formatting for terminal output
- `print_uncategorised`, `print_subscriptions`, `print_month_report`, `print_month_over_month`
- `export_csv` — unchanged; not extracted (out of web dashboard scope)
- `main()` — argparse; calls `report_data` then `print_*`

Emojis (`🎉`, `⚠️`) remain in `print_*` functions only, not in `report_data` return values.

### Public API — exact return shapes

These are the contracts Phase 2 `/api/*` endpoints should serialize with `json.dumps`. Amounts are raw `float` GBP (negative = money out).

#### `list_months(conn) -> list[str]`

```python
["2026-04", "2026-05", "2026-06"]  # sorted ascending
```

#### `month_report(conn, target_month) -> dict`

Empty month:

```python
{"month": "2026-01", "empty": True}
```

Populated month:

```python
{
    "month": "2026-05",
    "empty": False,
    "total_spend": -4684.77,       # sum of spending categories (negative)
    "income": 3285.81,
    "net": -1398.96,               # income + total_spend
    "categories": [
        {"name": "Housing", "amount": -1400.35, "pct": 29.9},
        # sorted by amount ascending (most negative / highest spend first)
    ],
    "benchmark": {
        "needs": -3446.71,
        "wants": -1238.06,
        "other": 0.0,                # total_spend - needs - wants
        "needs_pct": -73.6,          # abs(needs) / total_spend * 100 (negative because total_spend is negative)
        "wants_pct": -26.4,
        "savings_rate": -42.6,       # (income + total_spend) / income * 100; None if no income
    },
    "top_merchants": [
        {"description": "BARCLAYS UK MTGES", "amount": -1400.35},
        # max 10, sorted most negative first
    ],
}
```

#### `month_over_month(conn) -> dict`

No rows at all:

```python
{"empty": True}
```

Fewer than 2 months:

```python
{"empty": False, "insufficient_months": True, "months": ["2026-05"]}
```

Normal (2+ months):

```python
{
    "empty": False,
    "insufficient_months": False,
    "months": ["2026-04", "2026-05", "2026-06"],
    "categories": ["Groceries", "Transport", ...],   # sorted alphabetically
    "grid": {
        "Groceries": {"2026-04": -100.0, "2026-05": -120.0, "2026-06": 0},
        # 0 means no spend that month (CLI prints "—")
    },
    "totals": {"2026-04": -800.0, "2026-05": -950.0, ...},
    "anomalies": [                                   # only when len(months) >= 3
        {
            "category": "Transport",
            "direction": "up",                       # or "down"
            "change_pct": 45.0,                      # absolute percentage
            "prior_avg": -50.0,
            "latest": -72.5,
        },
    ],
}
```

Anomaly thresholds (unchanged from original `analyze.py`): latest month vs average of all prior months; flag when `abs(change_pct) >= 30` **and** `abs(latest - prior_avg) > 20` (GBP).

#### `uncategorised(conn) -> list[dict]`

```python
[
    {"description": "MYSTERY SHOP", "amount": -12.99},
    # DISTINCT (description, amount) pairs, ordered by description
]
```

Empty list if nothing uncategorised (CLI prints the 🎉 message separately).

#### `subscriptions(conn) -> dict`

```python
{
    "items": [
        {"description": "NETFLIX", "avg_amount": -9.99, "months_seen": 4},
        # sorted by avg_amount ascending (most expensive / most negative first)
    ],
    "estimated_monthly": -45.97,     # sum of avg_amount across items
    "estimated_yearly": -551.64,
}
```

Subscription detection heuristic (unchanged): 3+ charges, amount within 5% each time, 3+ distinct months, ≤ 1.5 charges per month on average. Excludes `NON_SPENDING_CATEGORIES`.

#### `summary(conn) -> dict`

Empty DB:

```python
{
    "empty": True,
    "message": "No data imported yet. Drop CSVs into data/accounts/ and data/credit_card/, then run importer.py.",
}
```

Default report payload (mirrors `python analyze.py` with no flags):

```python
{
    "empty": False,
    "latest_month": "2026-05",
    "month": { ... },                # month_report(conn, latest_month)
    "trends": { ... } | None,        # month_over_month(conn); None if insufficient_months
    "subscriptions": { ... },
    "uncategorised_count": 3,        # row count (not distinct descriptions)
}
```

Note: `uncategorised_count` counts **transaction rows** with category `Uncategorised`, while `uncategorised()` returns **distinct** `(description, amount)` pairs. This matches the original CLI warning line.

### How `analyze.py` maps flags to `report_data`

| CLI flag | `report_data` call |
|----------|-------------------|
| (default) | `summary(conn)` → then `print_month_report`, `print_month_over_month`, `print_subscriptions` |
| `--month YYYY-MM` | `month_report(conn, month)` via `print_month_report` |
| `--trends` | `month_over_month(conn)` via `print_month_over_month` |
| `--subscriptions` | `subscriptions(conn)` via `print_subscriptions` |
| `--uncategorised` | `uncategorised(conn)` via `print_uncategorised` |
| `--export FILE` | `get_all_transactions(conn)` only — not in `report_data` public API surface |

### Tests added

Run from project root:

```bash
python -m unittest discover -s tests -v
```

**15 tests** in `tests/test_report_data.py`, all using an in-memory SQLite DB (`:memory:`) with fake merchants — never touches `db/finance.db` or `data/`. See [Post-implementation review](#post-implementation-review-2026-06-21) for the additional 9 `test_web_server.py` tests (24 total).

| Test class | What it covers |
|------------|----------------|
| `TestListMonths` | Month list sorted ascending |
| `TestMonthReport` | Totals, non-spending exclusion, empty month, benchmark formula |
| `TestMonthOverMonth` | Grid/totals, insufficient months, anomaly up/down, anomaly threshold |
| `TestUncategorised` | DISTINCT descriptions |
| `TestSubscriptions` | Detection, variable amounts rejected, frequent charges rejected |
| `TestSummary` | Empty DB message, full payload structure |

Helper functions in the test file (not exported):

- `make_test_conn()` — creates in-memory DB with same schema as `db_layer.py`
- `insert_row(conn, date, description, amount, category)` — uses `db_layer.make_hash`

### Verification performed

1. **Unit tests:** `python -m unittest discover -s tests -v` → 15/15 OK (report_data only at Phase 1 completion; 24/24 after review)
2. **CLI parity (real DB):** `--trends`, `--subscriptions`, `--uncategorised` output identical before and after refactor (`fc` file compare)
3. **Full default report:** runs correctly; totals match (e.g. latest month 2026-05: spend -£4,684.77, income £3,285.81, net -£1,398.96)

**Note (review fix):** Phase 1 completion notes listed `tests/__init__.py` as added, but the file was missing on disk until the post-implementation review (2026-06-21). It has since been created.

**Windows note:** `analyze.py` now calls `sys.stdout.reconfigure(encoding="utf-8")` at startup so piping output to a file no longer fails on the `█` bar character under cp1252.

---

## Phase 2 — Completed (2026-06-21)

Phase 2 added `web_server.py`: a read-only stdlib HTTP server that serves the dashboard static files and JSON API endpoints backed by `report_data.py`.

### Files added

| File | Role |
|------|------|
| `web_server.py` | `ThreadingHTTPServer` on `127.0.0.1`, routing, JSON serialization |

### Server implementation

| Detail | As built |
|--------|----------|
| Server class | `http.server.ThreadingHTTPServer` |
| Handler | `DashboardHandler` extends `BaseHTTPRequestHandler` |
| Bind address | `("127.0.0.1", port)` only — never `0.0.0.0` |
| Default port | `8765` (`--port` CLI arg to override) |
| HTTP methods | `GET` only (read-only v1) |
| DB access | One `get_connection()` per API request; closed in `finally` |
| JSON encoding | `json.dumps(..., ensure_ascii=False).encode("utf-8")` |
| Static root | `web/static/` resolved via `Path.resolve()` + `relative_to()` check |
| Path traversal | Rejects `..` in URL path segments; files outside `STATIC_DIR` return 404 |
| Missing DB file | `503` + `{"error": "Database not found. Drop CSVs into data/ and run importer.py first."}` |
| Month validation | Regex `^\d{4}-\d{2}$` on `/api/month?month=` before calling `month_report` |
| Startup message | Prints URL and reminds user data stays local |

### API routes (all implemented)

| Route | Handler | Response |
|-------|---------|----------|
| `GET /` | Serves `web/static/index.html` | `text/html` |
| `GET /static/*` | Serves `style.css`, `app.js`, etc. | Matched content-type by suffix |
| `GET /api/months` | `list_months(conn)` | JSON array of `YYYY-MM` strings |
| `GET /api/summary` | `summary(conn)` | Full default dashboard payload |
| `GET /api/month?month=YYYY-MM` | `month_report(conn, month)` | Single-month report dict |
| `GET /api/trends` | `month_over_month(conn)` | Trends grid + anomalies |
| `GET /api/subscriptions` | `subscriptions(conn)` | Recurring charges + totals |
| `GET /api/uncategorised` | `uncategorised(conn)` | Distinct uncategorised descriptions |

### Error responses (verified)

| Case | Status | Body |
|------|--------|------|
| Unknown route | 404 | `{"error": "not found"}` |
| Invalid `month` param | 400 | `{"error": "month must be YYYY-MM"}` |
| Empty DB (via `summary`) | 200 | `{"empty": true, "message": "..."}` |
| `db/finance.db` missing | 503 | `{"error": "Database not found. ..."}` |
| Path traversal attempt | 404 | `{"error": "not found"}` |

### Verification performed

1. `/api/summary` returns 200 with live data when DB exists
2. CLI/API numeric parity confirmed (e.g. latest month spend -£4,684.77, income £3,285.81, net -£1,398.96)
3. `GET /static/../../db/finance.db` returns 404 (does not leak DB file)
4. `GET /api/month?month=bad` returns 400

**Automated coverage (added in review):** `tests/test_web_server.py` now locks in items 3–4 plus bind address, static serving, 503/400/404 responses, and empty/populated DB API behaviour. See [Post-implementation review](#post-implementation-review-2026-06-21).

---

## Phase 3 — Completed (2026-06-21)

Phase 3 added the browser UI under `web/static/`: a vanilla single-page app with no frameworks, CDN assets, or build step.

### Files added

| File | Role |
|------|------|
| `web/static/index.html` | Page shell, header, tab nav, view containers |
| `web/static/style.css` | Light theme via CSS variables, cards, tables, category bars |
| `web/static/app.js` | API client, rendering, month selector, tab switching |

### Views (tabs)

| Tab | CLI equivalent | What it shows |
|-----|----------------|---------------|
| **Overview** (default) | `analyze.py` (no flags) | Summary cards (spend, income, net); category table with CSS percentage bars; 50/30/20 benchmark; top 10 merchants; uncategorised warning banner when count > 0 |
| **Trends** | `analyze.py --trends` | Month-over-month category grid (horizontally scrollable); anomaly callouts (up/down %, same thresholds as CLI) |
| **Subscriptions** | `analyze.py --subscriptions` | Table of detected recurring charges; footer with estimated monthly/yearly totals |
| **Uncategorised** | `analyze.py --uncategorised` | Sortable table (click column headers for description or amount); guidance to edit `rules/categories.py` |

### Frontend behaviour

| Feature | Implementation |
|---------|----------------|
| Month selector | Dropdown from `GET /api/months`; default = latest month; changing month calls `GET /api/month?month=...` and refreshes Overview only |
| Initial load | `GET /api/summary` → populates Overview; also fetches `/api/months` and `/api/uncategorised`; uses embedded `trends`/`subscriptions` from summary or falls back to dedicated endpoints |
| Currency display | `fmtGbp()` in JS — `£1,234.56`, minus prefix for negatives |
| Percentages | `fmtPct()` uses `Math.abs()` so benchmark shares display as positive % (API may send negative `needs_pct`/`wants_pct`) |
| Category bars | CSS `bar-fill` width scaled to max category % in the month |
| Empty states | Friendly messages when DB empty, no subscriptions, all categorised, or insufficient months for trends |
| Errors | API failures shown in a red alert banner |
| Offline-safe | System font stack only; no external fonts, icons, or CDN scripts |

### Styling notes

- Max content width ~1100px; responsive tab bar and scrollable trend tables
- CSS variables for colours (`--bg`, `--surface`, `--accent`, etc.)
- Anomaly callouts colour-coded: red tint for "up", green tint for "down"

---

## Phase 4 — Completed (2026-06-21)

Phase 4 integrated documentation and confirmed end-to-end behaviour.

### Files changed

| File | Change |
|------|--------|
| `README.md` | Added web dashboard section, commands, workflow (`importer.py` → `web_server.py`) |
| `.cursor/rules/project.mdc` | Documented `report_data.py`, `web_server.py`, localhost constraint |
| `analyze.py` | Minor cleanup: removed unused `defaultdict` import; removed unimplemented `--year` from docstring; added UTF-8 stdout reconfigure for Windows piping |

### CLI unchanged

`analyze.py` behaviour and output format are unchanged aside from the Windows encoding fix. All `print_*` formatters remain in `analyze.py`; the web layer never duplicates report logic.

### End-to-end workflow (verified)

```
Drop CSVs → python importer.py → python web_server.py → browser at http://127.0.0.1:8765
```

Refresh the browser after re-importing or recategorising. No auto-reload in v1.

### Full test matrix

| Check | Result |
|-------|--------|
| `python -m unittest discover -s tests -v` | 24/24 OK (after review; was 15/15 at Phase 4 completion) |
| `python web_server.py` starts without pip install | OK |
| Browser totals match `python analyze.py` for latest month | OK (API/CLI parity verified; browser UI not manually tested by owner yet) |
| Trends / subscriptions / uncategorised match CLI flags | OK |
| Server binds to `127.0.0.1` only | OK (also covered by `test_bind_address_is_localhost`) |
| No outbound network requests from the app | OK (stdlib local server + static assets) |
| Path traversal blocked | OK (automated in `test_path_traversal_rejected`) |

---

## Post-implementation review (2026-06-21)

Independent review compared this plan, the completion notes in each phase section, and the actual codebase. **Verdict: implementation faithfully delivers the plan.** Four phases match spec; no blocking issues found.

### Review method

1. Read all phase completion notes and API contracts in this document
2. Inspected `report_data.py`, `web_server.py`, `web/static/*`, `analyze.py`, README, and `.cursor/rules/project.mdc`
3. Ran `python -m unittest discover -s tests -v` and live HTTP smoke tests against `web_server.py`
4. Compared CLI output and `/api/summary` numeric parity on real `db/finance.db`

### What matched the plan

| Area | Finding |
|------|---------|
| Architecture | Shared logic in `report_data.py`; CLI and web both consume it — no duplicated business logic in JS |
| Security | `127.0.0.1` bind, GET-only, path traversal rejection, one DB connection per request |
| API surface | All 8 routes implemented with documented error shapes (404, 400, 503, empty DB 200) |
| Frontend | Vanilla HTML/CSS/JS, no CDN/framework, CSS category bars, four tabs, month selector |
| Principles | Stdlib only, no outbound network calls, read-only web layer |
| Numeric parity | Latest month example confirmed: spend -£4,684.77, income £3,285.81, net -£1,398.96 |

### Issues found and resolution

| Issue | Severity | Resolution |
|-------|----------|------------|
| `tests/__init__.py` documented in Phase 1 but missing on disk | Low | **Fixed** — file created during review |
| No automated tests for `web_server.py` (security cases were manual only) | Low–medium | **Fixed** — `tests/test_web_server.py` added (9 tests) |
| Benchmark `%` sign: CLI prints negative `needs_pct`/`wants_pct`; web uses `Math.abs()` and shows positive | Cosmetic | **Open** — intentional presentation difference; align in v2 if desired |
| Overview tab wording "mirrors `analyze.py` with no flags" is imprecise — default CLI prints month + trends + subscriptions sequentially; dashboard splits across tabs | Cosmetic | Documented here; Phase 3 tab table is the accurate spec |
| Static 404s return JSON `{"error": "not found"}` rather than HTML | Minor UX | Accepted for v1; consistent with API error format |
| `.cursor/rules/project.mdc` omits `recategorise.py` (plan and README mention it) | Minor doc gap | Not fixed in review — optional follow-up |
| Browser UI not manually tested by project owner | Informational | Recommended: `python web_server.py` → http://127.0.0.1:8765, click through all four tabs |

### Files added during review

| File | Change |
|------|--------|
| `tests/__init__.py` | Empty package marker (matches Phase 1 documentation) |
| `tests/test_web_server.py` | **New** — 9 HTTP/integration tests |

### `test_web_server.py` coverage

| Test class | What it covers |
|------------|----------------|
| `TestWebServerBind` | Server address is `127.0.0.1` |
| `TestWebServerStatic` | `GET /` HTML, `GET /static/style.css`, path traversal 404, unknown route 404 |
| `TestWebServerApi` | Missing DB 503, invalid month 400, empty DB summary 200, populated DB summary/months/month endpoints |

Tests start a real `ThreadingHTTPServer` on an ephemeral port in-process. API tests patch `web_server.DB_PATH` and `db_layer.DB_PATH` to temp SQLite files — never reads real financial data.

**Windows note:** temp DB files must be fully closed before cleanup; tests close all SQLite connections explicitly to avoid `PermissionError` on `TemporaryDirectory` teardown.

### Verification after review

```bash
python -m unittest discover -s tests -v   # 24/24 OK
```

Manual HTTP smoke tests (summary 200, months 200, bad month 400, traversal 404, index HTML, static CSS) also confirmed on live server.
