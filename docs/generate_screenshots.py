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
PATTERNS = [
    # ---- Housing (the spine: mortgage + utilities + maintenance) ----
    ("Housing", "Mortgage",      "ROCKET MORTGAGE",         "Alex",  "monthly",  4_280, 0.00, None),
    ("Housing", "Property Tax",  "COUNTY TAX COLLECTOR",    "Alex",  "n_per_year:2", 5_400, 0.05, None),
    ("Housing", "Insurance",     "STATE FARM HOME INS",     "Alex",  "annual",     2_100, 0.05, None),
    ("Housing", "Utilities",     "PG&E ELECTRIC",           "Alex",  "monthly",      210, 0.20, {1:1.4,2:1.3,7:1.5,8:1.6,12:1.3}),
    ("Housing", "Utilities",     "CITY WATER",              "Alex",  "monthly",       95, 0.10, None),
    ("Housing", "Utilities",     "COMCAST INTERNET",        "Alex",  "monthly",       89, 0.02, None),
    ("Housing", "Maintenance",   "HOME DEPOT",              "either", "n_per_year:8", 180, 0.50, None),
    ("Housing", "Maintenance",   "HANDYMAN SERVICES",       "Alex",  "n_per_year:4",  450, 0.40, None),
    ("Housing", "Cleaning",      "MARIA CLEANING SERVICE",  "Sam",   "biweekly",      180, 0.05, None),

    # ---- Food ----
    ("Food", "Groceries",        "WHOLE FOODS",             "either","weekly",        165, 0.30, None),
    ("Food", "Groceries",        "TRADER JOE'S",            "either","weekly",         85, 0.35, None),
    ("Food", "Groceries",        "SAFEWAY",                 "either","n_per_year:30",  68, 0.40, None),
    ("Food", "Restaurants",      "CHIPOTLE",                "either","weekly",         28, 0.25, None),
    ("Food", "Restaurants",      "LOCAL BISTRO",            "Alex",  "n_per_year:20", 145, 0.40, None),
    ("Food", "Restaurants",      "SUSHI HOUSE",             "Sam",   "n_per_year:18",  92, 0.35, None),
    ("Food", "Restaurants",      "STARBUCKS",               "either","n_per_year:120",  7, 0.30, None),
    ("Food", "Delivery",         "DOORDASH",                "either","n_per_year:35",  42, 0.50, None),

    # ---- Travel (seasonal: spring break + summer + Thanksgiving + Xmas) ----
    ("Travel", "Flights",        "UNITED AIRLINES",         "Alex",  "n_per_year:6",  680, 0.40, {3:1.3,6:1.5,7:1.6,11:1.4,12:1.5}),
    ("Travel", "Flights",        "DELTA AIR LINES",         "Sam",   "n_per_year:4",  520, 0.40, {3:1.3,6:1.5,7:1.6,11:1.4,12:1.5}),
    ("Travel", "Hotels",         "MARRIOTT",                "Alex",  "n_per_year:6",  420, 0.50, {6:1.5,7:1.7,12:1.4}),
    ("Travel", "Hotels",         "AIRBNB",                  "Sam",   "n_per_year:4",  680, 0.45, {6:1.4,7:1.6,11:1.3}),
    ("Travel", "Activities",     "CITY TOURS",              "Alex",  "n_per_year:8",  140, 0.45, {6:1.6,7:1.7,12:1.3}),

    # ---- Holiday Home (smaller mortgage + utilities) ----
    ("Holiday Home", "Mortgage", "VAC HOME MORTGAGE",       "Alex",  "monthly",     1_490, 0.00, None),
    ("Holiday Home", "Utilities","MOUNTAIN POWER CO-OP",    "Alex",  "monthly",       145, 0.30, {1:1.5,2:1.4,7:1.3}),
    ("Holiday Home", "HOA",      "LAKE COMMUNITY HOA",      "Alex",  "n_per_year:4",  340, 0.05, None),
    ("Holiday Home", "Maintenance","CABIN MAINTENANCE",     "Alex",  "n_per_year:6",  280, 0.50, None),

    # ---- Kids ----
    ("Kids", "Schools",          "PRIVATE SCHOOL TUITION",  "Sam",   "n_per_year:10", 2_900, 0.02, None),
    ("Kids", "Activities",       "SOCCER LEAGUE",           "Sam",   "n_per_year:4",  185, 0.10, None),
    ("Kids", "Activities",       "MUSIC LESSONS",           "Sam",   "monthly",       240, 0.05, None),
    ("Kids", "Camps",            "SUMMER CAMP",             "Sam",   "n_per_year:2", 1_650, 0.05, {6:2,7:2}),
    ("Kids", "Clothing",         "CARTERS",                 "either","n_per_year:10", 110, 0.40, {8:1.6,12:1.5}),

    # ---- Health ----
    ("Health", "Medical",        "PEDIATRICIAN COPAY",      "Sam",   "n_per_year:8",   55, 0.10, None),
    ("Health", "Medical",        "DENTIST",                 "either","n_per_year:6",  220, 0.30, None),
    ("Health", "Pharmacy",       "CVS PHARMACY",            "either","n_per_year:18",  38, 0.40, None),
    ("Health", "Fitness",        "EQUINOX",                 "Alex",  "monthly",       265, 0.00, None),

    # ---- Subscriptions ----
    ("Subscriptions", "Streaming","NETFLIX",                "Alex",  "monthly",        18, 0.00, None),
    ("Subscriptions", "Streaming","SPOTIFY FAMILY",         "Alex",  "monthly",        17, 0.00, None),
    ("Subscriptions", "Streaming","DISNEY+",                "Sam",   "monthly",        14, 0.00, None),
    ("Subscriptions", "Streaming","HBO MAX",                "Sam",   "monthly",        16, 0.00, None),
    ("Subscriptions", "Software", "ICLOUD STORAGE",         "Alex",  "monthly",         3, 0.00, None),
    ("Subscriptions", "Software", "ADOBE CC",               "Alex",  "monthly",        55, 0.00, None),
    ("Subscriptions", "Software", "1PASSWORD",              "Sam",   "annual",         60, 0.00, None),
    ("Subscriptions", "News",     "NYT DIGITAL",            "Alex",  "monthly",        22, 0.00, None),
    ("Subscriptions", "News",     "WSJ",                    "Sam",   "monthly",        39, 0.00, None),

    # ---- Shopping ----
    ("Shopping", "Clothing",     "NORDSTROM",               "Sam",   "n_per_year:8",  220, 0.50, {11:1.6,12:1.8}),
    ("Shopping", "Clothing",     "PATAGONIA",               "Alex",  "n_per_year:4",  185, 0.40, {11:1.5,12:1.7}),
    ("Shopping", "Home Goods",   "AMAZON",                  "either","n_per_year:50",  68, 0.60, {11:1.5,12:1.8}),
    ("Shopping", "Home Goods",   "TARGET",                  "either","n_per_year:24",  85, 0.50, None),

    # ---- Pets ----
    ("Pets", "Vet",              "ANIMAL HOSPITAL",         "Sam",   "n_per_year:4",  280, 0.40, None),
    ("Pets", "Food",             "CHEWY",                   "Sam",   "monthly",        92, 0.10, None),

    # ---- Transport ----
    ("Transport", "Gas",         "SHELL",                   "either","n_per_year:36",  58, 0.30, None),
    ("Transport", "Rideshare",   "UBER",                    "either","n_per_year:30",  24, 0.50, None),
    ("Transport", "Auto Service","TOYOTA SERVICE",          "Alex",  "n_per_year:3",  340, 0.40, None),

    # ---- Gifts (Dec-heavy) ----
    ("Gifts", "Family",          "AMAZON GIFTS",            "Sam",   "n_per_year:8",  120, 0.60, {11:2,12:3}),
    ("Gifts", "Family",          "ETSY",                    "Sam",   "n_per_year:6",   65, 0.60, {11:1.8,12:2.5}),
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
