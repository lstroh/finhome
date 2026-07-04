# Local Web Dashboard — v2 Implementation Plan

**Builds on:** [WEB_DASHBOARD_PLAN.md](WEB_DASHBOARD_PLAN.md) (v1 complete, 2026-06-21)

**Approach:** Same as v1 — stdlib-only local HTTP server, shared logic in `report_data.py`, vanilla HTML/CSS/JS frontend.

**Goal:** Ship transaction drill-down and year view — without breaking CLI parity or v1 security constraints.

**Status:** Phase 1 complete (2026-06-21). Category editing addendum complete (2026-06-27). Payment search addendum complete (2026-06-28). Search category editing complete (2026-06-28). Next: Phase 2 (year view).

**Scope decisions:**

| Decision | Date | Outcome |
|----------|------|---------|
| Live reload | 2026-06-21 | **Not in v2** — user refreshes browser after import/recategorise (same as v1) |
| Print / PDF | 2026-06-21 | Deferred to v3 |
| Dark mode | 2026-06-21 | Deferred to v3 |
| SSE / polling | 2026-06-21 | Explicitly rejected — no auto-refresh in v2 |
| Category editing | 2026-06-27 | Added as post-Phase 1 addendum: local-only edits, persisted as description overrides |

---

## Principles

- **Stdlib only** — no Flask, no chart libraries, no CDN assets.
- **Localhost only** — bind to `127.0.0.1`, never `0.0.0.0`.
- **Local-only web writes** — no CSV import from the browser; category edits are allowed via localhost-only API and stored in SQLite.
- **Single source of truth** — new calculations live in `report_data.py`; `analyze.py` and `web_server.py` consume them.
- **Fail loudly** — invalid query params → HTTP 400 with JSON `{"error": "..."}`.

---

## v2 feature summary

| # | Feature | In v2? | Status |
|---|---------|--------|--------|
| 1 | Transaction drill-down | **Yes** | **Done** (2026-06-21) |
| 2 | Year view | **Yes** | Not started |
| 3 | Polish (optional) | **Yes** | Not started |
| A | Category editing addendum | **Yes** | **Done** (2026-06-27) |
| B | Payment search addendum | **Yes** | **Done** (2026-06-28) |
| C | Search category editing | **Yes** | **Done** (2026-06-28) |
| — | Live reload (SSE/polling) | **No** | Rejected — manual browser refresh |
| — | Print / PDF | **No** | Deferred to v3 |
| — | Dark mode | **No** | Deferred to v3 |

**Implementation order:** 1 → 2 → 3. Year view reuses drill-down API patterns (extend `/api/transactions` with `year` param).

---

## Current state

| Component | Role today |
|-----------|------------|
| `report_data.py` | v1 functions + **`category_transactions()`**, **`search_transactions()`** |
| `web_server.py` | v1 routes + **`GET /api/transactions`**, **`GET /api/search`** |
| `web/static/` | 5 tabs (Overview, Trends, Subscriptions, **Search**, Uncategorised); Overview category rows **clickable** with drill-down panel |
| `analyze.py` | Unchanged in v2 so far |
| `tests/test_report_data.py` | +5 for `category_transactions`, +8 for `search_transactions` |
| `tests/test_web_server.py` | +3 for `/api/transactions`, +5 for `/api/search`, +4 for category API |
| **Total tests** | **55** (was 24 at v1) |

After import or recategorise: **refresh the browser page** — no auto-reload in v2.

---

## Architecture

```
Browser (HTML/CSS/JS)
        │
        │  GET /api/transactions?month=&category=   → Phase 1 (done)
        │  GET /api/search?q=&scope=&month|year=    → Search addendum (done)
        │  GET /api/transactions?year=&category=    → Phase 2 (planned)
        │  GET /api/year?year=YYYY                  → Phase 2 (planned)
        │  GET /api/years                           → Phase 2 (planned)
        │  … existing v1 routes …
        ▼
web_server.py  (http.server on 127.0.0.1:PORT)
        │
        └── report_data.py
              ├── category_transactions()   → done
              ├── search_transactions()     → Search addendum (done)
              ├── year_report()             → Phase 2
              ├── list_years()              → Phase 2
              └── … existing v1 functions …
```

No schema changes to SQLite. All v2 queries filter the existing `transactions` table.

---

## File layout (v2 changes so far)

