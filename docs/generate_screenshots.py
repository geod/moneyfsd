"""Generate a synthetic lifestyle-expenses CSV and render screenshots.

Produces docs/screenshots/synthetic_lifestyle.csv plus the PNG/HTML chart
set, ready to be embedded in the README. Uses fictional household
"Alex & Sam Chase" with a small vacation home and recurring patterns
that resemble a real two-earner family budget.

Run from repo root:
    python docs/generate_screenshots.py
"""

from __future__ import annotations

import random
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "screenshots"
CSV_PATH = OUT_DIR / "synthetic_lifestyle.csv"
CHARTS_SCRIPT = ROOT / ".claude" / "skills" / "expenses" / "scripts" / "charts.py"

random.seed(42)

PEOPLE = ["Alex", "Sam"]
SOURCES_BY_PERSON = {
    "Alex": ["Alex AppleCard", "Alex ChaseCard", "Alex Checking"],
    "Sam":  ["Sam AppleCard",  "Sam ChaseCard",  "Sam Checking"],
}

# Each pattern: (Category, Subcategory, Description, person|"either",
#                cadence, base_amount, jitter_pct, season_mult)
# cadence: "monthly" / "weekly" / "biweekly" / "n_per_year:N" / "annual"
# season_mult: dict[month -> multiplier] OR None
# Synthetic household persona: upper-middle dual-income family with
# two kids in public school, one home (no vacation property), modest
# travel, public-school activities. Aim: ~$110-120k of lifestyle spend
# over 14 months — relatable, not aspirational.
PATTERNS = [
    # ---- Housing (the spine: mortgage + utilities + maintenance) ----
    ("Housing", "Mortgage",      "ROCKET MORTGAGE",         "Alex",  "monthly",  2_200, 0.00, None),
    ("Housing", "Property Tax",  "COUNTY TAX COLLECTOR",    "Alex",  "n_per_year:2", 2_500, 0.05, None),
    ("Housing", "Insurance",     "STATE FARM HOME INS",     "Alex",  "annual",     1_500, 0.05, None),
    ("Housing", "Utilities",     "ELECTRIC COMPANY",        "Alex",  "monthly",      165, 0.20, {1:1.4,2:1.3,7:1.5,8:1.6,12:1.3}),
    ("Housing", "Utilities",     "CITY WATER",              "Alex",  "monthly",       72, 0.10, None),
    ("Housing", "Utilities",     "INTERNET",                "Alex",  "monthly",       75, 0.02, None),
    ("Housing", "Utilities",     "NATURAL GAS",             "Alex",  "monthly",       55, 0.30, {11:1.6,12:1.8,1:1.9,2:1.8,3:1.4}),
    ("Housing", "Maintenance",   "HOME DEPOT",              "either", "n_per_year:6", 120, 0.50, None),
    ("Housing", "Maintenance",   "HANDYMAN",                "Alex",  "n_per_year:3",  340, 0.40, None),

    # ---- Food ----
    ("Food", "Groceries",        "WHOLE FOODS",             "either","weekly",        140, 0.30, None),
    ("Food", "Groceries",        "TRADER JOE'S",            "either","weekly",         75, 0.35, None),
    ("Food", "Groceries",        "SAFEWAY",                 "either","n_per_year:24",  62, 0.40, None),
    ("Food", "Restaurants",      "CHIPOTLE",                "either","weekly",         24, 0.25, None),
    ("Food", "Restaurants",      "LOCAL BISTRO",            "Alex",  "n_per_year:14",  85, 0.40, None),
    ("Food", "Restaurants",      "SUSHI HOUSE",             "Sam",   "n_per_year:10",  68, 0.35, None),
    ("Food", "Restaurants",      "STARBUCKS",               "either","n_per_year:90",   6, 0.30, None),
    ("Food", "Delivery",         "DOORDASH",                "either","n_per_year:24",  35, 0.50, None),

    # ---- Travel (modest: one summer family trip + occasional weekends) ----
    ("Travel", "Flights",        "DOMESTIC AIRLINE",        "Alex",  "n_per_year:3",  340, 0.30, {6:1.6,7:1.7,11:1.3,12:1.4}),
    ("Travel", "Flights",        "DOMESTIC AIRLINE",        "Sam",   "n_per_year:2",  340, 0.30, {6:1.6,7:1.7,11:1.3,12:1.4}),
    ("Travel", "Hotels",         "HOTEL CHAIN",             "Alex",  "n_per_year:5",  220, 0.35, {6:1.5,7:1.7}),
    ("Travel", "Hotels",         "AIRBNB",                  "Sam",   "n_per_year:2",  380, 0.40, {6:1.6,7:1.7}),
    ("Travel", "Activities",     "VACATION ACTIVITIES",     "Alex",  "n_per_year:6",   75, 0.45, {6:1.6,7:1.8}),

    # ---- Kids (public school + after-school + activities) ----
    ("Kids", "After School",     "AFTER SCHOOL CARE",       "Sam",   "monthly",       420, 0.05, None),
    ("Kids", "Activities",       "YOUTH SOCCER",            "Sam",   "n_per_year:4",  140, 0.10, None),
    ("Kids", "Activities",       "MUSIC LESSONS",           "Sam",   "monthly",       180, 0.05, None),
    ("Kids", "Activities",       "SWIM CLASS",              "Alex",  "n_per_year:4",  160, 0.10, None),
    ("Kids", "Camps",            "SUMMER DAY CAMP",         "Sam",   "n_per_year:2",  650, 0.10, {6:2,7:2}),
    ("Kids", "Clothing",         "OLD NAVY",                "either","n_per_year:8",   75, 0.40, {8:1.6,12:1.5}),

    # ---- Health ----
    ("Health", "Medical",        "PEDIATRICIAN COPAY",      "Sam",   "n_per_year:6",   45, 0.10, None),
    ("Health", "Medical",        "DENTIST",                 "either","n_per_year:5",  140, 0.30, None),
    ("Health", "Pharmacy",       "CVS PHARMACY",            "either","n_per_year:14",  32, 0.40, None),
    ("Health", "Fitness",        "YMCA FAMILY",             "Alex",  "monthly",        92, 0.00, None),

    # ---- Subscriptions ----
    ("Subscriptions", "Streaming","NETFLIX",                "Alex",  "monthly",        18, 0.00, None),
    ("Subscriptions", "Streaming","SPOTIFY FAMILY",         "Alex",  "monthly",        17, 0.00, None),
    ("Subscriptions", "Streaming","DISNEY+",                "Sam",   "monthly",        14, 0.00, None),
    ("Subscriptions", "Software", "ICLOUD STORAGE",         "Alex",  "monthly",         3, 0.00, None),
    ("Subscriptions", "Software", "1PASSWORD",              "Sam",   "annual",         60, 0.00, None),
    ("Subscriptions", "News",     "LOCAL NEWSPAPER",        "Alex",  "monthly",        15, 0.00, None),

    # ---- Shopping ----
    ("Shopping", "Clothing",     "GAP",                     "Sam",   "n_per_year:6",  110, 0.50, {11:1.6,12:1.8}),
    ("Shopping", "Home Goods",   "AMAZON",                  "either","n_per_year:42",  52, 0.60, {11:1.5,12:1.8}),
    ("Shopping", "Home Goods",   "TARGET",                  "either","n_per_year:24",  72, 0.50, None),

    # ---- Pets ----
    ("Pets", "Vet",              "ANIMAL HOSPITAL",         "Sam",   "n_per_year:3",  220, 0.40, None),
    ("Pets", "Food",             "CHEWY",                   "Sam",   "monthly",        72, 0.10, None),

    # ---- Transport ----
    ("Transport", "Gas",         "GAS STATION",             "either","n_per_year:36",  52, 0.30, None),
    ("Transport", "Rideshare",   "UBER",                    "either","n_per_year:18",  22, 0.50, None),
    ("Transport", "Auto Service","AUTO SERVICE",            "Alex",  "n_per_year:2",  280, 0.40, None),

    # ---- Gifts (Dec-heavy) ----
    ("Gifts", "Family",          "AMAZON GIFTS",            "Sam",   "n_per_year:6",   85, 0.60, {11:2,12:3}),
    ("Gifts", "Family",          "ETSY",                    "Sam",   "n_per_year:4",   45, 0.60, {11:1.8,12:2.5}),
]


