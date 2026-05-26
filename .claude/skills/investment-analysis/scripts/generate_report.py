#!/usr/bin/env python3
"""
Phase 5 (report half): build a question-driven consolidated report.

The report is structured around the questions a portfolio holder typically
asks when looking at their holdings in aggregate. Each section answers one
question, with tables built from the underlying classified data and
two inline charts (asset-category pie + tax-location heatmap) where the visual adds
something the table doesn't.

Reads:
- positions.csv (one row per original position)
- positions_classified.csv (asset-class-decomposed, has issuer/sector/region)
- Allocation.csv, Concentration.md, TaxLocation.md, Fees.csv, Anomalies.md
- _analyze_summary.json
- investment_analysis_config.yaml (for thresholds + employer registry)
- (optionally) prior positions_classified.csv for refresh delta

Writes:
- Investment Analysis Report.md  (primary consolidated artifact)
- Investment Positions.csv       (flat user-facing ledger)

Companion CSV/MD/PNG files written by analyze.py and generate_charts.py stay
in the folder unchanged as drill-down material.

Usage:
    python generate_report.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from _config_discover import auto_discover_config


SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "references" / "data"

SLEEVE_MAP = {
    "us_equity": "equity",
    "intl_dev_equity": "equity",
    "intl_em_equity": "equity",
    "us_bonds": "fixed_income",
    "intl_bonds": "fixed_income",
    "cash": "cash",
    "real_estate": "real_estate",
    "alt_concentrated": "alternatives",
    "crypto": "alternatives",
    "unknown": "unknown",
}

THRESHOLDS_DEFAULTS = {
    "single_name": 0.05,
    "single_sector": 0.25,
    "single_issuer": 0.25,
    "single_fund_in_sleeve": 0.50,
    "idle_cash_in_account": 0.05,
    "idle_cash_total": 0.02,
    "dust_position": 1000,
}

GEO_LABELS = {
    "us_equity": "United States",
    "intl_dev_equity": "International developed",
    "intl_em_equity": "Emerging markets",
}

WRAPPER_CREDIT_ACCOUNT_TYPES = {"nqdc", "ltip", "restricted_alt", "options", "profit_units"}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    if not path or not path.is_file():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def fmt_money(x: float) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:.1%}"


def md_image(io_dir: Path, filename: str, alt: str, ref_prefix: str = ".analysis/") -> str:
    """Embed a chart image. `io_dir` is where the PNG lives on disk;
    `ref_prefix` is what the report's relative href looks like."""
    if not (io_dir / filename).is_file():
        return ""
    return f"![{alt}]({ref_prefix}{filename})"


def md_table(headers: list[str], rows: list[list[str]],
             align: Optional[list[str]] = None) -> str:
    if not rows:
        return "_No data._"
    align = align or ["l"] * len(headers)
    sep_map = {"l": ":---", "r": "---:", "c": ":---:"}
    sep_row = "| " + " | ".join(sep_map.get(a, ":---") for a in align) + " |"
    head_row = "| " + " | ".join(headers) + " |"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([head_row, sep_row, *body])


# -----------------------------------------------------------------------------
# Ticker → clean name lookup
# -----------------------------------------------------------------------------

def load_name_lookup() -> dict[str, str]:
    """Build {ticker: clean_name} from the curated fund + stock registries."""
    names: dict[str, str] = {}
    fund_map = load_yaml(DATA_DIR / "fund_asset_class_map.yaml")
    for ticker, data in fund_map.items():
        if isinstance(data, dict) and "name" in data:
            names[ticker.upper()] = data["name"]
    stock_map = load_yaml(DATA_DIR / "stock_sector_map.yaml")
    for ticker, data in stock_map.items():
        if isinstance(data, dict) and "issuer" in data:
            names[ticker.upper()] = data["issuer"]
    return names


def load_stock_issuer_lookup() -> dict[str, str]:
    """Build {ticker: issuer_name} for stocks only."""
    out: dict[str, str] = {}
    stock_map = load_yaml(DATA_DIR / "stock_sector_map.yaml")
    for ticker, data in stock_map.items():
        if isinstance(data, dict) and "issuer" in data:
            out[ticker.upper()] = data["issuer"]
    return out


def employer_name_set(config: dict) -> set[str]:
    """Return lowercased set of distinctive employer brand tokens for matching.

    Only the registry key and the first word of the display name are kept —
    these are the brand-distinctive tokens. Generic suffixes like "Corporation",
    "Asset Management", "of America" are dropped to avoid false positives
    (e.g., "employer_a ... America" matching "American Water Works").
    """
    names: set[str] = set()
    for key, val in (config.get("employers") or {}).items():
        k = str(key).lower().strip()
        if len(k) >= 3:
            names.add(k)
        if isinstance(val, dict) and val.get("name"):
            first = re.split(r"[\s,]+", val["name"].lower().strip())[0]
            if len(first) >= 3:
                names.add(first)
    return names


def employer_token_matches(issuer: str, tokens: set[str]) -> bool:
    """Word-boundary match — avoids 'america' matching 'american'."""
    issuer_l = issuer.lower()
    for tok in tokens:
        if re.search(r"\b" + re.escape(tok) + r"\b", issuer_l):
            return True
    return False


