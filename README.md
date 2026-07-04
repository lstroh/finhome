# Personal Finance Tracker

A private, local-only tool to track and analyse your bank and credit card
spending. Nothing here ever connects to the internet or sends data
anywhere — your transactions live in a single SQLite file on your own
machine.

## How it works

1. You download CSV exports from your bank and credit card provider
2. You drop them into `data/accounts/` (bank) or `data/credit_card/` (card)
3. Run `python3 importer.py` — it reads every CSV, categorises each
   transaction, and stores it in `db/finance.db`
4. Run `python3 analyze.py` — it prints a report: this month's spending,
   month-over-month trends, anomalies, and detected subscriptions
   (or run `python3 web_server.py` for the same data in a browser)

Re-running the importer on the same files (or files with overlapping
date ranges) never creates duplicates — each transaction is fingerprinted
so it's only stored once.

## First-time setup

No installation needed — this only uses Python's standard library.
Just make sure you have Python 3.8+:

```bash
python3 --version
```

## Folder structure

```
finance_tracker/
├── data/
│   ├── accounts/        <- put your bank CSV exports here (one file per account)
│   └── credit_card/     <- put your credit card CSV exports here
├── db/
│   └── finance.db       <- created automatically; your data lives here
├── rules/
│   └── categories.py    <- editable keyword rules for categorisation
├── importer.py           <- run this first to load your data
├── analyze.py            <- run this to see reports in the terminal
├── web_server.py         <- run this for the browser dashboard
└── web/static/           <- dashboard HTML/CSS/JS (served locally)
```

## File formats expected

**Bank CSV** (tab or comma separated):
```
Transaction Date, Transaction Type, Sort Code, Account Number, Transaction Description, Debit Amount, Credit Amount, Balance
```

**Credit card CSV**:
```
Date, Description, Amount
```

If your bank/card changes its export format, tell Claude and the
importer can be adjusted.

## Monthly/weekly routine

Each time you want a fresh check-in:

1. Download new CSVs from your bank/card (covering since your last download)
2. Drop them into `data/accounts/` and `data/credit_card/`
   (you can keep old files there too — duplicates are auto-skipped)
3. Run:
   ```bash
   python3 importer.py
   python3 analyze.py
   ```

That's it. The default `analyze.py` report gives you the latest month,
trends, and subscriptions in one go.

## All commands

```bash
python3 importer.py                   # import every CSV in data/
python3 analyze.py                    # full report: latest month + trends + subscriptions
python3 analyze.py --month 2026-05    # report for one specific month
python3 analyze.py --trends           # month-over-month table only
python3 analyze.py --subscriptions    # list of detected recurring charges
python3 analyze.py --uncategorised    # see what needs a category rule
python3 analyze.py --export out.csv   # export everything to a flat CSV
python3 web_server.py                 # open http://127.0.0.1:8765 in your browser
python3 web_server.py --port 9000     # use a different port
python3 recategorise.py               # re-apply keyword rules (keeps manual overrides)
```

## Testing

Automated tests (stdlib `unittest`, synthetic data only — never touches
your real `db/finance.db`):

```bash
python3 -m unittest discover -s tests -v
```

**Automated coverage includes:** report calculations, category drill-down
API, payment search (`GET /api/search`), category editing
(`POST /api/transaction/category`), override persistence in `db_layer`,
and web server security (localhost bind, path traversal, error responses).

**Manual checks recommended** (not fully automated):

| Area | What to verify |
|------|----------------|
| Overview drill-down | Click a category → change category → totals/benchmark refresh |
| Search tab | Search by merchant/description → scope Month/Year/All data → results and total match |
| Search category edit | Change category from Search results → Save → all matching descriptions update |
| Uncategorised tab | Assign a category → row disappears, banner count drops |
| Custom category | Type a new name via **Custom…** → appears in reports and dropdown |
| Persistence | After a UI edit, run `recategorise.py` and re-import CSVs → override kept |
| Edge cases | Re-categorise to/from Income/Transfer/Credit Card Payment → spend totals shift; special characters in descriptions render safely |

Restart `web_server.py` after code updates, then hard-refresh the browser.

## Web dashboard

After importing your data, start the local dashboard:

```bash
python3 web_server.py
```

Open **http://127.0.0.1:8765** in your browser. The server binds to
`127.0.0.1` only — your data is never exposed to other machines on the
network. Refresh the page after re-running `importer.py` to see new data.

The dashboard mirrors `analyze.py`: overview with month selector, trends,
subscriptions, uncategorised transactions, and a **Search** tab. Search
matches transaction descriptions only (e.g. `BROMCOM`) and can be scoped
to one month, one calendar year, or all imported data. You can also
**edit categories in the browser** — click a category on the Overview tab to
drill down into individual transactions, use the Uncategorised tab, or
change a category from Search results. Changing a category updates all
transactions with the same description across every month and is remembered
on future imports.

Import stays on the CLI (`importer.py`). Keyword rule changes use
`recategorise.py` or a full DB rebuild (see below).

**Search tab:** enter a merchant or description, choose **Month**, **Year**,
or **All data**, then click **Search** (or press Enter). Results show date,
description, account, amount, and an editable category column, plus a count
and net total. Refunds appear if their description matches. Use the category
dropdown (or **Custom…**) and **Save** to re-categorise a merchant; the change
applies to all transactions with the same description, same as on Overview
and Uncategorised.

## Tuning categorisation

Open `rules/categories.py`. Each category is a list of keywords —
if a transaction description contains the keyword, it gets that
category. Run `python3 analyze.py --uncategorised` to see what's
falling through the cracks, then add keywords for those merchants.

**From the dashboard:** on the Overview tab, click a category row to
see its transactions and change a category from the dropdown (or pick
**Custom…** for a new name). The Uncategorised tab and **Search** tab
use the same editor. A change applies to every transaction with that
exact description and is stored as an override so it survives re-imports
and `python3 recategorise.py`.

**From the CLI:** after editing keyword rules in `rules/categories.py`,
run `python3 recategorise.py` to re-apply rules to existing rows.
Manual overrides from the dashboard are kept — keyword rules only apply
to descriptions you have not overridden. Alternatively, delete
`db/finance.db` and re-run `python3 importer.py` to rebuild from CSVs
(overrides are lost unless you re-assign them in the UI).

Custom categories appear in reports immediately but do not affect the
50/30/20 benchmark until you add them to `NEEDS_CATEGORIES` or
`WANTS_CATEGORIES` in `rules/categories.py`.

## Privacy

- No network calls, no telemetry, no cloud sync
- All data stored in `db/finance.db` — a single file you control
- Delete that file any time to wipe everything
- Consider keeping the `finance_tracker/` folder somewhere encrypted
  (e.g. inside a FileVault/BitLocker-protected folder) since it contains
  your real transaction history once you load real files in
