"""
report_data.py — pure data functions for spending reports.

Returns structured dicts/lists (no print, no HTTP). Used by analyze.py (CLI)
and web_server.py (JSON API).
"""

from collections import defaultdict

from db_layer import get_category_budgets
from rules.categories import (
    CATEGORY_RULES,
    NON_SPENDING_CATEGORIES,
    NEEDS_CATEGORIES,
    WANTS_CATEGORIES,
)


def month_key(date_str: str) -> str:
    return date_str[:7]  # YYYY-MM


def get_all_transactions(conn):
    cur = conn.execute(
        "SELECT id, date, description, amount, source_account, category, balance "
        "FROM transactions ORDER BY date"
    )
    return cur.fetchall()


def category_breakdown(rows, exclude_non_spending=True):
    totals = defaultdict(float)
    for _, date, desc, amount, account, category, balance in rows:
        if exclude_non_spending and category in NON_SPENDING_CATEGORIES:
            continue
        if amount < 0:  # only count spending
            totals[category] += amount
    return totals


def detect_subscriptions(conn):
    """
    Heuristic: a merchant counts as a likely subscription only if BOTH:
      1. The amount charged is consistent every time (within ~5%)
      2. The cadence is roughly monthly (close to 1 charge per distinct month)
    """
    cur = conn.execute(
        "SELECT date, description, amount FROM transactions "
        "WHERE category NOT IN ({}) AND amount < 0".format(
            ",".join("?" * len(NON_SPENDING_CATEGORIES))
        ),
        tuple(NON_SPENDING_CATEGORIES)
    )
    rows = cur.fetchall()

    by_merchant = defaultdict(list)
    for date, desc, amount in rows:
        by_merchant[desc.strip().upper()].append((date, amount))

    subscriptions = []
    for desc, entries in by_merchant.items():
        if len(entries) < 3:
            continue

        amounts = [a for _, a in entries]
        avg_amount = sum(amounts) / len(amounts)
        if avg_amount == 0:
            continue

        max_dev = max(abs(a - avg_amount) for a in amounts)
        relative_dev = max_dev / abs(avg_amount)
        if relative_dev > 0.05:
            continue

        months_seen = sorted(set(month_key(d) for d, _ in entries))
        if len(months_seen) < 3:
            continue

        charges_per_month = len(entries) / len(months_seen)
        if charges_per_month > 1.5:
            continue

        subscriptions.append((desc, avg_amount, len(months_seen)))

    subscriptions.sort(key=lambda x: x[1])
    return subscriptions


def list_months(conn):
    rows = get_all_transactions(conn)
    return sorted(set(month_key(r[1]) for r in rows))


def month_report(conn, target_month: str):
    cur = conn.execute(
        "SELECT id, date, description, amount, source_account, category, balance "
        "FROM transactions WHERE date LIKE ? ORDER BY date",
        (f"{target_month}%",)
    )
    rows = cur.fetchall()
    if not rows:
        return {"month": target_month, "empty": True}

    totals = category_breakdown(rows)
    total_spend = sum(totals.values())
    income = sum(r[3] for r in rows if r[5] == "Income" and r[3] > 0)

    categories = []
    for cat, amt in sorted(totals.items(), key=lambda x: x[1]):
        pct = (amt / total_spend * 100) if total_spend else 0
        categories.append({"name": cat, "amount": amt, "pct": pct})

    needs = sum(amt for cat, amt in totals.items() if cat in NEEDS_CATEGORIES)
    wants = sum(amt for cat, amt in totals.items() if cat in WANTS_CATEGORIES)
    other = total_spend - needs - wants

    benchmark = {
        "needs": needs,
        "wants": wants,
        "other": other,
        "needs_pct": abs(needs) / total_spend * 100 if total_spend else 0,
        "wants_pct": abs(wants) / total_spend * 100 if total_spend else 0,
        "savings_rate": (income + total_spend) / income * 100 if income else None,
    }

    merchant_totals = defaultdict(float)
    for _, date, desc, amount, account, category, balance in rows:
        if amount < 0 and category not in NON_SPENDING_CATEGORIES:
            merchant_totals[desc.strip()] += amount
    top_merchants = [
        {"description": desc, "amount": amt}
        for desc, amt in sorted(merchant_totals.items(), key=lambda x: x[1])[:10]
    ]

    return {
        "month": target_month,
        "empty": False,
        "total_spend": total_spend,
        "income": income,
        "net": income + total_spend,
        "categories": categories,
        "benchmark": benchmark,
        "top_merchants": top_merchants,
    }