def clean_desc(ticker: str, raw: str, lookup: dict[str, str]) -> str:
    """Return a human-readable description for a ticker."""
    t = (ticker or "").upper().strip()
    if t in lookup:
        return lookup[t]
    if t == "CASH":
        return "Cash"
    if t == "RE":
        return raw or "Real estate"

    s = (raw or "").strip()
    if not s:
        return ticker or ""

    # Strip quality markers and trailing punctuation
    s = re.sub(r"[◊◇‡†*]+\s*$", "", s).strip()
    s = s.rstrip(",.")
    # Insert spaces between lower→upper transitions (CamelCase)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    # Insert spaces between letter↔digit transitions
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", s)
    # Insert spaces at ALLCAPS→Capital+lower transitions (PIMCOReal → PIMCO Real)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    # Title-case if it's still all-caps and has no internal lowercase
    if s.isupper():
        s = s.title()
    # Fix common artifacts and re-capitalize acronyms
    s = s.replace("&Co", " & Co").replace("Etf", "ETF").replace(" Inc ", " Inc. ")
    s = re.sub(r"\bUs\b", "US", s)
    s = re.sub(r"\bUk\b", "UK", s)
    s = re.sub(r"\bEu\b", "EU", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def position_kind(section: str) -> str:
    return {
        "etf": "ETF",
        "mutual_fund": "Mutual fund",
        "equity": "Stock",
        "bond": "Bond",
        "cash": "Cash",
        "real_estate": "Real estate",
        "other": "Other",
    }.get(section, section.title() if section else "")


# -----------------------------------------------------------------------------
# Position ledger CSV (unchanged shape)
# -----------------------------------------------------------------------------

def write_positions_ledger(df: pd.DataFrame, out_path: Path) -> None:
    cols = [
        "account", "account_type", "owner", "employer", "ticker", "description",
        "section", "asset_class", "asset_class_weight",
        "weighted_value_gross", "weighted_value_net",
        "cost_basis", "unrealized_gain",
        "vested", "vest_date",
        "expense_ratio", "distribution_character",
        "sector", "region", "issuer", "sub_asset",
        "source_file",
    ]
    cols = [c for c in cols if c in df.columns]
    df[cols].to_csv(out_path, index=False)


# -----------------------------------------------------------------------------
# Refresh delta
# -----------------------------------------------------------------------------

def find_prior_classified(folder: Path) -> Path | None:
    candidates = list(folder.glob("positions_classified.*.csv"))
    return sorted(candidates)[-1] if candidates else None


def compute_delta(current: pd.DataFrame, prior: pd.DataFrame) -> dict:
    cur = current.groupby("ticker")["weighted_value_gross"].sum()
    pri = prior.groupby("ticker")["weighted_value_gross"].sum()
    new_t = sorted(set(cur.index) - set(pri.index))
    rem_t = sorted(set(pri.index) - set(cur.index))
    changes = []
    for t in set(cur.index) & set(pri.index):
        d = cur[t] - pri[t]
        if abs(d) > 100:
            changes.append({"ticker": t, "delta": d, "from": pri[t], "to": cur[t]})
    changes.sort(key=lambda x: -abs(x["delta"]))
    return {
        "total_delta": cur.sum() - pri.sum(),
        "total_pct_delta": (cur.sum() - pri.sum()) / pri.sum() if pri.sum() else 0,
        "new_tickers": new_t, "removed_tickers": rem_t,
        "top_changes": changes[:15],
    }


# -----------------------------------------------------------------------------
# Section: 1. How much do I have, and where does it sit?
# -----------------------------------------------------------------------------

def section_overview(positions: pd.DataFrame, summary: dict, io_dir: Path) -> list[str]:
    total = summary.get("total_gross", positions["market_value_gross"].sum())
    sleeve_totals = summary.get("sleeve_totals", {})

    lines = [
        "## 1. How much do I have, and where does it sit?",
        "",
        f"**Total investable (vested, gross): {fmt_money(total)}**",
        "",
        "Two complementary views: the **asset category** pie shows composition at the "
        "broadest level (equity / fixed income / cash / real estate). The **account** "
        "pie shows where the dollars actually live across your accounts. Each account is "
        "colored by its dominant asset category so the two views read consistently.",
        "",
    ]

    sleeve_img = md_image(io_dir, "chart_allocation_pie.png", "Asset category allocation")
    acct_img = md_image(io_dir, "chart_account_pie.png", "By account")
    if sleeve_img and acct_img:
        # Side-by-side via a two-column markdown table (renders well in most viewers)
        lines.append(f"| {sleeve_img} | {acct_img} |")
        lines.append("|:---:|:---:|")
        lines.append("| **By asset category** | **By account** |")
        lines.append("")
    elif sleeve_img:
        lines.extend([sleeve_img, ""])

    # Commentary
    if sleeve_totals:
        by_acct = (positions.groupby(["account", "account_type"])["market_value_gross"]
                            .sum().sort_values(ascending=False))
        biggest = max(sleeve_totals.items(), key=lambda x: x[1])
        top_acct = by_acct.index[0]
        top_acct_v = by_acct.iloc[0]
        lines.append(
            f"**Observation.** The largest asset category is **{biggest[0].replace('_', ' ')}** at "
            f"{fmt_pct(biggest[1] / total)} ({fmt_money(biggest[1])}). The largest single account is "
            f"**{top_acct[0]}** ({top_acct[1]}) at {fmt_pct(top_acct_v / total)} of investable."
        )
        lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Section: 2. What do I actually own?
# -----------------------------------------------------------------------------

def section_holdings(positions: pd.DataFrame, lookup: dict[str, str]) -> list[str]:
    lines = [
        "## 3. What do I actually own?",
        "",
        "_Top 20 holdings by gross value, aggregated across accounts. Full ledger in_ `Investment Positions.csv`_._",
        "",
    ]
    pos = positions.copy()
    pos["clean_desc"] = pos.apply(
        lambda r: clean_desc(r["ticker"], r.get("description", ""), lookup), axis=1)
    pos["kind"] = pos["section"].fillna("").map(position_kind)

    by_ticker = (pos.groupby(["ticker", "clean_desc", "kind"], as_index=False)
                    .agg(total_value=("market_value_gross", "sum"),
                         accounts=("account", lambda x: ", ".join(sorted(set(x))))))
    by_ticker = by_ticker.sort_values("total_value", ascending=False).head(20)

    total = positions["market_value_gross"].sum()
    rows = []
    for _, r in by_ticker.iterrows():
        accounts = r["accounts"]
        if len(accounts) > 32:
            accounts = accounts[:29] + "…"
        rows.append([
            f"`{r['ticker']}`", r["clean_desc"], r["kind"], accounts,
            fmt_money(r["total_value"]), fmt_pct(r["total_value"] / total if total else 0),
        ])
    lines.append(md_table(
        ["Ticker", "Name", "Kind", "Account(s)", "$", "% of investable"],
        rows, ["l", "l", "l", "l", "r", "r"]
    ))
    lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Section: 3. Asset mix through-the-fund
# -----------------------------------------------------------------------------

def section_allocation(classified: pd.DataFrame, io_dir: Path,
                         sector_threshold: float) -> list[str]:
    lines = [
        "## 2. What's my real asset mix once I look through every fund?",
        "",
        "_Every fund is decomposed into its underlying exposures. A target-date fund at 50% equity contributes 50% of its value to the equity category here, not 100% to \"funds\"._",
        "",
    ]
    total = classified["weighted_value_gross"].sum()

    # Asset classes
    asset_labels = {
        "us_equity": "US equity",
        "intl_dev_equity": "International developed equity",
        "intl_em_equity": "Emerging-market equity",
        "us_bonds": "US bonds",
        "intl_bonds": "International bonds",
        "cash": "Cash",
        "real_estate": "Real estate",
        "alt_concentrated": "Concentrated alternatives",
        "crypto": "Crypto",
        "unknown": "Unknown",
    }
    by_class = classified.groupby("asset_class")["weighted_value_gross"].sum().sort_values(ascending=False)
    rows = [[asset_labels.get(ac, ac.replace("_", " ")), fmt_money(v), fmt_pct(v / total if total else 0)]
            for ac, v in by_class.items()]
    lines.append("**Asset class:**")
    lines.append("")
    lines.append(md_table(["Asset class", "$", "% of investable"], rows, ["l", "r", "r"]))
    lines.append("")

    # Equity geography
    eq_classes = ["us_equity", "intl_dev_equity", "intl_em_equity"]
    eq = classified[classified["asset_class"].isin(eq_classes)]
    eq_total = eq["weighted_value_gross"].sum()
    if eq_total > 0:
        by_geo = eq.groupby("asset_class")["weighted_value_gross"].sum().sort_values(ascending=False)
        rows = [[GEO_LABELS.get(k, k), fmt_money(v), fmt_pct(v / eq_total)]
                for k, v in by_geo.items()]
        lines.append("**Equity geography:**")
        lines.append("")
        lines.append(md_table(["Region", "$", "% of equity"], rows, ["l", "r", "r"]))
        lines.append("")

    # Fixed income split
    fi_classes = ["us_bonds", "intl_bonds"]
    fi_labels = {"us_bonds": "US bonds", "intl_bonds": "International bonds"}
    fi = classified[classified["asset_class"].isin(fi_classes)]
    fi_total = fi["weighted_value_gross"].sum()
    if fi_total > 0:
        by_fi = fi.groupby("asset_class")["weighted_value_gross"].sum().sort_values(ascending=False)
        rows = [[fi_labels.get(k, k), fmt_money(v), fmt_pct(v / fi_total)]
                for k, v in by_fi.items()]
        lines.append("**Fixed income split:**")
        lines.append("")
        lines.append(md_table(["Region", "$", "% of bonds"], rows, ["l", "r", "r"]))
        lines.append("")

    # Sector breakdown (through-the-fund) — moved here from Section 4 because
    # this is the same KIND of compositional view as asset class and geography.
    sectors = parse_sector_concentration(io_dir / "Concentration.md")
    flagged_sectors: list[str] = []
    if sectors:
        sectors_sorted = sorted(sectors, key=lambda r: -r["pct"])
        rows = []
        for r in sectors_sorted:
            sector_lbl = r["sector"].replace("_", " ").title()
            flag = "✓" if r["pct"] >= sector_threshold else ""
            if r["pct"] >= sector_threshold:
                flagged_sectors.append(f"{sector_lbl} ({fmt_pct(r['pct'])})")
            rows.append([sector_lbl, fmt_money(r["total"]),
                          fmt_pct(r["pct"]), flag])
        lines.append("**Sector exposure (through-the-fund):**")
        lines.append("")
        lines.append(
            f"_GICS sector breakdown with broad-market ETFs / mutual funds "
            f"decomposed at index weight. Flag column = above the configured "
            f"**{fmt_pct(sector_threshold)} of equity** threshold._"
        )
        lines.append("")
        lines.append(md_table(
            ["Sector", "Total $", "% of equity", "Above threshold"],
            rows, ["l", "r", "r", "c"],
        ))
        lines.append("")

    # Commentary
    if eq_total > 0:
        us = classified[classified["asset_class"] == "us_equity"]["weighted_value_gross"].sum()
        intl = eq_total - us
        obs = (
            f"**Observation.** Equity category is **{fmt_pct(us / eq_total)} domestic / "
            f"{fmt_pct(intl / eq_total)} international**."
        )
        if flagged_sectors:
            obs += f" Sector concentration above threshold: **{', '.join(flagged_sectors)}**."
        lines.append(obs)
        lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Section: 4. Where am I concentrated?
# -----------------------------------------------------------------------------

def parse_sector_concentration(path: Path) -> list[dict]:
    """Read the sector table out of Concentration.md, return sorted list of dicts."""
    if not path.is_file():
        return []
    content = path.read_text()
    m = re.search(r"## Sector concentration.*?(?=\n## |\Z)", content, re.DOTALL)
    if not m:
        return []
    out = []
    for line in m.group(0).splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 5 or cols[0].lower() == "sector":
            continue
        try:
            total = float(cols[3].replace("$", "").replace(",", ""))
            pct = float(cols[4].rstrip("%")) / 100
            out.append({"sector": cols[0], "total": total, "pct": pct})
        except (ValueError, IndexError):
            continue
    out.sort(key=lambda r: -r["pct"])
    return out


def section_concentration(positions: pd.DataFrame, classified: pd.DataFrame,
                          io_dir: Path, thresholds: dict, config: dict,
                          lookup: dict[str, str]) -> list[str]:
    total = positions["market_value_gross"].sum()
    lines = [
        "## 4. Where am I concentrated?",
        "",
        "_Concentration takes several forms. Each subsection below shows a different cut, with its own threshold. Threshold flags are descriptive — they call out where a holding sits **above** the configured line. The line is a fact about the data, not a judgement about whether it should be there._",
        "",
    ]

    pos = positions.copy()
    pos["clean_desc"] = pos.apply(
        lambda r: clean_desc(r["ticker"], r.get("description", ""), lookup), axis=1)
    pos["kind"] = pos["section"].fillna("").map(position_kind)

    # -- 4a. Largest positions overall --
    lines.append("### 4a. Largest positions (any kind)")
    lines.append("")
    lines.append(
        "_Largest line items by gross value — funds, stocks, properties, cash all mixed. "
        "A fund flagged here is internally diversified; it's a large position, not a single-name risk. "
        "Single-name concentration is shown separately below._"
    )
    lines.append("")
    top_pos = (pos.groupby(["ticker", "clean_desc", "kind"], as_index=False)
                  ["market_value_gross"].sum()
                  .sort_values("market_value_gross", ascending=False)
                  .head(10))
    rows = []
    for _, r in top_pos.iterrows():
        rows.append([
            f"`{r['ticker']}`", r["clean_desc"], r["kind"],
            fmt_money(r["market_value_gross"]),
            fmt_pct(r["market_value_gross"] / total if total else 0),
        ])
    lines.append(md_table(
        ["Ticker", "Name", "Kind", "$", "% of investable"],
        rows, ["l", "l", "l", "r", "r"]
    ))
    lines.append("")

    # -- 4b. Single-stock concentration --
    sn_threshold = thresholds.get("single_name", 0.05)
    lines.append("### 4b. Single-stock concentration (direct holdings only)")
    lines.append("")
    lines.append(
        f"_Direct individual-stock holdings only — each position is undivided single-name risk. "
        f"**Above threshold** below means **more than {fmt_pct(sn_threshold)} of investable** held "
        f"in a single stock._"
    )
    lines.append("")
    stocks = pos[pos["section"] == "equity"]
    if len(stocks) > 0:
        by_stock = (stocks.groupby(["ticker", "clean_desc"], as_index=False)
                          ["market_value_gross"].sum()
                          .sort_values("market_value_gross", ascending=False).head(15))
        rows = []
        for _, r in by_stock.iterrows():
            pct = r["market_value_gross"] / total if total else 0
            flag = "✓" if pct >= sn_threshold else ""
            rows.append([f"`{r['ticker']}`", r["clean_desc"],
                         fmt_money(r["market_value_gross"]), fmt_pct(pct), flag])
        any_flagged = any(r[-1] == "✓" for r in rows)
        lines.append(md_table(
            ["Ticker", "Name", "$", "% of investable", "Above threshold"],
            rows, ["l", "l", "r", "r", "c"]
        ))
        lines.append("")
        if not any_flagged:
            lines.append(f"_No direct stock holding crosses the {fmt_pct(sn_threshold)} threshold._")
            lines.append("")
    else:
        lines.append("_No direct stock holdings observed._")
        lines.append("")

    # (Sector breakdown lives in Section 3 — it's a compositional view, not a
    #  concentration cut. Cross-reference here for users who looked for it.)

    # -- 4c. Single-fund concentration within sleeve --
    fund_threshold = thresholds.get("single_fund_in_sleeve", 0.50)
    lines.append("### 4c. Single-fund concentration within an asset category")
    lines.append("")
    lines.append(
        f"_One fund holding more than **{fmt_pct(fund_threshold)} of an entire asset category**. "
        f"The fund itself may be diversified, but the category depends on a single fund manager and tracking methodology._"
    )
    lines.append("")
    cl = classified.copy()
    cl["sleeve"] = cl["asset_class"].map(SLEEVE_MAP)
    rows = []
    for sleeve in ["equity", "fixed_income", "cash", "real_estate", "alternatives"]:
        sub = cl[cl["sleeve"] == sleeve]
        if len(sub) == 0:
            continue
        sleeve_total = sub["weighted_value_gross"].sum()
        if sleeve_total <= 0:
            continue
        by_t = (sub.groupby(["ticker", "description"])["weighted_value_gross"]
                   .sum().sort_values(ascending=False))
        if len(by_t) == 0:
            continue
        top_ticker, top_desc = by_t.index[0]
        top_value = by_t.iloc[0]
        pct = top_value / sleeve_total
        flag = "✓" if pct >= fund_threshold else ""
        rows.append([
            sleeve.replace("_", " ").title(),
            f"`{top_ticker}`",
            clean_desc(top_ticker, top_desc, lookup),
            fmt_money(top_value),
            fmt_pct(pct),
            flag,
        ])
    lines.append(md_table(
        ["Asset category", "Largest", "Name", "$", "% of category", "Above threshold"],
        rows, ["l", "l", "l", "r", "r", "c"]
    ))
    lines.append("")

    # -- 4d. Wrapper credit exposure --
    iss_threshold = thresholds.get("single_issuer", 0.25)
    lines.append("### 4d. Employer / wrapper credit exposure")
    lines.append("")
    lines.append(
        "_Non-qualified deferred compensation (NQDC), profit/partnership units, and similar wrappers are structurally an **unsecured creditor claim on the employer** — money inside is exposed to the employer's solvency, separate from whatever is held within the wrapper. Holdings of the employer's stock or debt directly are listed below it._"
    )
    lines.append("")

    # Wrapper credit
    wrap = positions[positions["account_type"].isin(WRAPPER_CREDIT_ACCOUNT_TYPES)]
    employers_cfg = config.get("employers", {}) or {}
    emp_label_for = lambda key: (employers_cfg.get(key, {}).get("name")
                                  if isinstance(employers_cfg.get(key), dict)
                                  else str(key).title() if key else "(unspecified)")
    if len(wrap) > 0:
        agg = wrap.groupby(["employer", "account_type"])["market_value_gross"].sum()
        rows = []
        for (emp, atype), v in agg.sort_values(ascending=False).items():
            pct = v / total if total else 0
            flag = "✓" if pct >= iss_threshold else ""
            rows.append([
                emp_label_for(emp) if emp else "(unspecified)",
                atype.upper() if atype == "nqdc" else atype.replace("_", " "),
                fmt_money(v), fmt_pct(pct), flag,
            ])
        lines.append(
            f"**Wrapper credit exposure** (threshold: more than **{fmt_pct(iss_threshold)} of investable** "
            f"to a single employer through wrappers):"
        )
        lines.append("")
        lines.append(md_table(
            ["Employer", "Wrapper", "$", "% of investable", "Above threshold"],
            rows, ["l", "l", "r", "r", "c"]
        ))
        lines.append("")
    else:
        lines.append("_No wrapper-based employer credit exposure observed._")
        lines.append("")

    # Direct employer stock — match by actual issuer, not by wrapper-inherited employer tag.
    # A position is "employer stock" only if the ticker's issuer name overlaps with one
    # of the configured employer names.
    stock_issuers = load_stock_issuer_lookup()
    employer_tokens = employer_name_set(config)
    emp_stock_rows = []
    if employer_tokens:
        stocks_only = positions[positions["section"] == "equity"]
        for _, r in stocks_only.iterrows():
            issuer = stock_issuers.get(str(r["ticker"]).upper(), "")
            if not issuer:
                continue
            if employer_token_matches(issuer, employer_tokens):
                emp_stock_rows.append([
                    issuer,
                    f"`{r['ticker']}`",
                    fmt_money(r["market_value_gross"]),
                    fmt_pct(r["market_value_gross"] / total if total else 0),
                ])
    if emp_stock_rows:
        lines.append("**Direct employer-stock holdings:**")
        lines.append("")
        lines.append(md_table(
            ["Issuer", "Ticker", "$", "% of investable"],
            emp_stock_rows, ["l", "l", "r", "r"]
        ))
        lines.append("")
    else:
        lines.append("_No direct employer-stock holdings observed in the analyzed accounts._")
        lines.append("")

    # -- 4f. Property concentration --
    re_pos = positions[positions["section"] == "real_estate"]
    if len(re_pos) > 0:
        lines.append("### 4e. Property concentration")
        lines.append("")
        lines.append(
            "_Each investment property is an undiversified single-asset exposure — geographically, structurally, and to a single tenant base._"
        )
        lines.append("")
        rows = []
        for _, r in re_pos.iterrows():
            rows.append([
                r["account"], fmt_money(r["market_value_gross"]),
                fmt_pct(r["market_value_gross"] / total if total else 0),
            ])
        lines.append(md_table(
            ["Property (alias)", "Net equity", "% of investable"],
            rows, ["l", "r", "r"]
        ))
        lines.append("")

    return lines


# -----------------------------------------------------------------------------
# Section: 5. Tax location
# -----------------------------------------------------------------------------

def section_tax_location(io_dir: Path) -> list[str]:
    lines = [
        "## 5. Where do things sit, tax-wise?",
        "",
        "_Each asset class plotted against the wrapper that holds it. Heavy cells = larger dollars in that asset-class × wrapper combination. Exact dollar values in `.analysis/TaxLocation.md`._",
        "",
    ]
    img = md_image(io_dir, "chart_tax_location_matrix.png", "Tax location matrix")
    if img:
        lines.extend([img, ""])

    # Pull ONLY the observations block from TaxLocation.md (skip the full matrix
    # table — it's a direct duplicate of the heatmap above).
    tl_path = io_dir / "TaxLocation.md"
    if tl_path.is_file():
        content = tl_path.read_text()
        m = re.search(r"## Observations.*", content, re.DOTALL)
        if m:
            observations = re.sub(r"^## ", "### ", m.group(0), flags=re.MULTILINE)
            lines.append(observations.strip())
            lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Section: 6. Fees
# -----------------------------------------------------------------------------

def section_fees(io_dir: Path) -> list[str]:
    lines = [
        "## 6. What's it costing me to hold this?",
        "",
        "_Fund expense ratios, dollar fees annualized at current holding values. Direct stock holdings, cash, and real estate carry no fund-level ER._",
        "",
    ]
    fees_path = io_dir / "Fees.csv"
    if not fees_path.is_file():
        lines.append("_No fee data available._")
        lines.append("")
        return lines

    fees = pd.read_csv(fees_path).sort_values("annual_fee_dollars", ascending=False)
    if len(fees) == 0:
        lines.append("_No fee data available._")
        lines.append("")
        return lines

    total_fees = fees["annual_fee_dollars"].sum()
    total_held = fees["holding_value"].sum()
    weighted_er = total_fees / total_held if total_held else 0

    rows = []
    for _, r in fees.head(15).iterrows():
        share = r["annual_fee_dollars"] / total_fees if total_fees else 0
        rows.append([
            f"`{r['ticker']}`",
            fmt_money(r["holding_value"]),
            f"{r['expense_ratio'] * 100:.2f}%",
            fmt_money(r["annual_fee_dollars"]),
            fmt_pct(share),
        ])
    lines.append(md_table(
        ["Ticker", "Held $", "Expense ratio", "Annual fee $", "% of total fees"],
        rows, ["l", "r", "r", "r", "r"]
    ))
    lines.append("")
    lines.append(
        f"**Observation.** Total annualized fee load across funds: **{fmt_money(total_fees)}** "
        f"on {fmt_money(total_held)} of fund holdings. Weighted-average expense ratio: "
        f"**{weighted_er * 100:.2f}%**."
    )
    if total_fees > 0:
        top = fees.iloc[0]
        lines.append("")
        lines.append(
            f"`{top['ticker']}` is the single biggest contributor at **{fmt_money(top['annual_fee_dollars'])}/yr** "
            f"({fmt_pct(top['annual_fee_dollars'] / total_fees)} of total fees) — driven by its "
            f"{top['expense_ratio'] * 100:.2f}% expense ratio on a {fmt_money(top['holding_value'])} position."
        )
    lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Section: 7. Anomalies (no TLH pairs, no income)
# -----------------------------------------------------------------------------

def section_anomalies(io_dir: Path) -> list[str]:
    lines = [
        "## 7. Is anything in the data unusual?",
        "",
        "_Data-quality and structural observations. Each is a fact about the current state, not a recommendation._",
        "",
    ]
    ano_path = io_dir / "Anomalies.md"
    if not ano_path.is_file():
        return lines
    content = ano_path.read_text()
    # Strip everything from "## Potential TLH pairs" onward (out of scope here)
    content = re.sub(r"\n## Potential TLH pairs.*", "", content, flags=re.DOTALL)
    cleaned = re.sub(r"^# .*?\n+", "", content, count=1)
    cleaned = re.sub(r"^_.*?_\n+", "", cleaned, count=1)
    cleaned = re.sub(r"^## ", "### ", cleaned, flags=re.MULTILINE)
    lines.append(cleaned.strip())
    lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Section: 8. Delta (conditional)
# -----------------------------------------------------------------------------

def section_delta(delta: dict, num: int) -> list[str]:
    lines = [
        f"## {num}. What changed since the last refresh?",
        "",
        f"Total investable changed by **{fmt_money(delta['total_delta'])}** "
        f"({fmt_pct(delta['total_pct_delta'])}) since last refresh.",
        "",
    ]
    if delta["new_tickers"]:
        lines.append("**New positions:** " + ", ".join(f"`{t}`" for t in delta["new_tickers"][:12]))
        lines.append("")
    if delta["removed_tickers"]:
        lines.append("**Removed positions:** " + ", ".join(f"`{t}`" for t in delta["removed_tickers"][:12]))
        lines.append("")
    if delta["top_changes"]:
        rows = [[f"`{c['ticker']}`", fmt_money(c["from"]), fmt_money(c["to"]),
                 ("+" if c["delta"] >= 0 else "") + fmt_money(c["delta"])]
                for c in delta["top_changes"][:10]]
        lines.append(md_table(["Ticker", "Prior", "Current", "Δ"], rows, ["l", "r", "r", "r"]))
        lines.append("")
    return lines


# -----------------------------------------------------------------------------
# Appendix + closing
# -----------------------------------------------------------------------------

def section_appendix(io_dir: Path) -> list[str]:
    lines = [
        "## Appendix — Companion Files",
        "",
        "**Top-level deliverables** (alongside this report):",
        "",
        "- `Investment Positions.csv` — flat position ledger",
        "- `investment_analysis_config.yaml` — config used for this run (reused on refresh)",
        "",
        "**Drill-down material** in the `.analysis/` subfolder:",
        "",
        "- `.analysis/Allocation.csv` — through-the-fund allocation data",
        "- `.analysis/Concentration.md` — full concentration tables (more rows than shown above)",
        "- `.analysis/TaxLocation.md` — wrapper × asset-class matrix",
        "- `.analysis/Fees.csv` — full fee detail per holding",
        "- `.analysis/Anomalies.md` — anomaly surface (full version, including TLH pairs)",
        "- `.analysis/positions_classified.csv` — analyst-grade ledger with through-the-fund weights",
        "",
    ]
    if (io_dir / "chart_sankey.html").is_file():
        lines.append("- `.analysis/chart_sankey.html` — interactive Sankey (accounts → wrappers → asset classes)")
    if (io_dir / "chart_concentration_heat.png").is_file():
        lines.append("- `.analysis/chart_concentration_heat.png`, `chart_asset_class_bars.png`, `chart_fees_bar.png` — supplementary charts not embedded in this report")
    lines.append("")
    return lines


def section_closing() -> list[str]:
    return [
        "---",
        "",
        "## Next Step — Build a Financial Plan?",
        "",
        "This report describes **what is** — the current state of the portfolio. "
        "It deliberately stops short of prescription: no target allocation, no rebalancing moves, "
        "no \"you should\" anywhere.",
        "",
        "The natural next step is a **financial plan** that takes this snapshot as input alongside:",
        "",
        "- Spending profile (where money is going each month, run-rate burn)",
        "- Goals and horizon (retirement age, lifestyle targets, education funding, legacy intent)",
        "- Risk capacity and tolerance",
        "- Tax bracket and state",
        "",
        "From there, target allocations, tax-location moves, cash deployment, and rebalancing fall out as outputs.",
        "",
        "**Would you like to start building a financial plan?**",
        "",
    ]


# -----------------------------------------------------------------------------
# Build the full report
# -----------------------------------------------------------------------------

def build_report(positions: pd.DataFrame, classified: pd.DataFrame,
                 summary: dict, delta: dict | None, io_dir: Path,
                 config: dict) -> str:
    lookup = load_name_lookup()
    thresholds = {**THRESHOLDS_DEFAULTS, **(config.get("concentration_thresholds") or {})}

    lines: list[str] = []
    lines.extend([
        "# Investment Analysis Report",
        "",
        "_Descriptive only — describes the current state of the portfolio. "
        "No recommendations, no target allocations, no trades._",
        "",
        "This report is organized around the questions a holder typically asks when looking at their portfolio in aggregate:",
        "",
        "1. How much do I have, and where does it sit?",
        "2. What's my real asset mix once I look through every fund?",
        "3. What do I actually own?",
        "4. Where am I concentrated?",
        "5. Where do things sit, tax-wise?",
        "6. What's it costing me to hold this?",
        "7. Is anything in the data unusual?",
        "",
        "_(Plus — what changed since last refresh — when applicable.)_",
        "",
        "---",
        "",
    ])
    lines.extend(section_overview(positions, summary, io_dir))
    lines.extend(section_allocation(classified, io_dir,
                                     thresholds.get("single_sector", 0.25)))
    lines.extend(section_holdings(positions, lookup))
    lines.extend(section_concentration(positions, classified, io_dir, thresholds, config, lookup))
    lines.extend(section_tax_location(io_dir))
    lines.extend(section_fees(io_dir))
    lines.extend(section_anomalies(io_dir))
    next_num = 8
    if delta:
        lines.extend(section_delta(delta, next_num))
        next_num += 1
    lines.extend(section_appendix(io_dir))
    lines.extend(section_closing())
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Folder hygiene — keep the source folder clean, intermediates in .analysis/
# -----------------------------------------------------------------------------

# Anything matching these patterns is an intermediate artifact and belongs
# inside `.analysis/`, not at the root of the user's source folder.
LEGACY_INTERMEDIATE_NAMES = {
    "raw_positions.csv", "statements_meta.json", "extract_warnings.txt",
    "positions.csv", "positions_classified.csv",
    "consolidation_log.csv", "consolidation_summary.md",
    "classification_unknowns.md",
    "Allocation.csv", "Concentration.md", "TaxLocation.md",
    "Fees.csv", "Income.csv", "Anomalies.md",
    "_analyze_summary.json",
    "Commentary.md",
}
LEGACY_INTERMEDIATE_PREFIXES = ("chart_",)


def migrate_legacy_artifacts(work_folder: Path, io_dir: Path) -> int:
    """Move any old-layout intermediate files from work_folder root → .analysis/.

    Returns the number of files moved. Safe to run on every invocation —
    skips files that are already correctly placed.
    """
    moved = 0
    if not work_folder.is_dir():
        return 0
    for p in work_folder.iterdir():
        if not p.is_file():
            continue
        is_intermediate = (
            p.name in LEGACY_INTERMEDIATE_NAMES
            or any(p.name.startswith(pfx) for pfx in LEGACY_INTERMEDIATE_PREFIXES)
        )
        if not is_intermediate:
            continue
        target = io_dir / p.name
        # If a newer version is already in .analysis/, delete the stale root copy
        if target.is_file():
            p.unlink()
        else:
            shutil.move(str(p), str(target))
        moved += 1
    return moved


def open_file(path: Path) -> None:
    """Open the report in the user's default Markdown viewer. macOS only for now."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif platform.system() == "Linux":
            subprocess.run(["xdg-open", str(path)], check=False)
        elif platform.system() == "Windows":
            subprocess.run(["cmd", "/c", "start", "", str(path)], check=False, shell=False)
    except Exception:
        pass  # best-effort; don't crash the pipeline if this fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path,
                    help="The user's source folder (where statements live). "
                         "Intermediates live in <work_folder>/.analysis/; "
                         "deliverables are written to the work_folder root.")
    ap.add_argument("--config", type=Path, default=None,
                    help="investment_analysis_config.yaml (for thresholds + employer registry)")
    ap.add_argument("--no-open", action="store_true",
                    help="Don't auto-open the report when done.")
    args = ap.parse_args()

    # Resolve the IO subfolder
    io_dir = args.work_folder if args.work_folder.name == ".analysis" else args.work_folder / ".analysis"
    io_dir.mkdir(exist_ok=True)
    user_folder = io_dir.parent

    # One-time migration: move any old-layout files at the root into .analysis/
    migrated = migrate_legacy_artifacts(user_folder, io_dir)
    if migrated:
        print(f"Migrated {migrated} legacy intermediate file(s) into .analysis/")

    positions_path = io_dir / "positions.csv"
    classified_path = io_dir / "positions_classified.csv"
    if not classified_path.is_file():
        print(f"error: {classified_path} not found", file=sys.stderr)
        return 2
    if not positions_path.is_file():
        print(f"error: {positions_path} not found", file=sys.stderr)
        return 2

    positions = pd.read_csv(positions_path)
    classified = pd.read_csv(classified_path)

    summary_path = io_dir / "_analyze_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}

    # Config lives at the root of the user's folder (it's a deliverable —
    # users edit it manually to add overrides, set thresholds, etc.).
    config = {}
    resolved_config = auto_discover_config(args.work_folder, args.config)
    if resolved_config:
        config = load_yaml(resolved_config)
        if not args.config:
            print(f"  Using config: {resolved_config}")

    prior_path = find_prior_classified(io_dir)
    delta = None
    if prior_path:
        prior = pd.read_csv(prior_path)
        delta = compute_delta(classified, prior)

    # Deliverables → root of user folder
    ledger_path = user_folder / "Investment Positions.csv"
    report_path = user_folder / "Investment Analysis Report.md"
    write_positions_ledger(classified, ledger_path)
    report_path.write_text(build_report(positions, classified, summary, delta, io_dir, config))

    print("Report written.")
    print(f"  {report_path}")
    print(f"  {ledger_path}")
    print(f"  (drill-down material in {io_dir}/)")

    if not args.no_open:
        open_file(report_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