```
finance_tracker/
├── report_data.py          # + category_transactions(), search_transactions()
├── web_server.py           # + /api/transactions, /api/search routes
├── web/static/
│   ├── index.html          # + drilldown-panel, Search tab
│   ├── style.css           # + drilldown, search toolbar styles
│   └── app.js              # + drilldown + search state/rendering
├── tests/
│   ├── test_report_data.py # + TestCategoryTransactions, TestSearchTransactions
│   └── test_web_server.py  # + transactions, search, category API tests
└── WEB_DASHBOARD_V2_PLAN.md
```

---

## Phase 1 — Transaction drill-down

**User story:** On the Overview tab, click a category row (e.g. "Groceries") and see every transaction in that category for the selected month.

**Status:** Complete (2026-06-21).

### 1.1 `report_data.py` — `category_transactions(conn, month, category)`

Query:

```sql
SELECT date, description, amount, source_account
FROM transactions
WHERE date LIKE ? AND category = ?
ORDER BY date, description
```

**Return shape:**

```python
# Empty (no rows for that month+category)
{"month": "2026-05", "category": "Groceries", "empty": True}

# Populated
{
    "month": "2026-05",
    "category": "Groceries",
    "empty": False,
    "total": -234.56,           # sum of amounts (negative for spending)
    "count": 12,
    "transactions": [
        {
            "date": "2026-05-03",
            "description": "TESCO STORES",
            "amount": -45.67,
            "source_account": "credit_card",
        },
        # … sorted by date, then description
    ],
}
```

**Rules (as built):**

- Include all rows matching `category`, regardless of sign (refunds appear).
- Do **not** re-apply `NON_SPENDING_CATEGORIES` filtering — honour the stored category.
- Sort by `date` ascending, then `description`.

### 1.2 `web_server.py` — `GET /api/transactions`

| Param | Required | Validation |
|-------|----------|------------|
| `month` | yes | `YYYY-MM` (reuse `MONTH_RE`) |
| `category` | yes | non-empty after strip, max 100 chars (`MAX_CATEGORY_LEN`) |

| Case | Response |
|------|----------|
| Missing/invalid `month` | 400 `{"error": "month must be YYYY-MM"}` |
| Missing/empty `category` | 400 `{"error": "category is required"}` |
| Category > 100 chars | 400 `{"error": "category too long"}` |
| Valid, no rows | 200 with `"empty": true` |
| Valid, has rows | 200 with transaction list |
| DB missing | 503 (via `_api`, same as other endpoints) |

URL-encode category names (e.g. `Food+%26+Drink`).

**Example:**

```bash
curl "http://127.0.0.1:8765/api/transactions?month=2026-05&category=Groceries"
```

### 1.3 Frontend — drill-down panel

**UX (as built):**

1. Hint text above category table: "Click a category to see individual transactions."
2. Category rows are clickable (`cursor: pointer`, hover highlight, keyboard Enter/Space).
3. Click opens inline `#drilldown-panel` below the category table.
4. Panel shows: category + month header, transaction count, total, table (date, description, account, amount).
5. **Close** button, or click the same row again to collapse.
6. Click a different category to switch drill-down.
7. Changing the month selector closes any open drill-down.

**State in `app.js`:**

```javascript
drilldown: { month: null, category: null, data: null, loading: false },
currentMonth: null,   // full month report for re-rendering category table
```

**Functions added:** `closeDrilldown()`, `toggleDrilldown(category)`, `renderDrilldownPanel()`.

**Accessibility:** selected row has `aria-expanded="true"`; panel has `role="region"` and dynamic `aria-label`.

### 1.4 Tests (as built)

| Test class | Test | File |
|------------|------|------|
| `TestCategoryTransactions` | `test_returns_transactions` | `test_report_data.py` |
| `TestCategoryTransactions` | `test_total_and_count` | `test_report_data.py` |
| `TestCategoryTransactions` | `test_includes_refunds` | `test_report_data.py` |
| `TestCategoryTransactions` | `test_empty_month_category` | `test_report_data.py` |
| `TestCategoryTransactions` | `test_other_category_excluded` | `test_report_data.py` |
| `TestWebServerApi` | `test_transactions_invalid_month_returns_400` | `test_web_server.py` |
| `TestWebServerApi` | `test_transactions_missing_category_returns_400` | `test_web_server.py` |
| `TestWebServerApi` | `test_transactions_with_data` | `test_web_server.py` |

Run all tests:

```bash
python -m unittest discover -s tests -v   # 32/32 OK
```

### 1.5 Checklist

- [x] **1.1** Add `category_transactions()` to `report_data.py`
- [x] **1.2** Add `/api/transactions` route to `web_server.py`
- [x] **1.3** Clickable category rows + drill-down panel in `app.js` / `index.html` / `style.css`
- [x] **1.4** Unit + integration tests (8 new tests; 32 total)
- [ ] **1.5** Manual: click a category → verify transactions match expectations

### 1.6 Verification performed

1. **Unit tests:** `python -m unittest discover -s tests -v` → 32/32 OK
2. **API:** `GET /api/transactions?month=2026-05&category=Groceries` returns 200 with transaction list when DB populated
3. **Browser UI:** manual smoke test recommended — `python web_server.py` → Overview → click category row

---

## Phase 1 — Completed (2026-06-21)

Phase 1 added transaction drill-down: click a category on the Overview tab to list individual transactions for that month.

### Files added or changed

| File | Change |
|------|--------|
| `report_data.py` | **Added** `category_transactions()` |
| `web_server.py` | **Added** `GET /api/transactions`; `MAX_CATEGORY_LEN = 100` |
| `web/static/index.html` | **Added** category hint, `#drilldown-panel` |
| `web/static/style.css` | **Added** `.drilldown`, `.category-row.clickable`, `.selected` styles |
| `web/static/app.js` | **Added** drill-down state, toggle/close/render functions |
| `tests/test_report_data.py` | **Added** `TestCategoryTransactions` (5 tests) |
| `tests/test_web_server.py` | **Added** 3 `/api/transactions` tests |

At Phase 1 completion, nothing else changed. Later category-editing work updated README and `.cursor/rules/project.mdc` (see addendum below).

---

## Addendum — Editable categories (2026-06-27)

**User story:** Change a transaction category from the local dashboard and have the change apply to every report. The chosen category should apply to all transactions with the same normalized description and survive future imports/recategorisation.

### What shipped

| File | Change |
|------|--------|
| `db_layer.py` | Added `category_overrides`, `normalize_description()`, `resolve_category()`, and description-level update helpers |
| `importer.py` | Uses `resolve_category()` so manual overrides win over keyword rules |
| `recategorise.py` | Re-applies keyword rules while preserving manual overrides |
| `report_data.py` | `category_transactions()` returns `id`/`category`; `uncategorised()` returns a representative `id`; added `category_options()` |
| `web_server.py` | Added `GET /api/categories` and `POST /api/transaction/category` |
| `web/static/app.js` | Added category editors in Overview drill-down, Uncategorised tab, and Search results (2026-06-28), including custom categories |
| `web/static/style.css` | Added compact editor/dropdown/button styling |
| `README.md` | Documented dashboard category editing, overrides, and manual testing |
| `.cursor/rules/project.mdc` | Updated architecture notes for overrides and the local write endpoint |
| `tests/test_db_layer.py` | Added override/helper coverage |
| `tests/test_report_data.py` | Added id/category/category-option coverage |
| `tests/test_web_server.py` | Added category API validation/update coverage |

### API contract

```text
GET /api/categories
POST /api/transaction/category
```

`POST /api/transaction/category` accepts:

```json
{"id": 123, "category": "Groceries"}
```

The server looks up the transaction by `id`, normalizes that transaction's description with `strip().upper()`, updates all rows with the same normalized description, persists the override in `category_overrides`, and returns the updated count.

### Behaviour notes

- Category edits are local-only writes to SQLite; CSV import remains CLI-only.
- Existing categories and DB-only custom categories appear in the dropdown.
- Custom categories are valid immediately, but they count as normal spending unless added to `NON_SPENDING_CATEGORIES`, `NEEDS_CATEGORIES`, or `WANTS_CATEGORIES`.
- Manual overrides survive `python recategorise.py` and future imports that use the same normalized description.
- Deleting `db/finance.db` and rebuilding from CSVs loses overrides because they live in SQLite.

### Testing status

Automated tests passed after implementation:

```bash
python -m unittest discover -s tests -q
# Ran 42 tests ... OK
```

Manual browser checks should be completed by the project owner against their real local data, especially the persistence and edge-case items below.

Manual checks still recommended:

1. Edit a category in the UI, run `python recategorise.py`, and confirm the override is kept.
2. Re-run `python importer.py` over existing CSVs and confirm the override is still used.
3. Move a transaction to/from `Income`, `Transfer`, or `Credit Card Payment` and confirm spend totals shift as expected.
4. Try descriptions/categories with special characters and confirm the UI renders safely.
5. Confirm the server still starts on `127.0.0.1` only and no outbound network behaviour was introduced.

---

## Addendum — Payment search (2026-06-28)

**User story:** Search for payments by merchant or description in the dashboard, scoped to one month, one calendar year, or all imported data.

### What shipped

| File | Change |
|------|--------|
| `report_data.py` | Added `_escape_like_literal()` and `search_transactions()` |
| `web_server.py` | Added `GET /api/search`; `YEAR_RE`, `MAX_SEARCH_QUERY_LEN = 200` |
| `web/static/index.html` | Added **Search** tab with query input, scope selector, month/year dropdowns |
| `web/static/style.css` | Added search toolbar, input, and submit button styles |
| `web/static/app.js` | Added search state, scope controls, submit-on-Enter, results table; later added shared category editor in search results |
| `README.md` | Documented Search tab usage and manual testing |
| `tests/test_report_data.py` | Added `TestSearchTransactions` (8 tests) |
| `tests/test_web_server.py` | Added 5 `/api/search` validation and data tests |

### API contract

```text
GET /api/search?q=BROMCOM&scope=month&month=2026-01
GET /api/search?q=BROMCOM&scope=year&year=2026
GET /api/search?q=BROMCOM&scope=all
```

| Param | Required | Validation |
|-------|----------|------------|
| `q` | yes | non-empty after trim, max 200 chars |
| `scope` | yes | `month`, `year`, or `all` |
| `month` | when `scope=month` | `YYYY-MM` |
| `year` | when `scope=year` | `YYYY` |

**Return shape (populated):**

```python
{
    "query": "BROMCOM",
    "scope": "all",
    "empty": False,
    "total": -4409.0,
    "count": 6,
    "transactions": [
        {
            "id": 1,
            "date": "2025-12-12",
            "description": "BROMCOM BROMCOM UNITED KINGDOM",
            "amount": -80.0,
            "source_account": "credit_card",
            "category": "Education & Childcare",
        },
        # … sorted by date, then description
    ],
}
```

### Behaviour notes

- Searches **transaction descriptions only** (case-insensitive substring match).
- User input is escaped so `%` and `_` are treated as literal characters, not SQL wildcards.
- Includes all matching rows in scope, including refunds; `total` is the net sum of amounts.
- Year options in the UI are derived from imported months (`state.months`).

### Search category editing (2026-06-28)

Reuses the same category editor as Overview drill-down and Uncategorised — no new API or backend logic.

| File | Change |
|------|--------|
| `web/static/app.js` | Search results render `renderCategoryEditor()` per row; `saveTransactionCategory()` and `refreshAfterCategoryChange()` refresh active search after save |

**Behaviour:**

- Each search result row shows category dropdown + **Custom…** + **Save** (same as other tabs).
- Save shows **Saving…** state, then re-fetches the active search so updated categories appear on all matching rows.
- Changes apply to all transactions with the same normalized description via existing `POST /api/transaction/category`.

**Manual check:** search `BROMCOM` (All data) → change category on one row → Save → all BROMCOM rows show the new category.

### Testing status

```bash
python -m unittest discover -s tests -v
# Ran 55 tests ... OK
```

Manual check: open the **Search** tab, search `BROMCOM` with **All data**, confirm count and total match expectations.

---

## Phase 2 — Year view

**User story:** See annual spending totals, a month-by-month breakdown, and category totals for a calendar year — in both CLI and dashboard.

**Status:** Not started. **Next step.**

### 2.1 `report_data.py` — new functions

#### `list_years(conn) -> list[str]`

```python
["2025", "2026"]   # sorted ascending, derived from transaction dates
```

#### `year_report(conn, year: str) -> dict`

Query all rows where `date LIKE '{year}-%'`.

**Return shape:**

