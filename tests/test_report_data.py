"""Unit tests for report_data.py — stdlib unittest only."""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db_layer import make_hash, set_category_budget
from report_data import (
    category_options,
    category_transactions,
    find_duplicates,
    list_months,
    month_over_month,
    month_report,
    month_transactions,
    month_vs_year_avg,
    search_transactions,
    subscriptions,
    summary,
    uncategorised,
    validate_duplicate_removal,
    year_avg_baseline,
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


class TestListMonths(unittest.TestCase):
    def test_sorted(self):
        conn = make_test_conn()
        insert_row(conn, "2026-06-01", "A", -10, "Groceries")
        insert_row(conn, "2026-04-01", "B", -10, "Groceries")
        insert_row(conn, "2026-05-01", "C", -10, "Groceries")
        conn.commit()
        self.assertEqual(list_months(conn), ["2026-04", "2026-05", "2026-06"])


class TestMonthReport(unittest.TestCase):
    def setUp(self):
        self.conn = make_test_conn()
        insert_row(self.conn, "2026-05-01", "TESCO", -100, "Groceries")
        insert_row(self.conn, "2026-05-15", "SALARY", 3000, "Income")
        insert_row(self.conn, "2026-05-20", "F/FLOW", -500, "Transfer")
        self.conn.commit()

    def test_totals(self):
        data = month_report(self.conn, "2026-05")
        self.assertFalse(data["empty"])
        self.assertEqual(data["total_spend"], -100)
        self.assertEqual(data["income"], 3000)
        self.assertEqual(data["net"], 2900)

    def test_excludes_non_spending(self):
        data = month_report(self.conn, "2026-05")
        cats = [c["name"] for c in data["categories"]]
        self.assertIn("Groceries", cats)
        self.assertNotIn("Transfer", cats)

    def test_empty_month(self):
        data = month_report(self.conn, "2026-01")
        self.assertTrue(data["empty"])

    def test_benchmark(self):
        insert_row(self.conn, "2026-05-02", "NETFLIX", -30, "Subscriptions")
        self.conn.commit()
        data = month_report(self.conn, "2026-05")
        b = data["benchmark"]
        # Matches analyze.py: abs(needs) / total_spend * 100 (total_spend is negative)
        self.assertAlmostEqual(b["needs_pct"], abs(b["needs"]) / data["total_spend"] * 100)
        self.assertIsNotNone(b["savings_rate"])


class TestMonthOverMonth(unittest.TestCase):
    def test_grid_and_totals(self):
        conn = make_test_conn()
        insert_row(conn, "2026-04-01", "TESCO", -100, "Groceries")
        insert_row(conn, "2026-05-01", "TESCO", -120, "Groceries")
        insert_row(conn, "2026-06-01", "TESCO", -110, "Groceries")
        conn.commit()
        data = month_over_month(conn)
        self.assertFalse(data["empty"])
        self.assertEqual(len(data["months"]), 3)
        self.assertEqual(data["grid"]["Groceries"]["2026-05"], -120)
        self.assertEqual(data["totals"]["2026-04"], -100)

    def test_insufficient_months(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -100, "Groceries")
        conn.commit()
        data = month_over_month(conn)
        self.assertTrue(data["insufficient_months"])

    def test_anomaly_detected(self):
        conn = make_test_conn()
        for m, amt in [("2026-04", -50), ("2026-05", -50), ("2026-06", -85)]:
            insert_row(conn, f"{m}-01", "UBER", amt, "Transport")
        conn.commit()
        data = month_over_month(conn)
        transport_anomalies = [a for a in data["anomalies"] if a["category"] == "Transport"]
        self.assertEqual(len(transport_anomalies), 1)
        self.assertEqual(transport_anomalies[0]["direction"], "up")

    def test_anomaly_skips_small_change(self):
        conn = make_test_conn()
        for m, amt in [("2026-04", -50), ("2026-05", -50), ("2026-06", -55)]:
            insert_row(conn, f"{m}-01", "UBER", amt, "Transport")
        conn.commit()
        data = month_over_month(conn)
        self.assertEqual(data["anomalies"], [])


class TestYearAvgBaseline(unittest.TestCase):
    def test_12_month_groceries_average(self):
        conn = make_test_conn()
        for i in range(12):
            month = f"2025-{i + 1:02d}"
            insert_row(conn, f"{month}-01", "TESCO", -200, "Groceries")
        conn.commit()
        data = year_avg_baseline(conn)
        self.assertFalse(data["empty"])
        self.assertEqual(data["month_count"], 12)
        self.assertEqual(data["window_start"], "2025-01")
        self.assertEqual(data["window_end"], "2025-12")
        self.assertAlmostEqual(data["category_avgs"]["Groceries"], -200)
        self.assertAlmostEqual(data["total_spend_avg"], -200)

    def test_partial_window(self):
        conn = make_test_conn()
        for m in ["2026-04", "2026-05", "2026-06"]:
            insert_row(conn, f"{m}-01", "TESCO", -300, "Groceries")
        conn.commit()
        data = year_avg_baseline(conn)
        self.assertEqual(data["month_count"], 3)
        self.assertAlmostEqual(data["category_avgs"]["Groceries"], -300)

    def test_excludes_transfer_counts_income(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -100, "Groceries")
        insert_row(conn, "2026-05-02", "F/FLOW", -500, "Transfer")
        insert_row(conn, "2026-05-03", "SALARY", 3000, "Income")
        insert_row(conn, "2026-06-01", "SALARY", 3000, "Income")
        conn.commit()
        data = year_avg_baseline(conn)
        self.assertNotIn("Transfer", data["category_avgs"])
        self.assertAlmostEqual(data["income_avg"], 3000)
        self.assertAlmostEqual(data["total_spend_avg"], -50)

    def test_empty_db(self):
        conn = make_test_conn()
        self.assertTrue(year_avg_baseline(conn)["empty"])


class TestMonthVsYearAvg(unittest.TestCase):
    def test_selected_month_comparison(self):
        conn = make_test_conn()
        for m, amt in [("2026-04", -300), ("2026-05", -300), ("2026-06", -400)]:
            insert_row(conn, f"{m}-01", "TESCO", amt, "Groceries")
        conn.commit()
        data = month_vs_year_avg(conn, "2026-06")
        self.assertFalse(data["empty"])
        self.assertEqual(data["selected_month"], "2026-06")
        groceries = next(c for c in data["categories"] if c["name"] == "Groceries")
        self.assertAlmostEqual(groceries["selected"], -400)
        self.assertAlmostEqual(groceries["average"], -1000 / 3)
        self.assertAlmostEqual(groceries["diff"], -400 - (-1000 / 3))
        expected_pct = (400 - 1000 / 3) / (1000 / 3) * 100
        self.assertAlmostEqual(groceries["diff_pct"], expected_pct)

    def test_empty_selected_month(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -300, "Groceries")
        conn.commit()
        data = month_vs_year_avg(conn, "2026-01")
        self.assertFalse(data["empty"])
        groceries = next(c for c in data["categories"] if c["name"] == "Groceries")
        self.assertAlmostEqual(groceries["selected"], 0)
        self.assertAlmostEqual(groceries["average"], -300)
        self.assertAlmostEqual(data["income"]["selected"], 0)
        self.assertAlmostEqual(data["total_spend"]["selected"], 0)

    def test_income_comparison(self):
        conn = make_test_conn()
        insert_row(conn, "2026-04-01", "SALARY", 4000, "Income")
        insert_row(conn, "2026-05-01", "SALARY", 2000, "Income")
        conn.commit()
        data = month_vs_year_avg(conn, "2026-05")
        self.assertAlmostEqual(data["income"]["selected"], 2000)
        self.assertAlmostEqual(data["income"]["average"], 3000)
        self.assertAlmostEqual(data["income"]["diff"], -1000)
        self.assertAlmostEqual(data["income"]["diff_pct"], -1000 / 3000 * 100)

    def test_uses_fixed_latest_window(self):
        conn = make_test_conn()
        for m in ["2026-04", "2026-05", "2026-06"]:
            insert_row(conn, f"{m}-01", "TESCO", -100, "Groceries")
        conn.commit()
        data_old = month_vs_year_avg(conn, "2026-04")
        data_new = month_vs_year_avg(conn, "2026-06")
        self.assertEqual(data_old["window_end"], data_new["window_end"])
        self.assertAlmostEqual(data_old["categories"][0]["average"], -100)

    def test_expected_budget_fields(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -450, "Groceries")
        set_category_budget(conn, "Groceries", -400)
        conn.commit()
        data = month_vs_year_avg(conn, "2026-05")
        groceries = next(c for c in data["categories"] if c["name"] == "Groceries")
        self.assertAlmostEqual(groceries["expected"], -400)
        self.assertAlmostEqual(groceries["expected_diff"], -50)
        self.assertAlmostEqual(groceries["expected_diff_pct"], 12.5)

    def test_budget_only_category_appears(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -100, "Groceries")
        set_category_budget(conn, "Subscriptions", -30)
        conn.commit()
        data = month_vs_year_avg(conn, "2026-05")
        names = [c["name"] for c in data["categories"]]
        self.assertIn("Subscriptions", names)
        subs = next(c for c in data["categories"] if c["name"] == "Subscriptions")
        self.assertAlmostEqual(subs["selected"], 0)
        self.assertAlmostEqual(subs["expected"], -30)

    def test_budget_total_sums_set_budgets(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -450, "Groceries")
        insert_row(conn, "2026-05-02", "NETFLIX", -15, "Subscriptions")
        set_category_budget(conn, "Groceries", -400)
        set_category_budget(conn, "Subscriptions", -30)
        conn.commit()
        data = month_vs_year_avg(conn, "2026-05")
        self.assertAlmostEqual(data["budget_total"]["expected"], -430)
        self.assertAlmostEqual(data["budget_total"]["expected_diff"], -35)
        self.assertAlmostEqual(data["total_spend"]["selected"], -465)


class TestUncategorised(unittest.TestCase):
    def test_distinct_descriptions(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "MYSTERY SHOP", -12.99, "Uncategorised")
        insert_row(conn, "2026-05-02", "MYSTERY SHOP", -12.99, "Uncategorised")
        insert_row(conn, "2026-05-03", "OTHER SHOP", -5.00, "Uncategorised")
        conn.commit()
        rows = uncategorised(conn)
        self.assertEqual(len(rows), 2)

    def test_rows_include_representative_id(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "MYSTERY SHOP", -12.99, "Uncategorised")
        insert_row(conn, "2026-05-02", "MYSTERY SHOP", -12.99, "Uncategorised")
        conn.commit()
        rows = uncategorised(conn)
        self.assertEqual(len(rows), 1)
        self.assertIn("id", rows[0])
        self.assertIsNotNone(rows[0]["id"])


class TestCategoryTransactions(unittest.TestCase):
    def setUp(self):
        self.conn = make_test_conn()
        insert_row(self.conn, "2026-05-03", "TESCO", -45.67, "Groceries", "credit_card")
        insert_row(self.conn, "2026-05-10", "SAINSBURY", -30.00, "Groceries", "credit_card")
        insert_row(self.conn, "2026-05-12", "TESCO REFUND", 5.00, "Groceries", "credit_card")
        insert_row(self.conn, "2026-05-15", "NETFLIX", -9.99, "Subscriptions")
        self.conn.commit()

    def test_returns_transactions(self):
        data = category_transactions(self.conn, "2026-05", "Groceries")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["transactions"]), 3)
        self.assertEqual(data["transactions"][0]["date"], "2026-05-03")
        self.assertEqual(data["transactions"][0]["source_account"], "credit_card")
        self.assertIn("id", data["transactions"][0])
        self.assertEqual(data["transactions"][0]["category"], "Groceries")

    def test_total_and_count(self):
        data = category_transactions(self.conn, "2026-05", "Groceries")
        expected_total = sum(t["amount"] for t in data["transactions"])
        self.assertAlmostEqual(data["total"], expected_total)
        self.assertEqual(data["total"], -70.67)

    def test_includes_refunds(self):
        data = category_transactions(self.conn, "2026-05", "Groceries")
        amounts = [t["amount"] for t in data["transactions"]]
        self.assertIn(5.00, amounts)

    def test_empty_month_category(self):
        data = category_transactions(self.conn, "2026-01", "Groceries")
        self.assertTrue(data["empty"])

    def test_other_category_excluded(self):
        data = category_transactions(self.conn, "2026-05", "Subscriptions")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 1)