def month_over_month(conn):
    rows = get_all_transactions(conn)
    if not rows:
        return {"empty": True}

    months = sorted(set(month_key(r[1]) for r in rows))
    if len(months) < 2:
        return {"empty": False, "insufficient_months": True, "months": months}

    monthly_totals = defaultdict(lambda: defaultdict(float))
    for _, date, desc, amount, account, category, balance in rows:
        if amount < 0 and category not in NON_SPENDING_CATEGORIES:
            monthly_totals[month_key(date)][category] += amount

    all_categories = sorted(set(
        cat for m in monthly_totals.values() for cat in m.keys()
    ))

    grid = {}
    for cat in all_categories:
        grid[cat] = {m: monthly_totals[m].get(cat, 0) for m in months}

    totals = {m: sum(monthly_totals[m].values()) for m in months}

    anomalies = []
    if len(months) >= 3:
        latest = months[-1]
        prior_months = months[:-1]
        for cat in all_categories:
            prior_avg = sum(monthly_totals[m].get(cat, 0) for m in prior_months) / len(prior_months)
            latest_val = monthly_totals[latest].get(cat, 0)
            if prior_avg == 0:
                continue
            prior_avg_abs = abs(prior_avg)
            latest_val_abs = abs(latest_val)
            change_pct = (latest_val_abs - prior_avg_abs) / prior_avg_abs * 100
            if abs(change_pct) >= 30 and abs(latest_val_abs - prior_avg_abs) > 20:
                direction = "up" if change_pct > 0 else "down"
                anomalies.append({
                    "category": cat,
                    "direction": direction,
                    "change_pct": abs(change_pct),
                    "prior_avg": prior_avg,
                    "latest": latest_val,
                })

    return {
        "empty": False,
        "insufficient_months": False,
        "months": months,
        "categories": all_categories,
        "grid": grid,
        "totals": totals,
        "anomalies": anomalies,
    }


def _compare_metric(selected, average, spending=False):
    diff = selected - average
    if spending:
        if average == 0:
            diff_pct = None
        else:
            diff_pct = (abs(selected) - abs(average)) / abs(average) * 100
    else:
        if average == 0:
            diff_pct = None
        else:
            diff_pct = (selected - average) / average * 100
    return {
        "selected": selected,
        "average": average,
        "diff": diff,
        "diff_pct": diff_pct,
    }


def _expected_fields(selected, expected):
    if expected is None:
        return {
            "expected": None,
            "expected_diff": None,
            "expected_diff_pct": None,
        }
    diff = selected - expected
    if expected == 0:
        diff_pct = None
    else:
        diff_pct = (abs(selected) - abs(expected)) / abs(expected) * 100
    return {
        "expected": expected,
        "expected_diff": diff,
        "expected_diff_pct": diff_pct,
    }


def year_avg_baseline(conn):
    """
    Fixed monthly averages over the most recent 12 months in the database.
    Months with no activity count as zero for that category/income/total.
    """
    rows = get_all_transactions(conn)
    if not rows:
        return {"empty": True}

    months = list_months(conn)
    window = months[-12:]
    month_count = len(window)
    if month_count == 0:
        return {"empty": False, "insufficient_data": True}

    monthly_spend = defaultdict(lambda: defaultdict(float))
    monthly_income = defaultdict(float)
    for _, date, desc, amount, account, category, balance in rows:
        mk = month_key(date)
        if mk not in window:
            continue
        if amount < 0 and category not in NON_SPENDING_CATEGORIES:
            monthly_spend[mk][category] += amount
        if category == "Income" and amount > 0:
            monthly_income[mk] += amount

    all_categories = sorted(set(
        cat for m in monthly_spend.values() for cat in m.keys()
    ))

    category_avgs = {}
    for cat in all_categories:
        total = sum(monthly_spend[m].get(cat, 0) for m in window)
        category_avgs[cat] = total / month_count

    total_spend_avg = sum(
        sum(monthly_spend[m].values()) for m in window
    ) / month_count
    income_avg = sum(monthly_income[m] for m in window) / month_count

    return {
        "empty": False,
        "insufficient_data": False,
        "window_start": window[0],
        "window_end": window[-1],
        "month_count": month_count,
        "category_avgs": category_avgs,
        "total_spend_avg": total_spend_avg,
        "income_avg": income_avg,
    }


