"""
report_data.py — pure data functions for spending reports.

Returns structured dicts/lists (no print, no HTTP). Used by analyze.py (CLI)
and web_server.py (JSON API).
"""

from collections import defaultdict

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
