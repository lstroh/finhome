"""
analyze.py — generates a spending report from everything imported so far.

USAGE
-----
  python3 analyze.py                  Full report: latest month + trends
  python3 analyze.py --month 2026-05  Report for a specific month
  python3 analyze.py --uncategorised  List transactions needing category rules
  python3 analyze.py --subscriptions  List detected recurring subscriptions
  python3 analyze.py --export FILE    Export full categorised data to CSV
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_layer import get_connection
from report_data import (
    get_all_transactions,
    month_over_month,
    month_report,
    subscriptions,
    summary,
    uncategorised,
)


def fmt_gbp(amount: float) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}£{abs(amount):,.2f}"


def print_uncategorised(conn):
    rows = uncategorised(conn)
    if not rows:
        print("Nothing uncategorised — every transaction matched a rule. 🎉")
        return
    print(f"{len(rows)} UNIQUE uncategorised descriptions found:\n")
    for item in rows:
        print(f"  {fmt_gbp(item['amount']):>12}  {item['description']}")
    print(f"\nAdd keywords for these in rules/categories.py, then re-run "
          f"analyze.py (no need to re-import).")


def print_subscriptions(conn):
    data = subscriptions(conn)
    if not data["items"]:
        print("No recurring subscriptions detected yet (need 3+ months of data).")
        return
    print(f"{len(data['items'])} LIKELY RECURRING SUBSCRIPTIONS detected:\n")
    for item in data["items"]:
        print(f"  {fmt_gbp(item['avg_amount']):>10} / charge   "
              f"seen in {item['months_seen']} months   {item['description']}")
    print(f"\n  Estimated total: {fmt_gbp(data['estimated_monthly'])} per month "
          f"({fmt_gbp(data['estimated_yearly'])} per year)")
    print("\n  Review this list — cancel anything you no longer use.")


def print_month_report(conn, target_month: str):
    data = month_report(conn, target_month)
    if data["empty"]:
        print(f"No transactions found for {target_month}.")
        return

    print("=" * 60)
    print(f"MONTHLY REPORT: {target_month}")
    print("=" * 60)

    print(f"\nTotal spend:   {fmt_gbp(data['total_spend'])}")
    print(f"Total income:  {fmt_gbp(data['income'])}")
    print(f"Net:           {fmt_gbp(data['net'])}")

    print("\nSPENDING BY CATEGORY (highest first):")
    for cat in data["categories"]:
        bar = "█" * int(abs(cat["pct"]) / 4)
        print(f"  {cat['name']:<22} {fmt_gbp(cat['amount']):>12}  "
              f"({cat['pct']:5.1f}%)  {bar}")

    b = data["benchmark"]
    if data["total_spend"]:
        print(f"\n50/30/20 BENCHMARK (target: 50% needs / 30% wants / 20% savings):")
        print(f"  Needs:  {fmt_gbp(b['needs']):>12}  ({b['needs_pct']:5.1f}% of spend)")
        print(f"  Wants:  {fmt_gbp(b['wants']):>12}  ({b['wants_pct']:5.1f}% of spend)")
        if b["savings_rate"] is not None:
            print(f"  Implied savings rate: {b['savings_rate']:.1f}% of income")

    print(f"\nTOP 10 MERCHANTS THIS MONTH:")
    for m in data["top_merchants"]:
        print(f"  {fmt_gbp(m['amount']):>12}  {m['description']}")


def print_month_over_month(conn):
    data = month_over_month(conn)
    if data.get("empty"):
        print("No data imported yet. Run importer.py first.")
        return
    if data.get("insufficient_months"):
        print("Need at least 2 months of data for month-over-month comparison.")
        return

    months = data["months"]
    print("=" * 60)
    print("MONTH-OVER-MONTH SPENDING BY CATEGORY")
    print("=" * 60)

    header = f"{'Category':<22}" + "".join(f"{m:>12}" for m in months)
    print(header)
    print("-" * len(header))
    for cat in data["categories"]:
        line = f"{cat:<22}"
        for m in months:
            val = data["grid"][cat][m]
            line += f"{fmt_gbp(val):>12}" if val else f"{'—':>12}"
        print(line)

    print("-" * len(header))
    totals_line = f"{'TOTAL':<22}"
    for m in months:
        totals_line += f"{fmt_gbp(data['totals'][m]):>12}"
    print(totals_line)

    if len(months) >= 3:
        latest = months[-1]
        prior_count = len(months) - 1
        print(f"\nANOMALIES IN {latest} (vs. average of prior {prior_count} months):")
        if data["anomalies"]:
            for a in data["anomalies"]:
                print(f"  {a['category']:<22} {a['direction']} {a['change_pct']:.0f}% "
                      f"(avg {fmt_gbp(a['prior_avg'])} -> {fmt_gbp(a['latest'])})")
        else:
            print("  No significant anomalies detected.")


def export_csv(conn, out_path: str):
    import csv as csv_module
    out = Path(out_path)
    if out.parent != Path("."):
        out.parent.mkdir(parents=True, exist_ok=True)
    rows = get_all_transactions(conn)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(["Date", "Description", "Amount", "Account", "Category", "Balance"])
        for _, date, desc, amount, account, category, balance in rows:
            writer.writerow([date, desc, amount, account, category, balance])
    print(f"Exported {len(rows)} transactions to {out_path}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="Analyze your bank/credit card spending.")
    parser.add_argument("--month", help="Report for a specific month, e.g. 2026-05")
    parser.add_argument("--uncategorised", action="store_true", help="List uncategorised transactions")
    parser.add_argument("--subscriptions", action="store_true", help="List detected subscriptions")
    parser.add_argument("--export", help="Export all data to a CSV file")
    parser.add_argument("--trends", action="store_true", help="Show month-over-month trends only")
    args = parser.parse_args()

    conn = get_connection()

    if args.uncategorised:
        print_uncategorised(conn)
    elif args.subscriptions:
        print_subscriptions(conn)
    elif args.export:
        export_csv(conn, args.export)
    elif args.month:
        print_month_report(conn, args.month)
    elif args.trends:
        print_month_over_month(conn)
    else:
        data = summary(conn)
        if data["empty"]:
            print("No data imported yet.")
            print("1. Drop your bank CSVs into data/accounts/")
            print("2. Drop your credit card CSVs into data/credit_card/")
            print("3. Run: python3 importer.py")
            print("4. Then re-run: python3 analyze.py")
            conn.close()
            return

        print_month_report(conn, data["latest_month"])
        print()
        print_month_over_month(conn)
        print()
        print_subscriptions(conn)

        if data["uncategorised_count"]:
            print(f"\n⚠️  {data['uncategorised_count']} transactions are Uncategorised. "
                  f"Run 'python3 analyze.py --uncategorised' to see them.")

    conn.close()


if __name__ == "__main__":
    main()