def month_vs_year_avg(conn, target_month: str):
    baseline = year_avg_baseline(conn)
    if baseline.get("empty"):
        return {"empty": True}
    if baseline.get("insufficient_data"):
        return {
            "empty": False,
            "insufficient_data": True,
            "selected_month": target_month,
        }

    selected = month_report(conn, target_month)
    if selected.get("empty"):
        selected_spend_by_cat = {}
        selected_total_spend = 0.0
        selected_income = 0.0
    else:
        selected_spend_by_cat = {c["name"]: c["amount"] for c in selected["categories"]}
        selected_total_spend = selected["total_spend"]
        selected_income = selected["income"]

    budgets = get_category_budgets(conn)

    all_categories = sorted(
        set(baseline["category_avgs"].keys())
        | set(selected_spend_by_cat.keys())
        | set(budgets.keys()),
        key=lambda cat: selected_spend_by_cat.get(cat, 0),
    )

    categories = []
    for cat in all_categories:
        sel = selected_spend_by_cat.get(cat, 0.0)
        avg = baseline["category_avgs"].get(cat, 0.0)
        categories.append({
            "name": cat,
            **_compare_metric(sel, avg, spending=True),
            **_expected_fields(sel, budgets.get(cat)),
        })

    if budgets:
        total_expected = sum(budgets.values())
        budget_total = {
            "expected": total_expected,
            **_expected_fields(selected_total_spend, total_expected),
        }
    else:
        budget_total = {
            "expected": None,
            "expected_diff": None,
            "expected_diff_pct": None,
        }

    return {
        "empty": False,
        "insufficient_data": False,
        "selected_month": target_month,
        "window_start": baseline["window_start"],
        "window_end": baseline["window_end"],
        "month_count": baseline["month_count"],
        "income": _compare_metric(selected_income, baseline["income_avg"], spending=False),
        "total_spend": _compare_metric(
            selected_total_spend, baseline["total_spend_avg"], spending=True
        ),
        "profit_loss": selected_income + selected_total_spend,
        "budget_total": budget_total,
        "categories": categories,
    }


def _resolve_expected(category, budgets, avgs):
    if category in budgets:
        return budgets[category], "budget"
    avg = avgs.get(category, 0.0)
    if avg != 0:
        return avg, "average"
    return None, None


def _progress_fields(spent, expected):
    if expected is None:
        return {
            "progress_pct": None,
            "over_budget": False,
            "remaining": None,
        }
    over_budget = abs(spent) > abs(expected)
    remaining = abs(expected) - abs(spent)
    if expected == 0:
        progress_pct = 100.0 if spent != 0 else 0.0
    else:
        progress_pct = min(100.0, abs(spent) / abs(expected) * 100)
    return {
        "progress_pct": progress_pct,
        "over_budget": over_budget,
        "remaining": remaining,
    }


def _pct_of_income(spend_amount, income_avg):
    if income_avg == 0:
        return None
    return abs(spend_amount) / income_avg * 100