class TestMonthTransactions(unittest.TestCase):
    def setUp(self):
        self.conn = make_test_conn()
        insert_row(self.conn, "2026-05-03", "TESCO", -45.67, "Groceries", "credit_card")
        insert_row(self.conn, "2026-05-10", "SAINSBURY", -30.00, "Groceries", "credit_card")
        insert_row(self.conn, "2026-05-12", "SALARY", 2500.00, "Income", "current_account")
        insert_row(self.conn, "2026-05-15", "NETFLIX", -9.99, "Subscriptions")
        insert_row(self.conn, "2026-06-01", "OTHER", -5.00, "Shopping")
        self.conn.commit()

    def test_returns_all_rows_for_month(self):
        data = month_transactions(self.conn, "2026-05")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 4)
        self.assertEqual(len(data["transactions"]), 4)

    def test_includes_income_and_spending(self):
        data = month_transactions(self.conn, "2026-05")
        amounts = [t["amount"] for t in data["transactions"]]
        self.assertIn(2500.00, amounts)
        self.assertIn(-45.67, amounts)

    def test_total_and_count(self):
        data = month_transactions(self.conn, "2026-05")
        expected_total = sum(t["amount"] for t in data["transactions"])
        self.assertAlmostEqual(data["total"], expected_total)
        self.assertAlmostEqual(data["total"], 2500.00 - 45.67 - 30.00 - 9.99)

    def test_empty_month(self):
        data = month_transactions(self.conn, "2026-01")
        self.assertTrue(data["empty"])

    def test_excludes_other_months(self):
        data = month_transactions(self.conn, "2026-05")
        descriptions = [t["description"] for t in data["transactions"]]
        self.assertNotIn("OTHER", descriptions)