def expand_pattern(pattern, start: date, end: date):
    cat, sub, desc, who, cadence, base, jitter, season = pattern
    rows = []

    def amount_for(d: date) -> float:
        mult = 1.0
        if season:
            mult *= season.get(d.month, 1.0)
        amt = base * mult * (1 + random.uniform(-jitter, jitter))
        return round(max(amt, 0.5), 2)

    def pick_source(d: date) -> str:
        if who == "either":
            person = random.choice(PEOPLE)
        else:
            person = who
        return random.choice(SOURCES_BY_PERSON[person])

    if cadence == "monthly":
        d = start.replace(day=random.randint(1, 6))
        while d <= end:
            rows.append((d, pick_source(d), desc, cat, sub, amount_for(d)))
            # next month, same approx day
            year, month = d.year, d.month + 1
            if month > 12:
                year, month = year + 1, 1
            d = date(year, month, min(28, random.randint(1, 8)))
    elif cadence == "weekly":
        d = start + timedelta(days=random.randint(0, 6))
        while d <= end:
            rows.append((d, pick_source(d), desc, cat, sub, amount_for(d)))
            d += timedelta(days=7)
    elif cadence == "biweekly":
        d = start + timedelta(days=random.randint(0, 13))
        while d <= end:
            rows.append((d, pick_source(d), desc, cat, sub, amount_for(d)))
            d += timedelta(days=14)
    elif cadence.startswith("n_per_year:"):
        n = int(cadence.split(":")[1])
        total_days = (end - start).days
        years = max(total_days / 365.25, 0.01)
        count = max(1, int(round(n * years)))
        for _ in range(count):
            offset = random.randint(0, total_days)
            d = start + timedelta(days=offset)
            rows.append((d, pick_source(d), desc, cat, sub, amount_for(d)))
    elif cadence == "annual":
        # one per calendar year, plus year-bounded
        year = start.year
        while date(year, 1, 1) <= end:
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            d = date(year, month, day)
            if start <= d <= end:
                rows.append((d, pick_source(d), desc, cat, sub, amount_for(d)))
            year += 1
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    start = date(2025, 3, 1)
    end = date(2026, 4, 30)

    rows = []
    for pat in PATTERNS:
        rows.extend(expand_pattern(pat, start, end))

    df = pd.DataFrame(
        rows,
        columns=["Date", "Source", "Description", "Category", "Subcategory", "Amount"],
    )
    df["Original Category"] = ""
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%m/%d/%Y")
    df = df.sort_values(["Date", "Source"]).reset_index(drop=True)
    df.to_csv(CSV_PATH, index=False)
    total = df["Amount"].sum()
    print(f"Wrote {len(df):,} rows · ${total:,.0f} total · {CSV_PATH}")

    # Run charts.py against the synthetic CSV
    print(f"Rendering charts via {CHARTS_SCRIPT.relative_to(ROOT)}…")
    res = subprocess.run(
        [sys.executable, str(CHARTS_SCRIPT), str(CSV_PATH), "--out", str(OUT_DIR)],
        cwd=ROOT,
    )
    if res.returncode != 0:
        sys.exit(res.returncode)
    print(f"Done. Charts written to {OUT_DIR}")


if __name__ == "__main__":
    main()
