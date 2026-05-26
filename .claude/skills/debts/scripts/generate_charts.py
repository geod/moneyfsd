#!/usr/bin/env python3
"""
Phase 5 (charts half): generate composition pie, rate-by-loan bar, payoff timeline.

Reading:
- <work_folder>/.analysis/loans_classified.csv
- <work_folder>/.analysis/PayoffTimeline.csv

Writing:
- <work_folder>/.analysis/chart_composition_pie.png
- <work_folder>/.analysis/chart_rate_by_loan.png
- <work_folder>/.analysis/chart_payoff_timeline.png
- <work_folder>/.analysis/chart_debt_by_owner.png

Same aesthetic as investments (cream bg, Georgia serif titles, muted palette).

Usage:
    python generate_charts.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import matplotlib.pyplot as plt
import matplotlib as mpl  # noqa: F401

from _config_discover import auto_discover_config


# Same palette family as investments — cream background, muted accents
CREAM = "#FAF7F2"
TYPE_COLOR = {
    "mortgage":        "#1f4e79",
    "heloc":           "#2e75b6",
    "auto":            "#bf8f00",
    "student_federal": "#548235",
    "student_private": "#70ad47",
    "credit_card":     "#A04040",
    "personal":        "#c55a11",
    "401k_loan":       "#7030a0",
    "bnpl":            "#c08552",
    "medical":         "#888888",
    "tax":             "#5c0d0d",
    "family":          "#a6a6a6",
    "other":           "#666666",
}


def setup_fig(figsize=(10, 7)):
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    fig.patch.set_facecolor(CREAM)
    ax.set_facecolor(CREAM)
    return fig, ax


def setup_axes(ax, title: str, subtitle: str = "") -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#888888")
    ax.spines["bottom"].set_color("#888888")
    ax.grid(axis="y", color="#dddddd", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.set_title(title, fontfamily="Georgia", fontsize=14, fontweight="bold", pad=12)
    if subtitle:
        ax.text(0.5, 1.02, subtitle, transform=ax.transAxes, ha="center",
                fontsize=10, color="#444444")


def _f(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_loans(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def headline_loans(loans: list[dict]) -> list[dict]:
    return [l for l in loans if l.get("status") not in ("paid_in_full", "informal")]


# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------

def chart_composition_pie(loans: list[dict], out_path: Path) -> None:
    hl = headline_loans(loans)
    totals: dict[str, float] = {}
    for l in hl:
        t = l.get("type", "other")
        totals[t] = totals.get(t, 0) + _f(l.get("balance"))

    if not totals:
        return

    items = sorted(totals.items(), key=lambda kv: -kv[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    colors = [TYPE_COLOR.get(k, "#666") for k in labels]

    fig, ax = plt.subplots(figsize=(9, 7), dpi=150)
    fig.patch.set_facecolor(CREAM)
    ax.set_facecolor(CREAM)
    wedges, _ = ax.pie(
        values, colors=colors, startangle=90, counterclock=False,
        wedgeprops=dict(linewidth=2, edgecolor="white"),
    )
    ax.set_title("Debt composition by loan type", fontfamily="Georgia",
                    fontsize=14, fontweight="bold", pad=12)
    total = sum(values)
    legend_labels = [
        f"{k.replace('_', ' ').title()}: ${v:,.0f} ({v/total*100:.1f}%)"
        for k, v in items
    ]
    ax.legend(wedges, legend_labels, loc="center left",
                bbox_to_anchor=(1, 0.5), frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, facecolor=CREAM)
    plt.close(fig)


def chart_rate_by_loan(loans: list[dict], out_path: Path) -> None:
    hl = [l for l in headline_loans(loans) if _f(l.get("rate")) > 0]
    if not hl:
        return
    hl.sort(key=lambda l: _f(l.get("rate")), reverse=True)

    labels = [l.get("loan_id", "?") for l in hl]
    rates = [_f(l.get("rate")) * 100 for l in hl]
    colors = [TYPE_COLOR.get(l.get("type", "other"), "#666") for l in hl]

    fig, ax = setup_fig(figsize=(10, max(4, 0.4 * len(labels) + 2)))
    setup_axes(ax, "APR by loan", "Sorted high-to-low, colored by loan type")
    y = list(range(len(labels)))
    ax.barh(y, rates, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("APR (%)")
    for i, r in enumerate(rates):
        ax.text(r + 0.1, i, f"{r:.2f}%", va="center", fontsize=8, color="#444")
    fig.tight_layout()
    fig.savefig(out_path, facecolor=CREAM)
    plt.close(fig)


def chart_payoff_timeline(payoff_csv: Path, out_path: Path) -> None:
    if not payoff_csv.is_file():
        return
    with payoff_csv.open() as f:
        rows = list(csv.DictReader(f))

    rows = [r for r in rows if r.get("months_to_payoff") not in (None, "")]
    if not rows:
        return

    rows.sort(key=lambda r: int(r.get("months_to_payoff") or 0))
    labels = [r.get("loan_id", "?") for r in rows]
    months = [int(r.get("months_to_payoff") or 0) for r in rows]
    colors = [TYPE_COLOR.get(r.get("type", "other"), "#666") for r in rows]

    fig, ax = setup_fig(figsize=(10, max(4, 0.4 * len(labels) + 2)))
    setup_axes(ax, "Months to payoff at current scheduled payment",
                "Excludes revolving and informal loans")
    y = list(range(len(labels)))
    ax.barh(y, months, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Months")
    for i, m in enumerate(months):
        years = m / 12
        label = f"{m}m ({years:.1f}y)" if years >= 1 else f"{m}m"
        ax.text(m + max(months) * 0.01, i, label, va="center", fontsize=8, color="#444")
    fig.tight_layout()
    fig.savefig(out_path, facecolor=CREAM)
    plt.close(fig)


def chart_debt_by_owner(loans: list[dict], out_path: Path) -> None:
    hl = headline_loans(loans)
    by_owner: dict[str, float] = {}
    for l in hl:
        by_owner[l.get("owner", "primary")] = by_owner.get(l.get("owner", "primary"), 0) + _f(l.get("balance"))
    if not by_owner:
        return
    items = sorted(by_owner.items(), key=lambda kv: -kv[1])
    fig, ax = setup_fig(figsize=(8, 5))
    setup_axes(ax, "Debt by owner")
    x = list(range(len(items)))
    ax.bar(x, [v for _, v in items], color="#1f4e79", edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([k for k, _ in items])
    ax.set_ylabel("Balance ($)")
    for i, (_, v) in enumerate(items):
        ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=9, color="#444")
    fig.tight_layout()
    fig.savefig(out_path, facecolor=CREAM)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    ap.add_argument("--config", type=Path, default=None,
                    help="debts_config.yaml (accepted for CLI uniformity)")
    args = ap.parse_args()

    if not args.work_folder.is_dir():
        print(f"error: not a directory: {args.work_folder}", file=sys.stderr)
        return 2

    resolved = auto_discover_config(args.work_folder, args.config)
    if resolved and not args.config:
        print(f"  Using config: {resolved}")

    io_dir = args.work_folder / ".analysis"
    in_path = io_dir / "loans_classified.csv"
    if not in_path.is_file():
        print(f"error: {in_path} not found — run classify.py first", file=sys.stderr)
        return 2

    loans = load_loans(in_path)

    chart_composition_pie(loans, io_dir / "chart_composition_pie.png")
    chart_rate_by_loan(loans, io_dir / "chart_rate_by_loan.png")
    chart_payoff_timeline(io_dir / "PayoffTimeline.csv", io_dir / "chart_payoff_timeline.png")
    chart_debt_by_owner(loans, io_dir / "chart_debt_by_owner.png")

    print("Charts written:")
    for n in ("chart_composition_pie.png", "chart_rate_by_loan.png",
                "chart_payoff_timeline.png", "chart_debt_by_owner.png"):
        print(f"  {io_dir / n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
