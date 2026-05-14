#!/usr/bin/env python3
"""
Phase 5 (report half): write the position ledger + commentary, and orchestrate
the full Phase 5 if no preceding analyze run is found.

Reads:
- positions_classified.csv
- Allocation.csv, Concentration.md, TaxLocation.md, Fees.csv, Income.csv, Anomalies.md
  (from analyze.py)
- _analyze_summary.json
- (optionally) prior positions_classified.csv for refresh delta

Writes:
- Investment Positions.csv (final user-facing ledger)
- Commentary.md (descriptive narrative — STRICTLY no recommendations)

Usage:
    python generate_report.py <work_folder>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd


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
# Position ledger — pretty user-facing CSV
# -----------------------------------------------------------------------------

def write_positions_ledger(df: pd.DataFrame, out_path: Path) -> None:
    cols = [
        "account", "account_type", "owner", "employer", "ticker", "description",
        "section", "asset_class", "asset_class_weight",
        "weighted_value_gross", "weighted_value_net",
        "cost_basis", "unrealized_gain",
        "vested", "vest_date",
        "expense_ratio", "distribution_character", "distribution_at_payout",
        "sector", "region", "issuer", "sub_asset",
        "source_file",
    ]
    cols = [c for c in cols if c in df.columns]
    df[cols].to_csv(out_path, index=False)


# -----------------------------------------------------------------------------
# Refresh delta
# -----------------------------------------------------------------------------

def find_prior_classified(folder: Path) -> Path | None:
    """Look for a prior classified file in archive/ or as a timestamped backup."""
    candidates = list(folder.glob("positions_classified.*.csv"))
    if not candidates:
        return None
    return sorted(candidates)[-1]


def compute_delta(current: pd.DataFrame, prior: pd.DataFrame) -> dict:
    cur_by_holding = current.groupby("ticker")["weighted_value_gross"].sum()
    prior_by_holding = prior.groupby("ticker")["weighted_value_gross"].sum()
    new_tickers = set(cur_by_holding.index) - set(prior_by_holding.index)
    removed_tickers = set(prior_by_holding.index) - set(cur_by_holding.index)
    common = set(cur_by_holding.index) & set(prior_by_holding.index)

    changes = []
    for t in common:
        delta = cur_by_holding[t] - prior_by_holding[t]
        if abs(delta) > 100:
            changes.append({"ticker": t, "delta": delta,
                            "from": prior_by_holding[t], "to": cur_by_holding[t]})
    changes.sort(key=lambda x: -abs(x["delta"]))

    cur_total = current["weighted_value_gross"].sum()
    prior_total = prior["weighted_value_gross"].sum()

    return {
        "total_delta": cur_total - prior_total,
        "total_pct_delta": (cur_total - prior_total) / prior_total if prior_total else 0,
        "new_tickers": sorted(new_tickers),
        "removed_tickers": sorted(removed_tickers),
        "top_changes": changes[:20],
    }


# -----------------------------------------------------------------------------
# Commentary — descriptive only
# -----------------------------------------------------------------------------

def write_commentary(df: pd.DataFrame, summary: dict, delta: dict | None,
                      anomalies_md: str, out_path: Path) -> None:
    total_gross = summary.get("total_gross", df["weighted_value_gross"].sum())
    total_net = summary.get("total_net", df["weighted_value_net"].sum())
    sleeve_totals = summary.get("sleeve_totals", {})

    lines: list[str] = []
    lines.append("# Commentary")
    lines.append("")
    lines.append(
        "_Descriptive — describes the current state of the portfolio. "
        "Does not recommend changes, target allocations, or trades. For prescriptive "
        "guidance, this analysis would feed a financial-planning + portfolio-optimization "
        "skill that combines it with goals, spending, and horizon._"
    )
    lines.append("")

    # ---- Headline ----
    lines.append("## Headline")
    lines.append("")
    lines.append(f"Total investable (vested, gross): **{fmt_money(total_gross)}**")
    lines.append(f"Total investable (vested, net of tax haircuts): **{fmt_money(total_net)}**")
    lines.append("")

    # Vested vs unvested split
    if "vested" in df.columns:
        unvested = df[df["vested"] == False]["weighted_value_gross"].sum()
        if unvested > 0:
            lines.append(f"Unvested awards (additional economic exposure): **{fmt_money(unvested)}**")
            lines.append(f"Total including unvested: **{fmt_money(total_gross + unvested)}**")
            lines.append("")

    lines.append("**Sleeve breakdown:**")
    lines.append("")
    for sleeve, val in sorted(sleeve_totals.items(), key=lambda x: -x[1]):
        pct = val / total_gross if total_gross else 0
        lines.append(f"- {sleeve}: {fmt_money(val)} ({fmt_pct(pct)})")
    lines.append("")

    # ---- Structural observations ----
    lines.append("## Structurally notable")
    lines.append("")

    # Largest single name
    by_holding = df.groupby(["ticker", "description"], as_index=False)["weighted_value_gross"].sum()
    by_holding = by_holding.sort_values("weighted_value_gross", ascending=False)
    if len(by_holding) > 0:
        top = by_holding.iloc[0]
        pct = top["weighted_value_gross"] / total_gross if total_gross else 0
        lines.append(f"- Largest single position: `{top['ticker']}` ({top['description']}) at {fmt_money(top['weighted_value_gross'])} ({fmt_pct(pct)} of investable).")

    # Largest issuer
    issuer_totals = defaultdict(float)
    for _, r in df.iterrows():
        issuer = r.get("issuer") or r.get("employer")
        if pd.notna(issuer) and issuer:
            issuer_totals[issuer] += r["weighted_value_gross"]
    if issuer_totals:
        top_issuer = max(issuer_totals.items(), key=lambda x: x[1])
        pct = top_issuer[1] / total_gross if total_gross else 0
        lines.append(f"- Largest single-issuer aggregate exposure: **{top_issuer[0]}** at {fmt_money(top_issuer[1])} ({fmt_pct(pct)} of investable, summing direct + wrapper + comp).")

    # International weight
    intl = df[df["asset_class"].isin(["intl_dev_equity", "intl_em_equity"])]["weighted_value_gross"].sum()
    equity_total = df[df["asset_class"].isin(["us_equity", "intl_dev_equity", "intl_em_equity"])]["weighted_value_gross"].sum()
    if equity_total > 0:
        intl_pct = intl / equity_total
        lines.append(f"- International equity: {fmt_money(intl)}, which is {fmt_pct(intl_pct)} of equity.")

    # Bond manager concentration
    bonds = df[df["asset_class"].isin(["us_bonds", "intl_bonds"])]
    if len(bonds) > 0:
        bond_total = bonds["weighted_value_gross"].sum()
        bond_by_fund = bonds.groupby("ticker")["weighted_value_gross"].sum().sort_values(ascending=False)
        if len(bond_by_fund) > 0:
            top_bond = bond_by_fund.index[0]
            pct = bond_by_fund.iloc[0] / bond_total
            lines.append(f"- Largest single fund in fixed income: `{top_bond}` at {fmt_pct(pct)} of bonds.")

    # Wrappers
    lines.append("")
    lines.append("## What's where (wrapper-wise)")
    lines.append("")
    wrapper_totals = df.groupby("account_type")["weighted_value_gross"].sum().sort_values(ascending=False)
    for atype, val in wrapper_totals.items():
        pct = val / total_gross if total_gross else 0
        if pct > 0.01:
            lines.append(f"- `{atype}`: {fmt_money(val)} ({fmt_pct(pct)})")

    # ---- Cash / idle ----
    cash_val = df[df["asset_class"] == "cash"]["weighted_value_gross"].sum()
    if cash_val > 0:
        lines.append("")
        lines.append(f"## Cash in investment accounts")
        lines.append("")
        cash_pct = cash_val / total_gross if total_gross else 0
        lines.append(f"- Total cash inside investment accounts: {fmt_money(cash_val)} ({fmt_pct(cash_pct)}).")

    # ---- Delta vs prior ----
    if delta:
        lines.append("")
        lines.append("## Changes since last refresh")
        lines.append("")
        lines.append(f"- Total investable: {fmt_money(delta['total_delta'])} change ({fmt_pct(delta['total_pct_delta'])}).")
        if delta["new_tickers"]:
            lines.append(f"- New positions: {', '.join(f'`{t}`' for t in delta['new_tickers'][:10])}")
        if delta["removed_tickers"]:
            lines.append(f"- Removed positions: {', '.join(f'`{t}`' for t in delta['removed_tickers'][:10])}")
        if delta["top_changes"]:
            lines.append("")
            lines.append("Top dollar changes per holding:")
            for c in delta["top_changes"][:8]:
                lines.append(f"  - `{c['ticker']}`: {fmt_money(c['from'])} → {fmt_money(c['to'])} ({'+' if c['delta'] >= 0 else ''}{fmt_money(c['delta'])})")

    # ---- Data caveats ----
    lines.append("")
    lines.append("## Data caveats")
    lines.append("")
    unknown_val = df[df["asset_class"] == "unknown"]["weighted_value_gross"].sum()
    if unknown_val > 0:
        lines.append(f"- {fmt_money(unknown_val)} of holdings classified as `unknown` — needs registry update.")
    haircut = df["market_value_gross"].sum() - df["market_value_net"].sum()
    if haircut > 1000:
        lines.append(f"- {fmt_money(haircut)} of tax haircut applied to deferred-comp / restricted positions.")
    re_positions = df[df["asset_class"] == "real_estate"]
    if len(re_positions) > 0:
        methods = re_positions["section"].dropna().unique()
        lines.append(f"- Real estate carrying methodology in use: see Anomalies.md and consolidation_summary.md.")
    lines.append("")

    # ---- Closing offer (NOT a recommendation) ----
    lines.append("## Where to drill")
    lines.append("")
    lines.append(
        "Companion files in this folder:\n"
        "- `Investment Positions.csv` — flat ledger\n"
        "- `Allocation.csv` — through-the-fund breakdown\n"
        "- `Concentration.md` — top exposures vs thresholds\n"
        "- `TaxLocation.md` — wrapper × asset-class matrix\n"
        "- `Fees.csv` — fee load\n"
        "- `Income.csv` — income by character\n"
        "- `Anomalies.md` — idle cash, duplicates, dust, follow-ups\n"
        "- 6 PNG charts + 1 optional Sankey HTML\n"
    )
    lines.append("")
    lines.append(
        "For recommendations — what to actually *do* with this — that's a separate "
        "skill that takes this analysis as input alongside spending data, goals, "
        "and retirement horizon. That layer doesn't exist yet."
    )

    out_path.write_text("\n".join(lines))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    args = ap.parse_args()

    classified_path = args.work_folder / "positions_classified.csv"
    if not classified_path.is_file():
        print(f"error: {classified_path} not found", file=sys.stderr)
        return 2

    df = pd.read_csv(classified_path)

    # Load analyze summary
    summary_path = args.work_folder / "_analyze_summary.json"
    summary = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text())

    # Optional refresh delta
    prior_path = find_prior_classified(args.work_folder)
    delta = None
    if prior_path:
        prior = pd.read_csv(prior_path)
        delta = compute_delta(df, prior)

    # Load anomalies for inclusion in commentary
    anomalies_md = (args.work_folder / "Anomalies.md").read_text() if (args.work_folder / "Anomalies.md").is_file() else ""

    # Outputs
    write_positions_ledger(df, args.work_folder / "Investment Positions.csv")
    write_commentary(df, summary, delta, anomalies_md, args.work_folder / "Commentary.md")

    print("Report written.")
    print(f"  {args.work_folder / 'Investment Positions.csv'}")
    print(f"  {args.work_folder / 'Commentary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
