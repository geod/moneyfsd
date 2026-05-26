#!/usr/bin/env python3
"""
Phase 5 (report half): build the consolidated Debt Report.md
and the user-facing Debt Ledger.csv.

Structure follows references/report.md — descriptive only, organized
around the questions a debt holder typically asks.

Reading:
- <work_folder>/.analysis/loans_classified.csv
- <work_folder>/.analysis/Totals.csv
- <work_folder>/.analysis/RateExposure.md
- <work_folder>/.analysis/PayoffTimeline.csv
- <work_folder>/.analysis/Anomalies.md
- <work_folder>/.analysis/_analyze_summary.json
- <work_folder>/debts_config.yaml (auto-discovered)

Writing:
- <work_folder>/Debt Report.md
- <work_folder>/Debt Ledger.csv

Usage:
    python generate_report.py <work_folder> [--config PATH] [--no-open]
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import yaml  # noqa: E402

from _config_discover import auto_discover_config  # noqa: E402


def load_yaml(p: Path) -> dict:
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _f(v: Any) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def headline_loans(loans: list[dict]) -> list[dict]:
    return [l for l in loans if l.get("status") not in ("paid_in_full", "informal")]


# -----------------------------------------------------------------------------
# Section builders
# -----------------------------------------------------------------------------

def section_intro() -> list[str]:
    return [
        "# Debt Report",
        "",
        "_Descriptive only — describes what you owe and at what cost. "
        "No recommendations on refinance, payoff order, consolidation, or strategy. "
        "Those need cashflow context and goals; they'll come from a separate planning skill._",
        "",
        "This report is organized around the questions a debt holder typically asks:",
        "",
        "1. How much do I owe, and to whom?",
        "2. What's it costing me?",
        "3. When does each loan pay off at current pace?",
        "4. Where is the debt secured?",
        "5. What's tax-deductible?",
        "6. Anything unusual in the data?",
        "",
        "_(Plus — what changed since last refresh — when applicable.)_",
        "",
        "---",
    ]


def section_total(loans: list[dict], summary: dict) -> list[str]:
    hl = headline_loans(loans)
    total = sum(_f(l.get("balance")) for l in hl)
    lines = [
        "## 1. How much do I owe, and to whom?",
        "",
        f"**Total debt: {fmt_money(total)}** across {len(hl)} loan(s).",
        "",
        "![Debt composition by loan type](.analysis/chart_composition_pie.png)",
        "",
        "### By loan type",
        "",
        "| Type | Count | Balance | % of total |",
        "| :--- | ---: | ---: | ---: |",
    ]
    by_type: dict[str, list[dict]] = {}
    for l in hl:
        by_type.setdefault(l.get("type", "other"), []).append(l)
    for t, ls in sorted(by_type.items(), key=lambda kv: -sum(_f(l.get("balance")) for l in kv[1])):
        bal = sum(_f(l.get("balance")) for l in ls)
        pct = bal / total * 100 if total else 0
        lines.append(f"| `{t}` | {len(ls)} | {fmt_money(bal)} | {pct:.1f}% |")

    lines += ["", "### By owner", "", "| Owner | Balance | % of total |",
                "| :--- | ---: | ---: |"]
    by_owner: dict[str, float] = {}
    for l in hl:
        by_owner[l.get("owner", "primary")] = by_owner.get(l.get("owner", "primary"), 0) + _f(l.get("balance"))
    for o, b in sorted(by_owner.items(), key=lambda kv: -kv[1]):
        pct = b / total * 100 if total else 0
        lines.append(f"| {o} | {fmt_money(b)} | {pct:.1f}% |")

    return lines + ["", "---", ""]


def section_cost(loans: list[dict], summary: dict, rate_exposure_md: str) -> list[str]:
    lines = [
        "## 2. What's it costing me?",
        "",
        rate_exposure_md.replace("# Rate Exposure", "").strip(),
        "",
        "---",
        "",
    ]
    return lines


def section_payoff(payoff_rows: list[dict]) -> list[str]:
    lines = [
        "## 3. When does each loan pay off at current pace?",
        "",
        "_At the current scheduled payment. Doesn't reflect any extra payments — descriptive of the existing trajectory._",
        "",
        "![Payoff timeline](.analysis/chart_payoff_timeline.png)",
        "",
        "| Loan | Type | Balance | Rate | Scheduled payment | Months to payoff | Note |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    rows_with_months = [r for r in payoff_rows if r.get("months_to_payoff") not in (None, "")]
    rows_with_months.sort(key=lambda r: int(r.get("months_to_payoff") or 0))
    rows_other = [r for r in payoff_rows if r.get("months_to_payoff") in (None, "")]
    for r in rows_with_months + rows_other:
        bal = _f(r.get("balance"))
        rate = _f(r.get("rate"))
        payment = _f(r.get("scheduled_payment"))
        months = r.get("months_to_payoff") or "—"
        est = str(r.get("payment_estimated", "")).strip().lower() == "true"
        # Decorate the payment column with ~ prefix when estimated so it's
        # visually obvious that the number isn't from a real statement.
        payment_disp = f"~{fmt_money(payment)}" if est and payment else fmt_money(payment)
        note = r.get("note") or ""
        lines.append(
            f"| `{r.get('loan_id')}` | {r.get('type', '?')} | "
            f"{fmt_money(bal)} | {rate*100:.2f}% | "
            f"{payment_disp} | {months} | {note} |"
        )
    return lines + ["", "_Payment values prefixed with `~` are estimated (not from a statement) — months-to-payoff for those rows is approximate._", "", "---", ""]


def section_secured(loans: list[dict]) -> list[str]:
    hl = headline_loans(loans)
    total = sum(_f(l.get("balance")) for l in hl)
    secured = sum(_f(l.get("balance")) for l in hl if l.get("secured_by"))
    unsecured = total - secured

    lines = [
        "## 4. Where is the debt secured?",
        "",
        f"- **Secured:** {fmt_money(secured)} ({secured/total*100:.1f}% of total)" if total else "",
        f"- **Unsecured:** {fmt_money(unsecured)} ({unsecured/total*100:.1f}% of total)" if total else "",
        "",
        "### By collateral",
        "",
        "| Collateral | Balance |",
        "| :--- | ---: |",
    ]
    by_collateral: dict[str, float] = {}
    for l in hl:
        if l.get("secured_by"):
            by_collateral[l.get("secured_by")] = by_collateral.get(l.get("secured_by"), 0) + _f(l.get("balance"))
    for c, b in sorted(by_collateral.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{c}` | {fmt_money(b)} |")
    if not by_collateral:
        lines.append("| _none_ | _0_ |")
    return lines + ["", "---", ""]


def section_tax(loans: list[dict]) -> list[str]:
    hl = headline_loans(loans)
    total = sum(_f(l.get("balance")) for l in hl)
    by_tax: dict[str, float] = {}
    for l in hl:
        by_tax[l.get("tax_treatment", "non_deductible")] = \
            by_tax.get(l.get("tax_treatment", "non_deductible"), 0) + _f(l.get("balance"))

    lines = [
        "## 5. What's tax-deductible?",
        "",
        "_Eligibility per IRS rules. **Actual deductibility depends on your filing context** (MAGI, SALT cap, itemize vs standard) — this skill flags eligibility, not the realized deduction._",
        "",
        "| Treatment | Balance | % of total |",
        "| :--- | ---: | ---: |",
    ]
    for t, b in sorted(by_tax.items(), key=lambda kv: -kv[1]):
        pct = b / total * 100 if total else 0
        lines.append(f"| {t.replace('_', ' ').title()} | {fmt_money(b)} | {pct:.1f}% |")
    return lines + ["", "---", ""]


def section_anomalies(anomalies_md: str) -> list[str]:
    body = anomalies_md.replace("# Anomalies", "").strip()
    return [
        "## 6. Anything unusual in the data?",
        "",
        body,
        "",
        "---",
        "",
    ]


def section_close() -> list[str]:
    return [
        "## Pair with `investment-analysis` for a balance-sheet view",
        "",
        "This report describes one half of your balance sheet. The future "
        "`balance-sheet` skill (Layer 2) will compose this ledger with "
        "`investment-analysis` output and any non-investable assets to produce "
        "the consolidated household net-worth view.",
        "",
        "When a `debt-payoff` planning skill exists, it'll take this ledger plus "
        "your cashflow to surface payoff strategies — refinance candidates, "
        "avalanche vs snowball comparisons, payoff scenarios under different "
        "cash deployment levels. None of those questions are descriptive; they "
        "all require goals + cashflow, which is why they live elsewhere.",
        "",
        "## Appendix — drill-down material",
        "",
        "- `Debt Ledger.csv` — the full ledger (one row per loan)",
        "- `.analysis/Totals.csv` — totals by type / owner / tax treatment",
        "- `.analysis/RateExposure.md` — rate-band distribution, ARM resets, expiring promos",
        "- `.analysis/PayoffTimeline.csv` — months-to-payoff per loan",
        "- `.analysis/Anomalies.md` — full anomaly list",
        "- `.analysis/chart_*.png` — chart files",
        "",
    ]


# -----------------------------------------------------------------------------
# Ledger writer (user-facing flat CSV)
# -----------------------------------------------------------------------------

LEDGER_COLUMNS = [
    "loan_id", "owner", "type", "lender", "balance", "original_amount",
    "rate", "rate_type", "reset_date", "term_months_remaining",
    "min_payment", "scheduled_payment", "payment_estimated", "status",
    "tax_treatment", "secured_by", "co_signer", "joint_share", "notes",
]


def write_ledger(loans: list[dict], out_path: Path) -> None:
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for l in loans:
            w.writerow(l)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def open_file(path: Path) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif system == "Windows":
            subprocess.run(["cmd", "/c", "start", "", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass  # best-effort


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not args.work_folder.is_dir():
        print(f"error: not a directory: {args.work_folder}", file=sys.stderr)
        return 2

    io_dir = args.work_folder / ".analysis"
    user_folder = args.work_folder

    config: dict[str, Any] = {}
    resolved = auto_discover_config(args.work_folder, args.config)
    if resolved:
        config = load_yaml(resolved)
        if not args.config:
            print(f"  Using config: {resolved}")

    in_path = io_dir / "loans_classified.csv"
    if not in_path.is_file():
        print(f"error: {in_path} not found — run the full pipeline first", file=sys.stderr)
        return 2

    with in_path.open() as f:
        loans = list(csv.DictReader(f))

    summary_path = io_dir / "_analyze_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}

    rate_md = (io_dir / "RateExposure.md").read_text() if (io_dir / "RateExposure.md").is_file() else ""
    anom_md = (io_dir / "Anomalies.md").read_text() if (io_dir / "Anomalies.md").is_file() else ""

    # Payoff timeline rows
    payoff_path = io_dir / "PayoffTimeline.csv"
    payoff_rows = []
    if payoff_path.is_file():
        with payoff_path.open() as f:
            payoff_rows = list(csv.DictReader(f))

    parts: list[str] = []
    parts += section_intro()
    parts += section_total(loans, summary)
    parts += section_cost(loans, summary, rate_md)
    parts += section_payoff(payoff_rows)
    parts += section_secured(loans)
    parts += section_tax(loans)
    parts += section_anomalies(anom_md)
    parts += section_close()

    report_path = user_folder / "Debt Report.md"
    report_path.write_text("\n".join(p for p in parts if p is not None))

    ledger_path = user_folder / "Debt Ledger.csv"
    write_ledger(loans, ledger_path)

    print("Report written.")
    print(f"  {report_path}")
    print(f"  {ledger_path}")
    print(f"  (drill-down material in {io_dir})")

    if not args.no_open:
        open_file(report_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