```python
# Empty
{"year": "2026", "empty": True}

# Populated
{
    "year": "2026",
    "empty": False,
    "total_spend": -52340.12,
    "income": 39480.00,
    "net": -12860.12,
    "months": ["2026-01", "2026-02", ...],          # only months with data
    "monthly_spend": {"2026-01": -4100.0, ...},     # per-month spending total
    "monthly_income": {"2026-01": 3200.0, ...},     # per-month income
    "categories": [
        {"name": "Housing", "amount": -16804.20, "pct": 32.1},
        # sorted by amount ascending (highest spend first)
    ],
    "benchmark": {
        "needs": ..., "wants": ..., "other": ...,
        "needs_pct": ..., "wants_pct": ...,
        "savings_rate": ...,
    },
    "top_merchants": [
        {"description": "...", "amount": -...},
        # max 10 for the full year
    ],
}
```

Reuse `category_breakdown()` on year rows. Benchmark formula identical to `month_report` but scoped to the year.

### 2.2 `analyze.py` — `--year YYYY` flag

```bash
python analyze.py --year 2026
```

Add `print_year_report(conn, year)` formatter (mirror `print_month_report` structure). Mutually exclusive with `--month`.

Default report (`python analyze.py` with no flags) stays unchanged — year view is opt-in only.

### 2.3 `web_server.py` — routes

| Route | Handler |
|-------|---------|
| `GET /api/years` | `list_years(conn)` |
| `GET /api/year?year=YYYY` | `year_report(conn, year)` |

Validation: `year` must match `^\d{4}$`. Invalid → 400 `{"error": "year must be YYYY"}`.

Add `YEAR_RE = re.compile(r"^\d{4}$")` alongside existing `MONTH_RE`.

### 2.4 Frontend — Year tab

Add a fifth tab **Year** (after Overview).

Contents:

- Year dropdown from `GET /api/years` (default: latest year with data).
- Summary cards (spend, income, net) — reuse `renderCards()`.
- Category breakdown table — rows clickable for year-scoped drill-down (see 2.5).
- Monthly bar chart via **CSS only**: flex/grid of vertical bars scaled to max monthly spend.
- 50/30/20 benchmark section — reuse benchmark renderer.

### 2.5 Drill-down for year view

Extend Phase 1 API:

```
GET /api/transactions?year=2026&category=Groceries
```

Mutually exclusive with `month` param. Returns all transactions in that category for the full year. Extend `category_transactions()` with optional `year` kwarg (or separate query branch).

### 2.6 Tests

| Test | File |
|------|------|
| `list_years` sorted, deduplicated | `test_report_data.py` |
| `year_report` totals, benchmark, empty year | `test_report_data.py` |
| `/api/year` 400/200, `/api/years` | `test_web_server.py` |
| Year-scoped `/api/transactions?year=&category=` | `test_web_server.py` |
| CLI `--year` output sanity | manual |

### 2.7 Checklist

- [ ] **2.1** Add `list_years()`, `year_report()` to `report_data.py`
- [ ] **2.2** Extend `category_transactions()` for optional `year` param
- [ ] **2.3** Add `/api/years`, `/api/year` routes; extend `/api/transactions` for year scope
- [ ] **2.4** Add `--year` to `analyze.py` + `print_year_report()`
- [ ] **2.5** Year tab in frontend + CSS monthly bars
- [ ] **2.6** Tests
- [ ] **2.7** Manual: compare `python analyze.py --year 2026` totals with Year tab

---

## Phase 3 — Polish (optional)

Low-priority items from the v1 post-implementation review. Ship when convenient; none block v2.

| Item | Action |
|------|--------|
| Benchmark `%` sign mismatch (CLI negative vs web `Math.abs`) | Pick one convention; update `print_month_report` or remove `Math.abs` in `fmtPct()` — cosmetic only |
| Static 404s return JSON | Optionally serve minimal HTML 404 for `/static/*` misses; keep JSON for `/api/*` |
| `recategorise.py` missing from `.cursor/rules/project.mdc` | One-line addition to Architecture section |
| `WEB_DASHBOARD_PLAN.md` cross-link | Add pointer to this v2 plan |
| `README.md` | Document drill-down, year tab, manual refresh after import |

### Checklist

- [ ] **3.1** Align benchmark % display (optional)
- [ ] **3.2** HTML 404 for static files (optional)
- [ ] **3.3** Document `recategorise.py` in project rules
- [ ] **3.4** Cross-link v1 and v2 plan docs
- [ ] **3.5** Update README for v2 features

---

## Deferred (not in v2)

| Feature | Notes |
|---------|-------|
| **Live reload (SSE)** | Rejected — refresh browser after `importer.py` / `recategorise.py` |
| **Live reload (polling)** | Rejected |
| Print / save as PDF | Browser `@media print` + Print button — v3 if needed |
| Dark mode | CSS variable toggle + `localStorage` — v3 if needed |