class TestCategoryOptions(unittest.TestCase):
    def test_includes_rules_db_and_uncategorised(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "TESCO", -10, "Groceries")
        insert_row(conn, "2026-05-02", "MYSTERY", -5, "My Custom Cat")
        conn.commit()
        options = category_options(conn)
        self.assertIn("Groceries", options)
        self.assertIn("Uncategorised", options)
        self.assertIn("My Custom Cat", options)
        self.assertIn("Income", options)


class TestSearchTransactions(unittest.TestCase):
    def setUp(self):
        self.conn = make_test_conn()
        insert_row(self.conn, "2025-12-12", "BROMCOM BROMCOM UNITED KINGDOM", -80, "Education & Childcare")
        insert_row(self.conn, "2026-01-02", "BROMCOM BROMCOM UNITED KINGDOM", -1218, "Education & Childcare")
        insert_row(self.conn, "2026-05-03", "TESCO STORES", -45.67, "Groceries")
        insert_row(self.conn, "2026-05-12", "BROMCOM REFUND", 10, "Education & Childcare")
        insert_row(self.conn, "2026-06-01", "100% SHOP", -5, "Shopping")
        insert_row(self.conn, "2026-06-02", "A_B SHOP", -7, "Shopping")
        self.conn.commit()

    def test_case_insensitive_description_match(self):
        data = search_transactions(self.conn, "bromcom", "all")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 3)

    def test_month_scope(self):
        data = search_transactions(self.conn, "BROMCOM", "month", month="2026-01")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["transactions"][0]["amount"], -1218)

    def test_year_scope(self):
        data = search_transactions(self.conn, "BROMCOM", "year", year="2026")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 2)

    def test_all_scope(self):
        data = search_transactions(self.conn, "BROMCOM", "all")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["total"], -80 - 1218 + 10)

    def test_literal_percent_not_wildcard(self):
        data = search_transactions(self.conn, "100%", "all")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["transactions"][0]["description"], "100% SHOP")

    def test_literal_underscore_not_wildcard(self):
        data = search_transactions(self.conn, "A_B", "all")
        self.assertFalse(data["empty"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["transactions"][0]["description"], "A_B SHOP")

    def test_empty_query_raises(self):
        with self.assertRaises(ValueError):
            search_transactions(self.conn, "   ", "all")

    def test_no_matches(self):
        data = search_transactions(self.conn, "NOPE", "all")
        self.assertTrue(data["empty"])


class TestSubscriptions(unittest.TestCase):
    def test_detected(self):
        conn = make_test_conn()
        for m in ["2026-04", "2026-05", "2026-06"]:
            insert_row(conn, f"{m}-01", "NETFLIX", -9.99, "Subscriptions")
        conn.commit()
        data = subscriptions(conn)
        self.assertEqual(len(data["items"]), 1)
        self.assertAlmostEqual(data["estimated_monthly"], -9.99)

    def test_rejects_variable_amounts(self):
        conn = make_test_conn()
        insert_row(conn, "2026-04-01", "AMAZON", -10, "Shopping")
        insert_row(conn, "2026-05-01", "AMAZON", -50, "Shopping")
        insert_row(conn, "2026-06-01", "AMAZON", -20, "Shopping")
        conn.commit()
        self.assertEqual(subscriptions(conn)["items"], [])

    def test_rejects_frequent_charges(self):
        conn = make_test_conn()
        for i in range(3):
            insert_row(conn, f"2026-04-{i+1:02d}", "COFFEE SHOP", -3.50, "Dining & Takeaway")
        for i in range(3):
            insert_row(conn, f"2026-05-{i+1:02d}", "COFFEE SHOP", -3.50, "Dining & Takeaway")
        for i in range(3):
            insert_row(conn, f"2026-06-{i+1:02d}", "COFFEE SHOP", -3.50, "Dining & Takeaway")
        conn.commit()
        self.assertEqual(subscriptions(conn)["items"], [])


class TestSummary(unittest.TestCase):
    def test_empty_db(self):
        conn = make_test_conn()
        data = summary(conn)
        self.assertTrue(data["empty"])
        self.assertIn("message", data)

    def test_full(self):
        conn = make_test_conn()
        insert_row(conn, "2026-04-01", "TESCO", -100, "Groceries")
        insert_row(conn, "2026-05-01", "TESCO", -100, "Groceries")
        insert_row(conn, "2026-05-02", "UNKNOWN", -5, "Uncategorised")
        conn.commit()
        data = summary(conn)
        self.assertFalse(data["empty"])
        self.assertEqual(data["latest_month"], "2026-05")
        self.assertEqual(data["uncategorised_count"], 1)
        self.assertIsNotNone(data["month"])
        self.assertIsNotNone(data["trends"])


class TestFindDuplicates(unittest.TestCase):
    def test_two_rows_different_source_account(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "OCTOPUS ENERGY LTD", -135.0, "Utilities", "account_a")
        insert_row(conn, "2026-05-29", "OCTOPUS ENERGY LTD", -135.0, "Utilities", "account_b")
        conn.commit()

        data = find_duplicates(conn)
        self.assertEqual(data["group_count"], 1)
        self.assertEqual(data["extra_row_count"], 1)
        self.assertEqual(len(data["groups"][0]["transactions"]), 2)

    def test_three_rows_one_group(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_a")
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_b")
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_c")
        conn.commit()

        data = find_duplicates(conn)
        self.assertEqual(data["group_count"], 1)
        self.assertEqual(data["extra_row_count"], 2)

    def test_different_amount_not_duplicate(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_a")
        insert_row(conn, "2026-05-29", "TESCO", -51.0, "Groceries", "account_b")
        conn.commit()

        data = find_duplicates(conn)
        self.assertEqual(data["group_count"], 0)
        self.assertEqual(data["extra_row_count"], 0)

    def test_suggested_keep_newer_export(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "OCTOPUS ENERGY LTD", -135.0, "Utilities", "old_export")
        insert_row(conn, "2026-06-15", "OTHER", -10.0, "Shopping", "old_export")
        insert_row(conn, "2026-05-29", "OCTOPUS ENERGY LTD", -135.0, "Utilities", "new_export")
        insert_row(conn, "2026-07-03", "OTHER", -10.0, "Shopping", "new_export")
        conn.commit()

        data = find_duplicates(conn)
        txs = {tx["source_account"]: tx for tx in data["groups"][0]["transactions"]}
        self.assertFalse(txs["old_export"]["suggested_keep"])
        self.assertTrue(txs["new_export"]["suggested_keep"])

    def test_suggested_keep_tie_breaks_on_highest_id(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_a")
        insert_row(conn, "2026-05-30", "OTHER", -10.0, "Shopping", "account_a")
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_b")
        insert_row(conn, "2026-05-30", "OTHER", -10.0, "Shopping", "account_b")
        conn.commit()

        data = find_duplicates(conn)
        txs = data["groups"][0]["transactions"]
        keep = [tx for tx in txs if tx["suggested_keep"]]
        self.assertEqual(len(keep), 1)
        self.assertEqual(keep[0]["id"], max(tx["id"] for tx in txs))

    def test_case_only_description_difference(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-01", "Tesco", -10.0, "Groceries", "test")
        insert_row(conn, "2026-05-01", "TESCO", -10.0, "Groceries", "test")
        conn.commit()

        data = find_duplicates(conn)
        self.assertEqual(data["group_count"], 1)

    def test_validate_rejects_unknown_id(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_a")
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_b")
        conn.commit()

        with self.assertRaises(ValueError) as ctx:
            validate_duplicate_removal(conn, [999])
        self.assertIn("unknown transaction id", str(ctx.exception))

    def test_validate_rejects_non_duplicate_id(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_a")
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_b")
        insert_row(conn, "2026-05-30", "UNIQUE", -5.0, "Shopping", "account_a")
        conn.commit()
        unique_id = conn.execute(
            "SELECT id FROM transactions WHERE description = 'UNIQUE'"
        ).fetchone()[0]

        with self.assertRaises(ValueError) as ctx:
            validate_duplicate_removal(conn, [unique_id])
        self.assertIn("is not a duplicate", str(ctx.exception))

    def test_validate_rejects_removing_all_copies(self):
        conn = make_test_conn()
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_a")
        insert_row(conn, "2026-05-29", "TESCO", -50.0, "Groceries", "account_b")
        conn.commit()
        ids = [row[0] for row in conn.execute("SELECT id FROM transactions").fetchall()]

        with self.assertRaises(ValueError) as ctx:
            validate_duplicate_removal(conn, ids)
        self.assertIn("would remove all copies", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
