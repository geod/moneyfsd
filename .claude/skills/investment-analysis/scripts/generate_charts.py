#!/usr/bin/env python3
"""
Phase 5 (charts half): generate the chart pack.

Reads:
- positions_classified.csv (output of classify_funds.py)
- _analyze_summary.json (sleeve totals from analyze.py)

Writes 7 charts:
- chart_allocation_pie.png
- chart_asset_class_bars.png
- chart_concentration_heat.png
- chart_tax_location_matrix.png
- chart_fees_bar.png
- chart_income_breakdown.png
- chart_sankey.html  (optional — requires plotly)

Aesthetic: cream background, muted palette, Georgia serif titles —
visually rhymes with the `expenses` skill charts.

Usage:
    python generate_charts.py <work_folder>
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

from _config_discover import auto_discover_config


# -----------------------------------------------------------------------------
# Aesthetic
# -----------------------------------------------------------------------------

CREAM = "#FAF7F2"
MUTED_RED = "#A04040"
PALETTE = {
    "us_equity":         "#1f4e79",
    "intl_dev_equity":   "#2e75b6",
    "intl_em_equity":    "#5b9bd5",
    "us_bonds":          "#548235",
    "intl_bonds":        "#70ad47",
    "cash":              "#a6a6a6",
    "real_estate":       "#bf8f00",
    "alt_concentrated":  "#c55a11",
    "crypto":            "#7030a0",
    "unknown":           "#888888",
}

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

SLEEVE_COLOR = {
    "equity": "#1f4e79",
    "fixed_income": "#548235",
    "cash": "#a6a6a6",
    "real_estate": "#bf8f00",
    "alternatives": "#c55a11",
    "unknown": "#888888",
}


def setup_axes(ax, title: str, subtitle: str = "") -> None:
    ax.set_facecolor(CREAM)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#888888")
    ax.spines["bottom"].set_color("#888888")
    ax.grid(axis="y", color="#dddddd", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_title(title, fontfamily="Georgia", fontsize=14, fontweight="bold", pad=12)
    if subtitle:
        ax.text(0.5, 1.02, subtitle, transform=ax.transAxes, ha="center", fontsize=10, color="#444444")


def setup_fig(figsize=(10, 7)):
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(CREAM)
    return fig, ax


# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------

def chart_allocation_pie(df: pd.DataFrame, out_path: Path) -> None:
    df = df.copy()
    df["sleeve"] = df["asset_class"].map(SLEEVE_MAP).fillna("unknown")
    totals = df.groupby("sleeve")["weighted_value_gross"].sum().sort_values(ascending=False)
    fig, ax = setup_fig(figsize=(10, 8))
    colors = [SLEEVE_COLOR.get(s, "#888") for s in totals.index]
    wedges, _ = ax.pie(
        totals.values, colors=colors, startangle=90, counterclock=False,
        wedgeprops=dict(linewidth=2, edgecolor="white"),
    )
    total = totals.sum()
    for i, w in enumerate(wedges):
        ang = (w.theta2 + w.theta1) / 2
        x = math.cos(math.radians(ang))
        y = math.sin(math.radians(ang))
        ha = "left" if x >= 0 else "right"
        ax.annotate(
            f"{totals.index[i]}\n{totals.values[i]/total:.1%}",
            xy=(x*0.95, y*0.95),
            xytext=(1.3*x, 1.15*y),
            ha=ha, va="center", fontsize=10,
            arrowprops=dict(arrowstyle="-", color="#888", linewidth=0.8),
        )
    ax.set_title("Asset Category Allocation", fontfamily="Georgia", fontsize=14, fontweight="bold", pad=20)
    ax.text(0, -1.3, f"Total investable: ${total:,.0f}", ha="center", fontsize=10, color="#444")
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


def chart_account_pie(df: pd.DataFrame, out_path: Path) -> None:
    """Pie chart of $ by account. Color reflects the account's dominant sleeve
    for visual consistency with the sleeve pie."""
    df = df.copy()
    df["sleeve"] = df["asset_class"].map(SLEEVE_MAP).fillna("unknown")
    by_acct = df.groupby("account")["weighted_value_gross"].sum().sort_values(ascending=False)
    # Pick a representative sleeve per account (the largest one) for coloring
    acct_sleeve = (df.groupby(["account", "sleeve"])["weighted_value_gross"].sum()
                       .reset_index()
                       .sort_values("weighted_value_gross", ascending=False)
                       .drop_duplicates("account")
                       .set_index("account")["sleeve"]
                       .to_dict())
    fig, ax = setup_fig(figsize=(10, 8))
    colors = [SLEEVE_COLOR.get(acct_sleeve.get(a, "unknown"), "#888") for a in by_acct.index]
    wedges, _ = ax.pie(
        by_acct.values, colors=colors, startangle=90, counterclock=False,
        wedgeprops=dict(linewidth=2, edgecolor="white"),
    )
    total = by_acct.sum()
    for i, w in enumerate(wedges):
        ang = (w.theta2 + w.theta1) / 2
        x = math.cos(math.radians(ang))
        y = math.sin(math.radians(ang))
        ha = "left" if x >= 0 else "right"
        ax.annotate(
            f"{by_acct.index[i]}\n${by_acct.values[i]:,.0f} ({by_acct.values[i]/total:.0%})",
            xy=(x*0.95, y*0.95),
            xytext=(1.3*x, 1.15*y),
            ha=ha, va="center", fontsize=10,
            arrowprops=dict(arrowstyle="-", color="#888", linewidth=0.8),
        )
    ax.set_title("By Account", fontfamily="Georgia", fontsize=14,
                  fontweight="bold", pad=20)
    ax.text(0, -1.3, f"Color = dominant asset category", ha="center",
            fontsize=9, color="#666", style="italic")
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


def chart_asset_class_bars(df: pd.DataFrame, out_path: Path) -> None:
    totals = df.groupby("asset_class")["weighted_value_gross"].sum().sort_values(ascending=True)
    fig, ax = setup_fig(figsize=(10, 6))
    colors = [PALETTE.get(ac, "#888") for ac in totals.index]
    ax.barh(totals.index, totals.values, color=colors)
    setup_axes(ax, "Asset Class Breakdown", "")
    ax.set_xlabel("$ value")
    for i, v in enumerate(totals.values):
        ax.text(v, i, f" ${v:,.0f}", va="center", fontsize=9)
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


def chart_concentration_heat(df: pd.DataFrame, out_path: Path) -> None:
    by_holding = df.groupby(["ticker", "description"], as_index=False)["weighted_value_gross"].sum()
    by_holding = by_holding.sort_values("weighted_value_gross", ascending=False).head(15)
    total = df["weighted_value_gross"].sum()
    by_holding["pct"] = by_holding["weighted_value_gross"] / total

    fig, ax = setup_fig(figsize=(11, 7))
    norm = mpl.colors.Normalize(vmin=0, vmax=max(by_holding["pct"].max(), 0.10))
    cmap = mpl.cm.YlOrRd
    colors = [cmap(norm(p)) for p in by_holding["pct"]]
    labels = [f"{t} — {d[:40]}" for t, d in zip(by_holding["ticker"], by_holding["description"])]
    ax.barh(labels[::-1], by_holding["pct"].values[::-1] * 100, color=colors[::-1])
    ax.axvline(5, color=MUTED_RED, linestyle="--", linewidth=1, label="5% single-name threshold")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    setup_axes(ax, "Top 15 Single-Name Exposures", "")
    ax.set_xlabel("% of investable")
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


def chart_fees_bar(df: pd.DataFrame, out_path: Path) -> None:
    df = df.copy()
    df["sleeve"] = df["asset_class"].map(SLEEVE_MAP).fillna("unknown")
    df = df[df["expense_ratio"].notna()]
    df["annual_fee"] = df["weighted_value_gross"] * df["expense_ratio"]
    by_sleeve = df.groupby("sleeve")["annual_fee"].sum().sort_values(ascending=True)

    fig, ax = setup_fig(figsize=(10, 5))
    colors = [SLEEVE_COLOR.get(s, "#888") for s in by_sleeve.index]
    ax.barh(by_sleeve.index, by_sleeve.values, color=colors)
    setup_axes(ax, "Annual Fee Load by Sleeve", "")
    ax.set_xlabel("$ per year")
    for i, v in enumerate(by_sleeve.values):
        ax.text(v, i, f" ${v:,.0f}", va="center", fontsize=9)
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


def chart_income_breakdown(df: pd.DataFrame, out_path: Path) -> None:
    df = df.copy()
    if "est_annual_income" not in df.columns:
        df["est_annual_income"] = 0.0
    if "est_yield_pct" not in df.columns:
        df["est_yield_pct"] = 0.0
    df["est_income"] = df["est_annual_income"].fillna(
        df["weighted_value_gross"] * df["est_yield_pct"].fillna(0)
    )
    by_char = df.groupby("distribution_character")["est_income"].sum().sort_values(ascending=False)
    by_char = by_char[by_char > 0]

    fig, ax = setup_fig(figsize=(10, 5))
    colors = ["#1f4e79", "#548235", "#70ad47", "#bf8f00", "#a6a6a6", "#888"][:len(by_char)]
    ax.bar(by_char.index, by_char.values, color=colors)
    setup_axes(ax, "Estimated Annual Income by Distribution Character", "")
    ax.set_ylabel("$ per year")
    for i, v in enumerate(by_char.values):
        ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=9)
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


def chart_sankey_html(df: pd.DataFrame, out_path: Path) -> bool:
    """Optional Sankey via plotly. Returns True if rendered, False if skipped."""
    try:
        import plotly.graph_objects as go  # type: ignore
    except ImportError:
        return False

    # Build links: owner → wrapper → asset_class
    df = df.copy()
    df["wrapper"] = df["account_type"]
    owner_nodes = list(df["owner"].unique())
    wrapper_nodes = list(df["wrapper"].unique())
    class_nodes = list(df["asset_class"].unique())
    all_nodes = owner_nodes + wrapper_nodes + class_nodes
    node_idx = {n: i for i, n in enumerate(all_nodes)}

    links_source, links_target, links_value = [], [], []
    # Owner → wrapper
    g1 = df.groupby(["owner", "wrapper"])["weighted_value_gross"].sum().reset_index()
    for _, r in g1.iterrows():
        links_source.append(node_idx[r["owner"]])
        links_target.append(node_idx[r["wrapper"]])
        links_value.append(max(r["weighted_value_gross"], 1))
    # Wrapper → asset class
    g2 = df.groupby(["wrapper", "asset_class"])["weighted_value_gross"].sum().reset_index()
    for _, r in g2.iterrows():
        links_source.append(node_idx[r["wrapper"]])
        links_target.append(node_idx[r["asset_class"]])
        links_value.append(max(r["weighted_value_gross"], 1))

    fig = go.Figure(data=[go.Sankey(
        node=dict(label=all_nodes, pad=15, thickness=15),
        link=dict(source=links_source, target=links_target, value=links_value),
    )])
    fig.update_layout(
        title_text="Owner → Wrapper → Asset Class",
        font_family="Georgia",
        paper_bgcolor=CREAM,
        height=700,
    )
    fig.write_html(str(out_path))
    return True


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    # `--config` is accepted (and auto-discovered) for CLI uniformity with
    # the other pipeline scripts. Charts don't currently consume any config
    # values, but pipeline wrappers / future palette overrides may want to
    # pass it through without erroring.
    ap.add_argument("--config", type=Path, default=None,
                    help="investment_analysis_config.yaml (accepted for CLI uniformity)")
    args = ap.parse_args()

    resolved_config = auto_discover_config(args.work_folder, args.config)
    if resolved_config and not args.config:
        print(f"  Using config: {resolved_config}")

    # Intermediates and chart outputs live in .analysis/ subfolder
    io_dir = args.work_folder if args.work_folder.name == ".analysis" else args.work_folder / ".analysis"
    io_dir.mkdir(exist_ok=True)

    classified_path = io_dir / "positions_classified.csv"
    if not classified_path.is_file():
        print(f"error: {classified_path} not found", file=sys.stderr)
        return 2

    df = pd.read_csv(classified_path)

    out_dir = io_dir
    chart_allocation_pie(df, out_dir / "chart_allocation_pie.png")
    chart_account_pie(df, out_dir / "chart_account_pie.png")
    chart_asset_class_bars(df, out_dir / "chart_asset_class_bars.png")
    chart_concentration_heat(df, out_dir / "chart_concentration_heat.png")
    # tax-location chart uses inline mapping to avoid cross-script imports
    _chart_tax_location_inline(df, out_dir / "chart_tax_location_matrix.png")
    chart_fees_bar(df, out_dir / "chart_fees_bar.png")
    chart_income_breakdown(df, out_dir / "chart_income_breakdown.png")

    sankey_rendered = chart_sankey_html(df, out_dir / "chart_sankey.html")
    if not sankey_rendered:
        print("  (plotly not installed — Sankey skipped; install plotly for chart_sankey.html)")

    print("Charts written:")
    for f in sorted(out_dir.glob("chart_*.png")):
        print(f"  {f}")
    if sankey_rendered:
        print(f"  {out_dir / 'chart_sankey.html'}")
    return 0


def _chart_tax_location_inline(df: pd.DataFrame, out_path: Path) -> None:
    """Inline tax-location matrix chart (avoids cross-script import)."""
    wrapper_groups = {
        "taxable_brokerage": "taxable", "cash_savings": "taxable",
        "direct_holding": "taxable", "espp": "taxable", "crypto": "taxable",
        "real_estate": "real_estate_wrapper",
        "qualified_401k": "qualified", "qualified_403b": "qualified",
        "qualified_457": "qualified", "qualified_pcra": "qualified",
        "traditional_ira": "qualified", "sep_ira": "qualified",
        "pension_db": "qualified", "pension_cb": "qualified", "pension_unknown": "qualified",
        "roth_401k": "roth", "roth_ira": "roth",
        "nqdc": "nqdc", "nqdc_pcra": "nqdc", "ltip": "nqdc", "rsu_award": "nqdc",
        "alt_concentrated": "nqdc",
        "hsa": "hsa", "529": "529",
        "unknown": "unknown",
    }
    wrapper_labels = ["taxable", "qualified", "roth", "nqdc", "hsa", "529", "real_estate_wrapper", "unknown"]

    df = df.copy()
    df["wrapper"] = df["account_type"].map(wrapper_groups).fillna("unknown")
    matrix = df.pivot_table(
        index="asset_class", columns="wrapper", values="weighted_value_gross",
        aggfunc="sum", fill_value=0,
    )
    for w in wrapper_labels:
        if w not in matrix.columns:
            matrix[w] = 0
    matrix = matrix[wrapper_labels]

    fig, ax = setup_fig(figsize=(11, 7))
    im = ax.imshow(matrix.values, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_xticklabels(matrix.columns, rotation=30, ha="right", fontsize=10)
    ax.set_yticks(range(len(matrix.index)))
    ax.set_yticklabels(matrix.index, fontsize=10)
    max_val = matrix.values.max() if matrix.values.max() > 0 else 1
    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            val = matrix.values[i, j]
            if val > 0:
                ax.text(j, i, f"${val/1000:,.0f}k",
                        ha="center", va="center", fontsize=8,
                        color="white" if val > max_val*0.4 else "black")
    fig.colorbar(im, ax=ax, label="$ value")
    ax.set_title("Tax-Location Matrix", fontfamily="Georgia", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Wrapper type", fontsize=10)
    ax.set_ylabel("Asset class", fontsize=10)
    fig.savefig(out_path, bbox_inches="tight", facecolor=CREAM)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
