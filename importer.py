"""
Importers for bank and credit card CSV exports.

Bank format:
    Transaction Date, Transaction Type, Sort Code, Account Number,
    Transaction Description, Debit Amount, Credit Amount, Balance

Credit card format:
    Date, Description, Amount

Both importers:
  - Normalise dates to ISO format (YYYY-MM-DD)
  - Normalise amounts to a single signed float (negative = spent, positive = received)
  - Tag every row with a source_account (derived from filename)
  - Categorise every row
  - Insert into SQLite, skipping anything already imported (by content hash)
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_layer import get_connection, insert_transaction, resolve_category
from categoriser import categorise


def parse_date(raw: str) -> str:
    """
    Try common UK date formats and return ISO YYYY-MM-DD.
    Raises ValueError if nothing matches, so bad data is never silently
    misfiled into the wrong month.
    """
    raw = raw.strip()
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d/%m/%y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Could not parse date: '{raw}'")


def parse_amount(raw: str) -> float:
    """
    Strip currency symbols/commas and convert to float.
    Raises ValueError on anything that doesn't look like a clean amount —
    this is deliberately strict. A silently-wrong huge number is far worse
    than a row that gets flagged as an error and skipped.
    """
    if raw is None:
        return 0.0
    cleaned = raw.replace("£", "").replace(",", "").strip()
    if cleaned in ("", "-"):
        return 0.0
    value = float(cleaned)  # will raise ValueError if not a clean number
    # Sanity bound: a single personal transaction over £100,000 is almost
    # certainly a parsing error (column misalignment, stray comma, etc.)
    # rather than a real transaction. Flag it instead of silently importing.
    if abs(value) > 100_000:
        raise ValueError(
            f"Amount {value:,.2f} exceeds sanity threshold (£100,000) — "
            f"likely a parsing error (check for commas/quoting issues in "
            f"the source row), not a genuine transaction."
        )
    return value


def account_name_from_filename(path: Path) -> str:
    """e.g. 'current_account_2026.csv' -> 'current_account_2026'"""
    return path.stem


def detect_delimiter(path: Path) -> str:
    """Bank exports may be comma or tab separated — detect which."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        return dialect.delimiter
    except csv.Error:
        return ","  # fall back to comma


def import_bank_csv(path: Path, conn) -> dict:
    """
    Returns a dict with counts: {'inserted': N, 'skipped': N, 'errors': [...]}
    """
    account = account_name_from_filename(path)
    inserted, skipped, errors = 0, 0, []
    delimiter = detect_delimiter(path)

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row_num, row in enumerate(reader, start=2):
            try:
                date = parse_date(row["Transaction Date"])
                description = row["Transaction Description"].strip()
                debit = parse_amount(row.get("Debit Amount", "") or "")
                credit = parse_amount(row.get("Credit Amount", "") or "")
                amount = credit - debit  # signed: spending is negative
                balance_raw = row.get("Balance", "")
                balance = parse_amount(balance_raw) if balance_raw else None

                category = resolve_category(conn, description, categorise)

                was_inserted = insert_transaction(
                    conn, date, description, amount, account, category, balance
                )
                if was_inserted:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                row_date = row.get("Transaction Date", "?")
                errors.append(f"Row {row_num} (date: {row_date}): {e}")

    conn.commit()
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


def import_credit_card_csv(path: Path, conn, spending_is_positive: bool = None) -> dict:
    """
    Credit card CSVs vary on whether purchases show as positive or negative
    numbers. If spending_is_positive is None, we auto-detect: most
    transactions in a card statement are purchases, so whichever sign is
    in the majority is assumed to be spending, and we flip if needed so
    that spending is always stored as negative (consistent with the bank
    format).
    """
    account = "credit_card_" + account_name_from_filename(path)
    inserted, skipped, errors = 0, 0, []
    delimiter = detect_delimiter(path)

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row_num, row in enumerate(reader, start=2):
            try:
                date = parse_date(row["Date"])
                description = row["Description"].strip()
                amount = parse_amount(row["Amount"])
                rows.append((row_num, date, description, amount))
            except Exception as e:
                row_date = row.get("Date", "?")
                errors.append(f"Row {row_num} (date: {row_date}): {e}")

    if not rows:
        return {"inserted": 0, "skipped": 0, "errors": errors}

    if spending_is_positive is None:
        positive_count = sum(1 for *_, amt in rows if amt > 0)
        spending_is_positive = positive_count > len(rows) / 2

    for row_num, date, description, raw_amount in rows:
        # Normalise so spending is always negative, payments/refunds positive
        amount = raw_amount if not spending_is_positive else -raw_amount
        category = resolve_category(conn, description, categorise)
        was_inserted = insert_transaction(
            conn, date, description, amount, account, category, balance=None
        )
        if was_inserted:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    return {
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "detected_spending_is_positive": spending_is_positive,
    }


def import_all(data_dir: Path):
    """
    Scans data/accounts/*.csv as bank files and data/credit_card/*.csv as
    credit card files, imports everything, and prints a summary.
    """
    conn = get_connection()
    total_inserted, total_skipped = 0, 0
    all_errors = []

    accounts_dir = data_dir / "accounts"
    cc_dir = data_dir / "credit_card"

    print("=" * 60)
    print("IMPORTING BANK ACCOUNT FILES")
    print("=" * 60)
    for csv_file in sorted(accounts_dir.glob("*.csv")):
        result = import_bank_csv(csv_file, conn)
        total_inserted += result["inserted"]
        total_skipped += result["skipped"]
        all_errors.extend(result["errors"])
        print(f"  {csv_file.name}: {result['inserted']} new, "
              f"{result['skipped']} already imported, "
              f"{len(result['errors'])} errors")

    print()
    print("=" * 60)
    print("IMPORTING CREDIT CARD FILES")
    print("=" * 60)
    for csv_file in sorted(cc_dir.glob("*.csv")):
        result = import_credit_card_csv(csv_file, conn)
        total_inserted += result["inserted"]
        total_skipped += result["skipped"]
        all_errors.extend(result["errors"])
        sign_note = ""
        if "detected_spending_is_positive" in result:
            sign_note = (f" (auto-detected: spending stored as "
                         f"{'positive->flipped to negative' if result['detected_spending_is_positive'] else 'already negative'})")
        print(f"  {csv_file.name}: {result['inserted']} new, "
              f"{result['skipped']} already imported, "
              f"{len(result['errors'])} errors{sign_note}")

    conn.close()

    print()
    print("=" * 60)
    print(f"TOTAL: {total_inserted} new transactions imported, "
          f"{total_skipped} duplicates skipped")
    if all_errors:
        print(f"\n{len(all_errors)} ERRORS encountered:")
        for err in all_errors[:20]:
            print(f"  - {err}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more")
    print("=" * 60)


if __name__ == "__main__":
    data_dir = Path(__file__).parent / "data"
    import_all(data_dir)
