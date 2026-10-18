
from flask import Blueprint, request, jsonify
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
import json
import re
import calendar

api_bp = Blueprint("api", __name__)

DATA_FILE = Path(__file__).resolve().parents[1] / "orders.jsonl"
TZ = ZoneInfo("Asia/Kolkata")
RATES = {"USD": 1.0, "EUR": 1.13, "INR": 0.01108}

PRODUCTS = [
    "Air Fryer", "Blender", "Grinder", "Juicer",
    "Kettle", "Mixer", "Rice Cooker", "Toaster"
]
REGIONS = ["Central", "East", "North", "South", "West"]

_orders_cache = None


def load_orders():
    """Load orders and retain the latest version of each order ID."""
    global _orders_cache

    if _orders_cache is None:
        latest = {}

        with DATA_FILE.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue

                row = json.loads(line)
                oid = row["id"]
                old = latest.get(oid)

                if old is None or row["updated_at"] > old["updated_at"]:
                    latest[oid] = row

        _orders_cache = list(latest.values())

    return _orders_cache


def usd(row):
    """Convert an order amount to USD."""
    return float(row["amount"]) * RATES[row["currency"]]


def local_date(row):
    """Convert the order creation timestamp to an India-local date."""
    dt = datetime.fromisoformat(
        row["created_at"].replace("Z", "+00:00")
    )
    return dt.astimezone(TZ).date()


def find_named_value(question, values):
    q = question.lower()

    for value in sorted(values, key=len, reverse=True):
        if value.lower() in q:
            return value

    return None


def date_filter(question, rows):
    q = question.lower()

    month_names = {
        m.lower(): i
        for i, m in enumerate(calendar.month_name)
        if m
    }
    month_names.update({
        m.lower(): i
        for i, m in enumerate(calendar.month_abbr)
        if m
    })

    # Formats such as 2026-05 or 2026/05
    ym = re.search(r"\b(20\d{2})[-/](\d{1,2})\b", q)

    if ym:
        year, month = int(ym.group(1)), int(ym.group(2))
        if 1 <= month <= 12:
            return [
                r for r in rows
                if local_date(r).year == year
                and local_date(r).month == month
            ]

    # Formats such as May 2026 or May
    for name, month in month_names.items():
        if re.search(r"\b" + re.escape(name) + r"\b", q):
            year_match = re.search(r"\b(20\d{2})\b", q)
            year = int(year_match.group(1)) if year_match else None

            return [
                r for r in rows
                if local_date(r).month == month
                and (
                    year is None
                    or local_date(r).year == year
                )
            ]

    # A year on its own
    year_match = re.search(r"\b(20\d{2})\b", q)

    if year_match:
        year = int(year_match.group(1))
        return [
            r for r in rows
            if local_date(r).year == year
        ]

    return rows


def answer_question(question):
    q = question.lower().strip()
    rows = load_orders()

    product = find_named_value(question, PRODUCTS)
    region = find_named_value(question, REGIONS)

    customer_match = re.search(r"\bC\d{4}\b", question, re.I)
    customer = (
        customer_match.group(0).upper()
        if customer_match else None
    )

    # Apply date, product, region, and customer filters first.
    rows = date_filter(question, rows)

    if product:
        rows = [
            r for r in rows
            if r["product"].lower() == product.lower()
        ]

    if region:
        rows = [
            r for r in rows
            if r["region"].lower() == region.lower()
        ]

    if customer:
        rows = [
            r for r in rows
            if r["customer"] == customer
        ]

    # Explicit status filters.
    if "refunded" in q or "refund" in q:
        rows = [r for r in rows if r["status"] == "refunded"]

    elif "void" in q or "cancelled" in q or "canceled" in q:
        rows = [r for r in rows if r["status"] == "void"]

    elif any(word in q for word in [
    "paid", "revenue", "sales", "earn", "earned",
    "income", "turnover"
]):
    rows = [r for r in rows if r["status"] == "paid"]

    # Average questions must be checked before general count questions.
    if "average" in q or "on average" in q or "mean" in q:
        total = sum(usd(r) for r in rows)
        return round(total / len(rows), 2) if rows else 0

    # Count distinct customers, including "different customers".
    if any(x in q for x in [
        "distinct customer",
        "unique customer",
        "different customer",
        "how many customers",
        "number of customers",
    ]):
        return len({r["customer"] for r in rows})

    # Other count questions.
    if (
        "how many" in q
        or "count" in q
        or "number of orders" in q
    ):
        return len(rows)

    # Ranking and breakdown questions.
    group_field = None

    if (
        "by product" in q
        or "each product" in q
        or "per product" in q
    ):
        group_field = "product"

    elif (
        "by region" in q
        or "each region" in q
        or "per region" in q
    ):
        group_field = "region"

    elif "by customer" in q or "each customer" in q:
        group_field = "customer"

    if group_field:
        totals = defaultdict(float)

        for r in rows:
            totals[r[group_field]] += usd(r)

        return {
            k: round(v + 1e-9, 2)
            for k, v in sorted(totals.items())
        }

    if any(x in q for x in [
        "highest", "most", "top", "largest", "best-selling"
    ]):
        field = "product" if not region else "customer"
        totals = defaultdict(float)

        for r in rows:
            totals[r[field]] += usd(r)

        if totals:
            return max(totals, key=totals.get)

    if any(x in q for x in ["lowest", "least", "smallest"]):
        field = "product" if not region else "customer"
        totals = defaultdict(float)

        for r in rows:
            totals[r[field]] += usd(r)

        if totals:
            return min(totals, key=totals.get)

    # Money totals: revenue, refunds, and general order value.
    total = sum(usd(r) for r in rows)

    if any(x in q for x in [
        "revenue", "sales", "total", "how much",
        "amount", "refund", "refunded", "value"
    ]):
        return round(total + 1e-9, 2)

    # Product questions without a specific product.
    if "product" in q and not product:
        return sorted({r["product"] for r in rows})

    return "I could not determine the requested calculation."


@api_bp.post("/api/answer")
def answer_endpoint():
    body = request.get_json(silent=True) or {}
    question = body.get("question", "")

    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "A question is required"}), 400

    try:
        return jsonify({"answer": answer_question(question)})

    except FileNotFoundError:
        return jsonify({"error": "orders.jsonl was not found"}), 500

    except Exception:
        # Keep internal exception details out of the public response.
        return jsonify({"error": "Unable to process this question"}), 500