def month_spending_progress(conn, target_month: str):
    """
    Calendar-month spending vs resolved expected amounts per category.
    Expected = user budget when set, otherwise 12-month rolling average.
    """
    baseline = year_avg_baseline(conn)
    if baseline.get("empty"):
        return {"empty": True}
    if baseline.get("insufficient_data"):
        return {
            "empty": False,
            "insufficient_data": True,
            "month": target_month,
        }

    selected = month_report(conn, target_month)
    if selected.get("empty"):
        spent_by_cat = {}
        total_spend = 0.0
        selected_income = 0.0
    else:
        spent_by_cat = {c["name"]: c["amount"] for c in selected["categories"]}
        total_spend = selected["total_spend"]
        selected_income = selected["income"]

    budgets = get_category_budgets(conn)
    avgs = baseline["category_avgs"]

    all_categories = sorted(
        set(avgs.keys()) | set(spent_by_cat.keys()) | set(budgets.keys()),
        key=lambda cat: spent_by_cat.get(cat, 0),
    )

    categories = []
    total_expected = 0.0
    for cat in all_categories:
        spent = spent_by_cat.get(cat, 0.0)
        expected, source = _resolve_expected(cat, budgets, avgs)
        if expected is not None:
            total_expected += expected
        categories.append({
            "name": cat,
            "spent": spent,
            "expected": expected,
            "expected_source": source,
            **_progress_fields(spent, expected),
        })

    total_remaining = abs(total_expected) - abs(total_spend)
    income_avg = baseline["income_avg"]
    total_spend_avg = baseline["total_spend_avg"]

    return {
        "empty": False,
        "insufficient_data": False,
        "month": target_month,
        "window_start": baseline["window_start"],
        "window_end": baseline["window_end"],
        "month_count": baseline["month_count"],
        "income": _compare_metric(selected_income, income_avg, spending=False),
        "total_spend": total_spend,
        "total_expected": total_expected,
        "total_remaining": total_remaining,
        "total_spend_avg": total_spend_avg,
        "current_spend_pct_of_income_avg": _pct_of_income(total_spend, income_avg),
        "expected_spend_pct_of_income_avg": _pct_of_income(total_expected, income_avg),
        "avg_spend_pct_of_income_avg": _pct_of_income(total_spend_avg, income_avg),
        "profit_loss": selected_income + total_spend,
        "categories": categories,
    }


def category_options(conn):
    """Categories for UI dropdowns: rules, DB values, and Uncategorised."""
    cur = conn.execute("SELECT DISTINCT category FROM transactions ORDER BY category")
    db_categories = {row[0] for row in cur.fetchall()}
    names = set(CATEGORY_RULES.keys()) | db_categories | {"Uncategorised"}
    return sorted(names)


def category_transactions(conn, month: str, category: str):
    cur = conn.execute(
        "SELECT id, date, description, amount, source_account, category "
        "FROM transactions "
        "WHERE date LIKE ? AND category = ? "
        "ORDER BY date, description",
        (f"{month}%", category),
    )
    rows = cur.fetchall()
    if not rows:
        return {"month": month, "category": category, "empty": True}

    transactions = [
        {
            "id": row_id,
            "date": date,
            "description": description,
            "amount": amount,
            "source_account": source_account,
            "category": row_category,
        }
        for row_id, date, description, amount, source_account, row_category in rows
    ]
    total = sum(t["amount"] for t in transactions)
    return {
        "month": month,
        "category": category,
        "empty": False,
        "total": total,
        "count": len(transactions),
        "transactions": transactions,
    }


def month_transactions(conn, month: str):
    cur = conn.execute(
        "SELECT id, date, description, amount, source_account, category "
        "FROM transactions "
        "WHERE date LIKE ? "
        "ORDER BY date, description",
        (f"{month}%",),
    )
    rows = cur.fetchall()
    if not rows:
        return {"month": month, "empty": True}

    transactions = [
        {
            "id": row_id,
            "date": date,
            "description": description,
            "amount": amount,
            "source_account": source_account,
            "category": row_category,
        }
        for row_id, date, description, amount, source_account, row_category in rows
    ]
    total = sum(t["amount"] for t in transactions)
    return {
        "month": month,
        "empty": False,
        "total": total,
        "count": len(transactions),
        "transactions": transactions,
    }