---

## Out of scope (unchanged from v1)

- Editing categories from the browser
- Running `importer.py` from the browser
- User authentication / LAN binding
- `--export` from the web UI
- Mobile-first redesign
- Chart libraries (line charts, pie charts) — CSS bars remain sufficient
- WebSocket / SSE / polling for auto-refresh
- Automated browser/E2E tests

---

## Testing strategy

Stdlib `unittest` only:

| Layer | What's tested |
|-------|---------------|
| `test_report_data.py` | Pure functions with in-memory SQLite + synthetic rows |
| `test_web_server.py` | Routes, validation errors, security (path traversal, bind address) |
| Manual | Drill-down UX, year CLI parity (Phase 2) |

**Current:** 32 automated tests (24 v1 + 8 Phase 1).

**Target after v2 complete:** ~40 automated tests (estimate: +6–8 for year view).

Run all tests:

```bash
python -m unittest discover -s tests -v
```

---

## Documentation updates (end of v2)

| File | Change |
|------|--------|
| `README.md` | Drill-down, Search tab, year tab, manual refresh note |
| `.cursor/rules/project.mdc` | New API routes, `category_transactions`, `search_transactions`, year functions |
| `WEB_DASHBOARD_PLAN.md` | Add "See also: WEB_DASHBOARD_V2_PLAN.md" at top |
| `WEB_DASHBOARD_V2_PLAN.md` | Mark phases/addenda complete with dates |

---

## Implementation order (master checklist)

- [x] **Phase 1** — Transaction drill-down (`category_transactions`, `/api/transactions`, clickable rows)
- [x] **Addendum** — Editable categories (`category_overrides`, `/api/categories`, `POST /api/transaction/category`, UI editors)
- [x] **Addendum** — Payment search (`search_transactions`, `/api/search`, Search tab)
- [x] **Addendum** — Search category editing (reuse editor in Search results)
- [ ] **Phase 2** — Year view (`year_report`, `--year`, Year tab, year drill-down)
- [ ] **Phase 3** — Optional polish + docs
- [ ] **Docs** — README, project rules, cross-links

---

## Success criteria

### Phase 1 (done)

- [x] Clicking a category shows correct transactions for the selected month; totals match sum of rows
- [x] All v1 tests still pass; new tests cover `/api/transactions` and `category_transactions`
- [x] No new pip dependencies; server still binds `127.0.0.1` only; no outbound network calls

### Category editing addendum (done)

- [x] Category changes can be saved from Overview drill-down, Uncategorised tab, and Search results
- [x] Saves apply to all rows with the same normalized description and persist in `category_overrides`
- [x] Automated tests cover DB override helpers, API validation/update behaviour, and report payload changes
- [ ] Manual owner check: persistence through `recategorise.py` and re-import
- [ ] Manual owner check: non-spending category edge cases and special-character rendering

### Payment search addendum (done)

- [x] Search tab finds transactions by description substring
- [x] Month, year, and all-data scopes filter correctly
- [x] Literal `%` and `_` in search text do not act as wildcards
- [x] Automated tests cover `search_transactions` and `/api/search` validation
- [x] Search results reuse shared category editor; active search refreshes after save
- [ ] Manual owner check: search a known merchant (e.g. BROMCOM) across scopes
- [ ] Manual owner check: change category from Search tab and confirm all matching rows update

### Remaining (Phases 2–3)

- [ ] `python analyze.py --year 2026` and the Year tab show the same annual totals
- [ ] Year category drill-down works via `/api/transactions?year=&category=`
- [ ] README documents drill-down and manual refresh workflow

---

## Estimated effort

| Phase | Rough size | Status |
|-------|------------|--------|
| 1 — Drill-down | ~150 lines Python + ~80 lines JS/CSS | **Done** |
| Addendum — Editable categories | ~200 lines Python/JS/CSS + tests/docs | **Done** |
| Addendum — Payment search | ~150 lines Python/JS/CSS + tests/docs | **Done** |
| Addendum — Search category edit | ~30 lines JS (frontend only) | **Done** |
| 2 — Year view | ~120 lines Python + ~100 lines JS + CLI formatter | Not started |
| 3 — Polish | ~20 lines scattered + docs | Not started |

**Next step:** Phase 2 — year view.
