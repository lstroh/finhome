"""Re-apply CATEGORY_RULES to all transactions in the database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from categoriser import categorise
from db_layer import get_connection, resolve_category


def main():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, description, category FROM transactions"
    ).fetchall()
    updated = 0
    for tid, desc, old_cat in rows:
        new_cat = resolve_category(conn, desc, categorise)
        if new_cat != old_cat:
            conn.execute(
                "UPDATE transactions SET category = ? WHERE id = ?",
                (new_cat, tid),
            )
            updated += 1
    conn.commit()
    remaining = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE category = 'Uncategorised'"
    ).fetchone()[0]
    print(f"Updated {updated} transactions")
    print(f"Remaining uncategorised: {remaining}")


if __name__ == "__main__":
    main()