def _escape_like_literal(text: str) -> str:
    """Escape SQLite LIKE wildcards so user input is matched literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_transactions(conn, query: str, scope: str, month: str = None, year: str = None):
    """
    Search transaction descriptions within a date scope.

    scope: 'month' (requires month=YYYY-MM), 'year' (requires year=YYYY), or 'all'.
    """
    q = query.strip()
    if not q:
        raise ValueError("query is required")

    pattern = f"%{_escape_like_literal(q)}%"
    sql = (
        "SELECT id, date, description, amount, source_account, category "
        "FROM transactions WHERE description LIKE ? ESCAPE '\\'"
    )
    params = [pattern]

    if scope == "month":
        if not month:
            raise ValueError("month is required for month scope")
        sql += " AND date LIKE ?"
        params.append(f"{month}%")
    elif scope == "year":
        if not year:
            raise ValueError("year is required for year scope")
        sql += " AND date LIKE ?"
        params.append(f"{year}-%")
    elif scope != "all":
        raise ValueError("invalid scope")

    sql += " ORDER BY date, description"
    cur = conn.execute(sql, params)
    rows = cur.fetchall()

    if not rows:
        result = {
            "query": q,
            "scope": scope,
            "empty": True,
        }
        if scope == "month":
            result["month"] = month
        elif scope == "year":
            result["year"] = year
        return result

    transactions = [
        {
            "id": row_id,
            "date": date,
            "description": description,
            "amount": amount,
            "source_account": source_account,
            "category": row_category,
        }
        for row_id, date, description, amount, source_account, row_category in rows
    ]
    total = sum(t["amount"] for t in transactions)
    result = {
        "query": q,
        "scope": scope,
        "empty": False,
        "total": total,
        "count": len(transactions),
        "transactions": transactions,
    }
    if scope == "month":
        result["month"] = month
    elif scope == "year":
        result["year"] = year
    return result


def uncategorised(conn):
    cur = conn.execute(
        "SELECT MIN(id), description, amount FROM transactions "
        "WHERE category = 'Uncategorised' "
        "GROUP BY description ORDER BY description"
    )
    return [
        {"id": row_id, "description": desc, "amount": amount}
        for row_id, desc, amount in cur.fetchall()
    ]


def subscriptions(conn):
    subs = detect_subscriptions(conn)
    items = [
        {"description": desc, "avg_amount": avg_amount, "months_seen": months_seen}
        for desc, avg_amount, months_seen in subs
    ]
    estimated_monthly = sum(item["avg_amount"] for item in items)
    return {
        "items": items,
        "estimated_monthly": estimated_monthly,
        "estimated_yearly": estimated_monthly * 12,
    }


def _account_latest_dates(conn):
    """Map each source_account to its latest transaction date."""
    rows = conn.execute(
        "SELECT source_account, MAX(date) FROM transactions GROUP BY source_account"
    ).fetchall()
    return {account: latest for account, latest in rows}


def _duplicate_groups(conn):
    """
    Return duplicate groups as (date, norm_desc, rounded_amount, member_rows).
    Each member_row is (id, date, description, amount, source_account, category, balance).
    Cross-file duplicates share date + normalized description + rounded amount but differ
    in source_account / raw_hash (see make_hash in db_layer).
    """
    keys = conn.execute(
        """SELECT date, UPPER(TRIM(description)), ROUND(amount, 2), COUNT(*)
           FROM transactions
           GROUP BY 1, 2, 3
           HAVING COUNT(*) >= 2"""
    ).fetchall()

    groups = []
    for date, norm_desc, rounded_amount, _count in keys:
        rows = conn.execute(
            """SELECT id, date, description, amount, source_account, category, balance
               FROM transactions
               WHERE date = ? AND UPPER(TRIM(description)) = ? AND ROUND(amount, 2) = ?
               ORDER BY id""",
            (date, norm_desc, rounded_amount),
        ).fetchall()
        groups.append((date, norm_desc, rounded_amount, rows))
    return groups


def _suggested_keep_id(rows, account_latest_date):
    """Pick the row to keep: newest export (latest account max date), then highest id."""
    return max(
        rows,
        key=lambda row: (account_latest_date.get(row[4], ""), row[0]),
    )[0]


def find_duplicates(conn):
    """Return duplicate groups with suggested_keep flags for the Import UI."""
    account_latest_date = _account_latest_dates(conn)
    raw_groups = _duplicate_groups(conn)

    groups = []
    extra_row_count = 0
    for date, norm_desc, rounded_amount, rows in raw_groups:
        keep_id = _suggested_keep_id(rows, account_latest_date)
        transactions = []
        for row_id, _date, _description, _amount, source_account, category, _balance in rows:
            transactions.append({
                "id": row_id,
                "source_account": source_account,
                "category": category,
                "suggested_keep": row_id == keep_id,
            })
        extra_row_count += len(rows) - 1
        groups.append({
            "key": {
                "date": date,
                "description": norm_desc,
                "amount": float(rounded_amount),
            },
            "transactions": transactions,
        })

    return {
        "group_count": len(groups),
        "extra_row_count": extra_row_count,
        "groups": groups,
    }


def validate_duplicate_removal(conn, ids_to_remove):
    """
    Raise ValueError if ids are invalid or would delete all copies of any group.
    Caller must ensure ids_to_remove is a non-empty list of positive ints.
    """
    unique_ids = list(dict.fromkeys(ids_to_remove))

    existing = {
        row[0]
        for row in conn.execute(
            f"SELECT id FROM transactions WHERE id IN ({','.join('?' * len(unique_ids))})",
            unique_ids,
        ).fetchall()
    }
    for tid in unique_ids:
        if tid not in existing:
            raise ValueError(f"unknown transaction id: {tid}")

    duplicate_ids = set()
    for _date, _norm_desc, _rounded_amount, rows in _duplicate_groups(conn):
        group_ids = {row[0] for row in rows}
        duplicate_ids |= group_ids
        removing = group_ids.intersection(unique_ids)
        if removing and len(removing) == len(group_ids):
            raise ValueError("would remove all copies of a duplicate group")

    for tid in unique_ids:
        if tid not in duplicate_ids:
            raise ValueError(f"id {tid} is not a duplicate")


def source_status(conn):
    """Return aggregated status for bank and credit card sources."""
    tx_stats = {}
    for source_type, is_credit in (("bank", False), ("credit_card", True)):
        if is_credit:
            where = "WHERE source_account LIKE 'credit_card_%'"
        else:
            where = "WHERE source_account NOT LIKE 'credit_card_%'"
        row = conn.execute(
            f"SELECT MAX(date), COUNT(*), COUNT(DISTINCT source_account) "
            f"FROM transactions {where}"
        ).fetchone()
        tx_stats[source_type] = {
            "last_transaction_date": row[0],
            "transaction_count": row[1] or 0,
            "file_count": row[2] or 0,
        }

    import_stats = {}
    rows = conn.execute(
        "SELECT source_type, MAX(last_import_at) FROM import_runs GROUP BY source_type"
    ).fetchall()
    for source_type, last_import_at in rows:
        import_stats[source_type] = last_import_at

    labels = {"bank": "Bank", "credit_card": "Credit card"}
    result = []
    for source_type in ("bank", "credit_card"):
        tx = tx_stats[source_type]
        result.append({
            "type": source_type,
            "label": labels[source_type],
            "last_transaction_date": tx["last_transaction_date"],
            "last_import_at": import_stats.get(source_type),
            "transaction_count": tx["transaction_count"],
            "file_count": tx["file_count"],
        })
    return result


def summary(conn):
    rows = get_all_transactions(conn)
    if not rows:
        return {
            "empty": True,
            "message": (
                "No data imported yet. Drop CSVs into data/accounts/ and "
                "data/credit_card/, then run importer.py."
            ),
        }

    latest_month = list_months(conn)[-1]
    trends = month_over_month(conn)
    if trends.get("insufficient_months"):
        trends = None

    return {
        "empty": False,
        "latest_month": latest_month,
        "month": month_report(conn, latest_month),
        "trends": trends,
        "subscriptions": subscriptions(conn),
        "uncategorised_count": sum(1 for r in rows if r[5] == "Uncategorised"),
    }
