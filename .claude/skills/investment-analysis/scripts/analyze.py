#!/usr/bin/env python3
"""
Phase 5 (analysis half): produce all the analysis CSVs and markdown reports.
This is the descriptive-only artifact set. No recommendations. Ever.

Outputs:
- Allocation.csv
- Concentration.md
- TaxLocation.md
- Fees.csv
- Income.csv
- Anomalies.md

Charts are produced by generate_charts.py. Commentary is produced by
generate_report.py.

Usage:
    python analyze.py <work_folder> [--config PATH] [--thresholds PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    if not path or not path.is_file():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


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


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return f"{x:.1%}"


# -----------------------------------------------------------------------------
# Allocation
# -----------------------------------------------------------------------------

def write_allocation(df: pd.DataFrame, out_path: Path) -> dict:
    """Write Allocation.csv with multiple views. Returns the by-sleeve summary
    for downstream callers."""
    total_gross = df["weighted_value_gross"].sum()
    total_net = df["weighted_value_net"].sum()

    rows: list[dict] = []

    # By asset class
    g = df.groupby("asset_class", as_index=False).agg(
        value_gross=("weighted_value_gross", "sum"),
        value_net=("weighted_value_net", "sum"),
    )
    for _, r in g.iterrows():
        rows.append({
            "view": "by_asset_class",
            "group": r["asset_class"],
            "value_gross": round(r["value_gross"], 2),
            "value_net": round(r["value_net"], 2),
            "pct_of_investable": round(r["value_gross"] / total_gross, 4) if total_gross else 0,
        })

    # By sleeve
    df = df.copy()
    df["sleeve"] = df["asset_class"].map(SLEEVE_MAP).fillna("unknown")
    g = df.groupby("sleeve", as_index=False).agg(
        value_gross=("weighted_value_gross", "sum"),
        value_net=("weighted_value_net", "sum"),
    )
    sleeve_totals = {}
    for _, r in g.iterrows():
        rows.append({
            "view": "by_sleeve",
            "group": r["sleeve"],
            "value_gross": round(r["value_gross"], 2),
            "value_net": round(r["value_net"], 2),
            "pct_of_investable": round(r["value_gross"] / total_gross, 4) if total_gross else 0,
        })
        sleeve_totals[r["sleeve"]] = r["value_gross"]

    # By account
    g = df.groupby("account", as_index=False).agg(
        value_gross=("weighted_value_gross", "sum"),
        value_net=("weighted_value_net", "sum"),
    )
    for _, r in g.iterrows():
        rows.append({
            "view": "by_account",
            "group": r["account"],
            "value_gross": round(r["value_gross"], 2),
            "value_net": round(r["value_net"], 2),
            "pct_of_investable": round(r["value_gross"] / total_gross, 4) if total_gross else 0,
        })

    # By owner
    g = df.groupby("owner", as_index=False).agg(
        value_gross=("weighted_value_gross", "sum"),
        value_net=("weighted_value_net", "sum"),
    )
    for _, r in g.iterrows():
        rows.append({
            "view": "by_owner",
            "group": r["owner"],
            "value_gross": round(r["value_gross"], 2),
            "value_net": round(r["value_net"], 2),
            "pct_of_investable": round(r["value_gross"] / total_gross, 4) if total_gross else 0,
        })

    pd.DataFrame(rows).to_csv(out_path, index=False)
    return {"sleeve_totals": sleeve_totals, "total_gross": total_gross, "total_net": total_net}


# -----------------------------------------------------------------------------
# Concentration
# -----------------------------------------------------------------------------

def write_concentration(df: pd.DataFrame, thresholds: dict, out_path: Path) -> None:
    total = df["weighted_value_gross"].sum()
    equity_total = df[df["asset_class"].isin(["us_equity", "intl_dev_equity", "intl_em_equity"])]["weighted_value_gross"].sum()
    ct = thresholds.get("concentration_thresholds", {})

    # Top 10 single-name (group by ticker + issuer)
    single_name = df.groupby(["ticker", "description"], as_index=False)["weighted_value_gross"].sum()
    single_name = single_name.sort_values("weighted_value_gross", ascending=False).head(10)
    single_name_threshold = ct.get("single_name", 0.05)

    # Sector concentration (direct + implied)
    sector_direct = defaultdict(float)
    for _, r in df.iterrows():
        if pd.notna(r.get("sector")) and r["sector"]:
            sector_direct[r["sector"]] += r["weighted_value_gross"]

    sector_implied = defaultdict(float)
    for _, r in df.iterrows():
        isw = r.get("implied_sector_weights")
        if pd.notna(isw) and isw:
            try:
                weights = json.loads(isw) if isinstance(isw, str) else isw
                for sec, w in weights.items():
                    sector_implied[sec] += r["weighted_value_gross"] * w
            except (json.JSONDecodeError, TypeError):
                continue

    all_sectors = sorted(set(list(sector_direct.keys()) + list(sector_implied.keys())))
    sector_threshold = ct.get("single_sector", 0.25)

    # Single-fund within sleeve
    df_local = df.copy()
    df_local["sleeve"] = df_local["asset_class"].map(SLEEVE_MAP).fillna("unknown")
    fund_in_sleeve_threshold = ct.get("single_fund_in_sleeve", 0.50)
    sleeve_fund_facts: list[tuple[str, str, float, float]] = []
    for sleeve, group in df_local.groupby("sleeve"):
        sleeve_total = group["weighted_value_gross"].sum()
        if sleeve_total <= 0:
            continue
        per_fund = group.groupby("ticker")["weighted_value_gross"].sum()
        top_fund = per_fund.idxmax()
        top_val = per_fund.max()
        sleeve_fund_facts.append((sleeve, top_fund, top_val, top_val / sleeve_total))

    # Single-issuer aggregation
    issuer_threshold = ct.get("single_issuer", 0.25)
    issuer_totals = defaultdict(float)
    for _, r in df.iterrows():
        issuer = r.get("issuer") or r.get("employer")
        if pd.notna(issuer) and issuer:
            issuer_totals[issuer] += r["weighted_value_gross"]

    # Geographic
    region_totals = defaultdict(float)
    for _, r in df.iterrows():
        ac = r.get("asset_class", "")
        if ac == "us_equity":
            region_totals["us"] += r["weighted_value_gross"]
        elif ac == "intl_dev_equity":
            region_totals["intl_developed"] += r["weighted_value_gross"]
        elif ac == "intl_em_equity":
            region_totals["emerging_markets"] += r["weighted_value_gross"]

    # ------ Write markdown ------
    lines = ["# Concentration Map", ""]
    lines.append(f"_All values descriptive. Thresholds from config flag facts, not problems._")
    lines.append("")
    lines.append(f"Total investable basis: {fmt_money(total)}")
    lines.append("")

    # Top single names
    lines.append("## Top 10 single-name exposures")
    lines.append("")
    lines.append(f"Threshold for flagging: {fmt_pct(single_name_threshold)} of investable.")
    lines.append("")
    lines.append("| Rank | Ticker | Description | Value | % of Investable | Above threshold |")
    lines.append("|---:|---|---|---:|---:|:---:|")
    for i, (_, r) in enumerate(single_name.iterrows(), start=1):
        pct = r["weighted_value_gross"] / total if total else 0
        flag = "✓" if pct > single_name_threshold else ""
        lines.append(f"| {i} | `{r['ticker']}` | {r['description']} | {fmt_money(r['weighted_value_gross'])} | {fmt_pct(pct)} | {flag} |")
    lines.append("")

    # Sectors
    lines.append("## Sector concentration (through-the-fund)")
    lines.append("")
    lines.append(f"Threshold: {fmt_pct(sector_threshold)} of equity. Equity total: {fmt_money(equity_total)}.")
    lines.append("")
    lines.append("| Sector | Direct $ | Implied $ | Total $ | % of equity | Above threshold |")
    lines.append("|---|---:|---:|---:|---:|:---:|")
    for sec in all_sectors:
        direct = sector_direct.get(sec, 0)
        implied = sector_implied.get(sec, 0)
        total_sec = direct + implied
        pct = total_sec / equity_total if equity_total else 0
        flag = "✓" if pct > sector_threshold else ""
        lines.append(f"| {sec} | {fmt_money(direct)} | {fmt_money(implied)} | {fmt_money(total_sec)} | {fmt_pct(pct)} | {flag} |")
    lines.append("")

    # Single-fund per sleeve
    lines.append("## Single-fund concentration (within sleeves)")
    lines.append("")
    lines.append(f"Threshold: {fmt_pct(fund_in_sleeve_threshold)} of any sleeve.")
    lines.append("")
    lines.append("| Sleeve | Largest fund | Value | % of sleeve | Above threshold |")
    lines.append("|---|---|---:|---:|:---:|")
    for sleeve, fund, val, pct in sleeve_fund_facts:
        flag = "✓" if pct > fund_in_sleeve_threshold else ""
        lines.append(f"| {sleeve} | `{fund}` | {fmt_money(val)} | {fmt_pct(pct)} | {flag} |")
    lines.append("")

    # Issuer
    lines.append("## Single-issuer / employer aggregation")
    lines.append("")
    lines.append(f"Threshold: {fmt_pct(issuer_threshold)} of investable.")
    lines.append("")
    if issuer_totals:
        lines.append("| Issuer | Total | % of investable | Above threshold |")
        lines.append("|---|---:|---:|:---:|")
        for issuer, val in sorted(issuer_totals.items(), key=lambda x: -x[1]):
            pct = val / total if total else 0
            flag = "✓" if pct > issuer_threshold else ""
            lines.append(f"| {issuer} | {fmt_money(val)} | {fmt_pct(pct)} | {flag} |")
    else:
        lines.append("_No issuer-tagged positions detected._")
    lines.append("")

    # Geographic
    lines.append("## Geographic concentration")
    lines.append("")
    lines.append("| Region | Value | % of equity |")
    lines.append("|---|---:|---:|")
    for region in ["us", "intl_developed", "emerging_markets"]:
        val = region_totals.get(region, 0)
        pct = val / equity_total if equity_total else 0
        lines.append(f"| {region} | {fmt_money(val)} | {fmt_pct(pct)} |")
    lines.append("")

    out_path.write_text("\n".join(lines))


# -----------------------------------------------------------------------------
# Tax-location audit
# -----------------------------------------------------------------------------

WRAPPER_GROUPS = {
    "taxable_brokerage": "taxable",
    "cash_savings": "taxable",
    "direct_holding": "taxable",
    "real_estate": "real_estate_wrapper",
    "qualified_401k": "qualified",
    "qualified_403b": "qualified",
    "qualified_457": "qualified",
    "qualified_pcra": "qualified",
    "traditional_ira": "qualified",
    "sep_ira": "qualified",
    "pension_db": "qualified",
    "pension_cb": "qualified",
    "pension_unknown": "qualified",
    "roth_401k": "roth",
    "roth_ira": "roth",
    "nqdc": "nqdc",
    "nqdc_pcra": "nqdc",
    "ltip": "nqdc",
    "rsu_award": "nqdc",
    "alt_concentrated": "nqdc",
    "espp": "taxable",
    "hsa": "hsa",
    "529": "529",
    "crypto": "taxable",
    "unknown": "unknown",
}

WRAPPER_LABELS = ["taxable", "qualified", "roth", "nqdc", "hsa", "529", "real_estate_wrapper", "unknown"]


def write_tax_location(df: pd.DataFrame, out_path: Path) -> None:
    df = df.copy()
    df["wrapper"] = df["account_type"].map(WRAPPER_GROUPS).fillna("unknown")
    matrix = df.pivot_table(
        index="asset_class",
        columns="wrapper",
        values="weighted_value_gross",
        aggfunc="sum",
        fill_value=0,
    )
    # Reorder columns
    for w in WRAPPER_LABELS:
        if w not in matrix.columns:
            matrix[w] = 0
    matrix = matrix[WRAPPER_LABELS]
    matrix["total"] = matrix.sum(axis=1)

    lines = ["# Tax-Location Audit", ""]
    lines.append(
        "_Descriptive only — surfaces where assets sit by wrapper type. "
        "Does not recommend where they should sit._"
    )
    lines.append("")

    header = "| Asset class | " + " | ".join(WRAPPER_LABELS) + " | Total |"
    sep = "|---|" + "|".join(["---:"] * (len(WRAPPER_LABELS) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    for ac, row in matrix.iterrows():
        cells = [fmt_money(row[w]) for w in WRAPPER_LABELS]
        lines.append(f"| {ac} | " + " | ".join(cells) + f" | {fmt_money(row['total'])} |")

    # Append descriptive facts
    lines.extend(["", "## Observations", ""])
    growth_in_nqdc = df[(df["account_type"].isin(["nqdc", "nqdc_pcra", "ltip", "rsu_award"]))
                       & (df["asset_class"].isin(["us_equity", "intl_dev_equity", "intl_em_equity"]))]["weighted_value_gross"].sum()
    if growth_in_nqdc > 0:
        lines.append(f"- {fmt_money(growth_in_nqdc)} of equity is held in NQDC/restricted wrappers.")

    muni_in_taxable = df[(df["account_type"] == "taxable_brokerage")
                        & (df["distribution_character"] == "muni")]["weighted_value_gross"].sum()
    if muni_in_taxable > 0:
        lines.append(f"- {fmt_money(muni_in_taxable)} of municipal-bond exposure is held in taxable accounts.")

    bonds_in_taxable = df[(df["account_type"] == "taxable_brokerage")
                         & (df["asset_class"].isin(["us_bonds", "intl_bonds"]))
                         & (df["distribution_character"] != "muni")]["weighted_value_gross"].sum()
    if bonds_in_taxable > 0:
        lines.append(f"- {fmt_money(bonds_in_taxable)} of taxable-coupon bonds is held in taxable accounts.")

    out_path.write_text("\n".join(lines))


# -----------------------------------------------------------------------------
# Fees
# -----------------------------------------------------------------------------

def write_fees(df: pd.DataFrame, thresholds: dict, out_path: Path) -> None:
    notable_er = thresholds.get("anomalies", {}).get("notable_er_pct", 0.0075)
    grouped = df.groupby(["ticker", "description"], as_index=False).agg(
        holding_value=("weighted_value_gross", "sum"),
        expense_ratio=("expense_ratio", "first"),
        asset_class=("asset_class", "first"),
    )
    grouped = grouped[grouped["expense_ratio"].notna()].copy()
    grouped["annual_fee_dollars"] = grouped["holding_value"] * grouped["expense_ratio"]
    grouped["notable"] = (grouped["expense_ratio"] > notable_er) | (grouped["holding_value"] > 100000)
    grouped = grouped.sort_values("annual_fee_dollars", ascending=False)
    grouped.to_csv(out_path, index=False)


# -----------------------------------------------------------------------------
# Income
# -----------------------------------------------------------------------------

def write_income(df: pd.DataFrame, out_path: Path) -> None:
    agg_args: dict[str, tuple[str, str]] = {"holding_value": ("weighted_value_gross", "sum")}
    if "est_annual_income" in df.columns:
        agg_args["est_annual_income"] = ("est_annual_income", "sum")
    if "est_yield_pct" in df.columns:
        agg_args["est_yield"] = ("est_yield_pct", "first")
    income = df.groupby(
        ["ticker", "description", "distribution_character", "account_type"],
        as_index=False,
    ).agg(**agg_args)
    income.to_csv(out_path, index=False)


# -----------------------------------------------------------------------------
# Anomalies
# -----------------------------------------------------------------------------

def write_anomalies(df: pd.DataFrame, thresholds: dict, out_path: Path) -> None:
    ct = thresholds.get("concentration_thresholds", {})
    cash_acct = ct.get("idle_cash_in_account", 0.05)
    cash_total = ct.get("idle_cash_total", 0.02)
    dust_threshold = ct.get("dust_position_usd", 1000)
    total = df["weighted_value_gross"].sum()

    lines = ["# Anomalies", ""]
    lines.append("_Surface of observations — described as facts, not problems._")
    lines.append("")

    # Idle cash by account
    lines.append("## Idle cash")
    lines.append("")
    cash_df = df[df["asset_class"] == "cash"]
    acct_totals = df.groupby("account")["weighted_value_gross"].sum()
    cash_by_acct = cash_df.groupby("account")["weighted_value_gross"].sum()
    flagged = []
    for acct, cash_val in cash_by_acct.items():
        acct_total = acct_totals.get(acct, 0)
        if acct_total <= 0:
            continue
        pct = cash_val / acct_total
        if pct > cash_acct:
            flagged.append((acct, cash_val, acct_total, pct))
    if flagged:
        lines.append("| Account | Cash | Account total | % of account |")
        lines.append("|---|---:|---:|---:|")
        for acct, c, t, p in flagged:
            lines.append(f"| {acct} | {fmt_money(c)} | {fmt_money(t)} | {fmt_pct(p)} |")
    else:
        lines.append("_No accounts above the per-account idle-cash threshold._")
    lines.append("")

    total_cash = cash_df["weighted_value_gross"].sum()
    if total and (total_cash / total) > cash_total:
        lines.append(f"Total cash in investment accounts: {fmt_money(total_cash)} ({fmt_pct(total_cash/total)} of investable — above the {fmt_pct(cash_total)} threshold).")
    lines.append("")

    # Dust positions
    lines.append("## Dust positions")
    lines.append("")
    dust = df[(df["weighted_value_gross"] < dust_threshold) & (df["asset_class"] != "cash")]
    dust = dust.groupby(["ticker", "description"], as_index=False)["weighted_value_gross"].sum()
    dust = dust[dust["weighted_value_gross"] < dust_threshold]
    if len(dust) > 0:
        lines.append(f"{len(dust)} positions below ${dust_threshold:,} — total {fmt_money(dust['weighted_value_gross'].sum())}.")
        lines.append("")
        lines.append("| Ticker | Description | Value |")
        lines.append("|---|---|---:|")
        for _, r in dust.head(30).iterrows():
            lines.append(f"| `{r['ticker']}` | {r['description']} | {fmt_money(r['weighted_value_gross'])} |")
    else:
        lines.append("_No dust positions detected._")
    lines.append("")

    # Missing cost basis (material)
    cb_threshold = thresholds.get("anomalies", {}).get("missing_cost_basis_usd", 10000)
    missing_cb = df[(df["cost_basis"].isna()) & (df["weighted_value_gross"] > cb_threshold)
                    & (df["asset_class"] != "cash")
                    & (df["asset_class"] != "real_estate")]
    lines.append("## Missing cost basis (positions above threshold)")
    lines.append("")
    if len(missing_cb) > 0:
        lines.append(f"{len(missing_cb)} positions above ${cb_threshold:,} missing cost basis.")
    else:
        lines.append("_All material positions have cost basis._")
    lines.append("")

    # Substantially overlapping funds (potential TLH pairs)
    lines.append("## Potential TLH pairs")
    lines.append("")
    overlap_pairs = []
    by_class = df.groupby("asset_class")
    for ac, group in by_class:
        if ac in {"cash", "real_estate", "alt_concentrated", "crypto", "unknown"}:
            continue
        funds = group[group["index"].notna()].groupby(["ticker", "index"], as_index=False)["weighted_value_gross"].sum()
        if len(funds) < 2:
            continue
        funds = funds.sort_values("weighted_value_gross", ascending=False).head(5)
        funds_list = list(funds.itertuples(index=False))
        for i, a in enumerate(funds_list):
            for b in funds_list[i+1:]:
                if a.index != b.index:        # different indices → TLH-eligible
                    overlap_pairs.append((ac, a.ticker, a.index, b.ticker, b.index))
    if overlap_pairs:
        lines.append("Held simultaneously with different tracked indices (TLH-eligible swap partners):")
        lines.append("")
        lines.append("| Asset class | Fund A | Index A | Fund B | Index B |")
        lines.append("|---|---|---|---|---|")
        for ac, a, ai, b, bi in overlap_pairs[:15]:
            lines.append(f"| {ac} | `{a}` | {ai} | `{b}` | {bi} |")
    else:
        lines.append("_No same-asset-class fund pairs detected._")
    lines.append("")

    out_path.write_text("\n".join(lines))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--thresholds", type=Path, default=None,
                    help="Defaults to <skill_dir>/references/data/thresholds.yaml")
    args = ap.parse_args()

    # Intermediates live in .analysis/ subfolder
    io_dir = args.work_folder if args.work_folder.name == ".analysis" else args.work_folder / ".analysis"
    io_dir.mkdir(exist_ok=True)

    classified_path = io_dir / "positions_classified.csv"
    if not classified_path.is_file():
        print(f"error: {classified_path} not found", file=sys.stderr)
        return 2

    df = pd.read_csv(classified_path)

    thresholds_path = args.thresholds or (Path(__file__).parent.parent / "references" / "data" / "thresholds.yaml")
    thresholds = load_yaml(thresholds_path)
    config = load_yaml(args.config) if args.config else {}

    # Merge user-overridden thresholds
    user_ct = config.get("concentration_thresholds")
    if user_ct:
        thresholds.setdefault("concentration_thresholds", {}).update(user_ct)

    summary = write_allocation(df, io_dir / "Allocation.csv")
    write_concentration(df, thresholds, io_dir / "Concentration.md")
    write_tax_location(df, io_dir / "TaxLocation.md")
    write_fees(df, thresholds, io_dir / "Fees.csv")
    write_income(df, io_dir / "Income.csv")
    write_anomalies(df, thresholds, io_dir / "Anomalies.md")

    # Stash the summary for generate_report to pick up
    (io_dir / "_analyze_summary.json").write_text(json.dumps(summary, default=str, indent=2))

    print("Analysis complete.")
    print(f"  Total investable (gross): {fmt_money(summary['total_gross'])}")
    print(f"  Total investable (net):   {fmt_money(summary['total_net'])}")
    print("Output:")
    for f in ["Allocation.csv", "Concentration.md", "TaxLocation.md", "Fees.csv", "Income.csv", "Anomalies.md"]:
        print(f"  {io_dir / f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
