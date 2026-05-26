#!/usr/bin/env python3
"""
Phase 5 (analysis half): produce Totals.csv, RateExposure.md, PayoffTimeline.csv,
Anomalies.md from loans_classified.csv.

Reading:
- <work_folder>/.analysis/loans_classified.csv
- <skill_dir>/references/data/thresholds.yaml
- <work_folder>/debts_config.yaml (auto-discovered)

Writing:
- <work_folder>/.analysis/Totals.csv
- <work_folder>/.analysis/RateExposure.md
- <work_folder>/.analysis/PayoffTimeline.csv
- <work_folder>/.analysis/Anomalies.md
- <work_folder>/.analysis/_analyze_summary.json

Usage:
    python analyze.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent))

import yaml  # noqa: E402

from _config_discover import auto_discover_config  # noqa: E402


SKILL_DIR = Path(__file__).resolve().parent.parent
THRESHOLDS_PATH = SKILL_DIR / "references" / "data" / "thresholds.yaml"


def load_yaml(p: Path) -> dict:
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# Filters
# -----------------------------------------------------------------------------

def headline_loans(loans: list[dict]) -> list[dict]:
    """Loans that count toward the headline 'total debt' figure.
    Excludes paid_in_full and informal."""
    return [l for l in loans if l.get("status") not in ("paid_in_full", "informal")]


def formal_loans(loans: list[dict]) -> list[dict]:
    """Loans with a formal rate — used for weighted-avg-rate calc."""
    return [l for l in headline_loans(loans) if _f(l.get("rate")) is not None]


# -----------------------------------------------------------------------------
# Totals
# -----------------------------------------------------------------------------

def write_totals(loans: list[dict], out_path: Path) -> dict:
    hl = headline_loans(loans)
    total = sum(_f(l.get("balance")) or 0 for l in hl)

    # By type
    by_type: dict[str, float] = {}
    for l in hl:
        by_type[l.get("type", "other")] = by_type.get(l.get("type", "other"), 0) + (_f(l.get("balance")) or 0)

    # By owner
    by_owner: dict[str, float] = {}
    for l in hl:
        by_owner[l.get("owner", "primary")] = by_owner.get(l.get("owner", "primary"), 0) + (_f(l.get("balance")) or 0)

    # By tax treatment
    by_tax: dict[str, float] = {}
    for l in hl:
        by_tax[l.get("tax_treatment", "non_deductible")] = \
            by_tax.get(l.get("tax_treatment", "non_deductible"), 0) + (_f(l.get("balance")) or 0)

    # By secured/unsecured
    secured = sum(_f(l.get("balance")) or 0 for l in hl if l.get("secured_by"))
    unsecured = total - secured

    # Write Totals.csv
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bucket", "key", "amount", "pct_of_total"])
        w.writerow(["total", "all", f"{total:.2f}", "1.0000"])
        for t, b in sorted(by_type.items(), key=lambda kv: -kv[1]):
            w.writerow(["type", t, f"{b:.2f}", f"{b/total:.4f}" if total else "0"])
        for o, b in sorted(by_owner.items(), key=lambda kv: -kv[1]):
            w.writerow(["owner", o, f"{b:.2f}", f"{b/total:.4f}" if total else "0"])
        for t, b in sorted(by_tax.items(), key=lambda kv: -kv[1]):
            w.writerow(["tax_treatment", t, f"{b:.2f}", f"{b/total:.4f}" if total else "0"])
        w.writerow(["secured_status", "secured", f"{secured:.2f}",
                    f"{secured/total:.4f}" if total else "0"])
        w.writerow(["secured_status", "unsecured", f"{unsecured:.2f}",
                    f"{unsecured/total:.4f}" if total else "0"])

    return {
        "total_debt": total,
        "by_type": by_type,
        "by_owner": by_owner,
        "by_tax_treatment": by_tax,
        "secured": secured,
        "unsecured": unsecured,
    }


# -----------------------------------------------------------------------------
# Rate exposure
# -----------------------------------------------------------------------------

def write_rate_exposure(loans: list[dict], thresholds: dict, out_path: Path) -> dict:
    formal = formal_loans(loans)
    total_formal = sum(_f(l.get("balance")) or 0 for l in formal)

    if not formal or total_formal <= 0:
        out_path.write_text("# Rate Exposure\n\n_No formal debt with rate data._\n")
        return {"weighted_avg_rate": None, "variable_exposure_pct": 0}

    # Weighted-avg rate
    weighted_avg = sum((_f(l.get("rate")) or 0) * (_f(l.get("balance")) or 0)
                        for l in formal) / total_formal

    # Variable-rate exposure
    variable = sum(_f(l.get("balance")) or 0 for l in formal
                    if (l.get("rate_type") or "").lower() in ("variable", "promo"))
    var_pct = variable / total_formal if total_formal else 0

    # Rate-band distribution
    bands = thresholds.get("thresholds", {}).get("rate_bands", [])
    by_band: list[tuple[str, float]] = []
    for band in bands:
        in_band = sum(_f(l.get("balance")) or 0 for l in formal
                        if band["min"] <= (_f(l.get("rate")) or 0) < band["max"])
        by_band.append((band["label"], in_band))

    lines = [
        "# Rate Exposure",
        "",
        f"**Weighted-average APR:** {weighted_avg*100:.2f}% across ${total_formal:,.0f} of formal debt",
        "",
        f"**Variable-rate exposure:** ${variable:,.0f} ({var_pct*100:.1f}% of formal debt)",
        "",
        "## Distribution by rate band",
        "",
        "| Band | Balance | % |",
        "| :--- | ---: | ---: |",
    ]
    for label, bal in by_band:
        pct = bal / total_formal * 100 if total_formal else 0
        lines.append(f"| {label} | ${bal:,.0f} | {pct:.1f}% |")

    # Promotional rates expiring within horizon
    horizon_days = thresholds.get("thresholds", {}).get("promo_expiry_horizon_days", 60)
    today = date.today()
    expiring = []
    for l in formal:
        rd = l.get("reset_date")
        if rd and (l.get("rate_type") or "").lower() == "promo":
            try:
                d = datetime.strptime(rd, "%Y-%m-%d").date()
                if 0 <= (d - today).days <= horizon_days:
                    expiring.append((l.get("loan_id"), rd, _f(l.get("balance"))))
            except (ValueError, TypeError):
                pass
    if expiring:
        lines += ["", f"## Promo rates expiring within {horizon_days} days", "",
                    "| Loan | Promo end | Balance |", "| :--- | :--- | ---: |"]
        for lid, rd, bal in expiring:
            lines.append(f"| `{lid}` | {rd} | ${bal:,.0f} |")

    # ARM resets within horizon
    arm_horizon = thresholds.get("thresholds", {}).get("arm_reset_horizon_months", 12)
    arm_horizon_days = arm_horizon * 30  # rough
    arm_resets = []
    for l in formal:
        rd = l.get("reset_date")
        if rd and (l.get("rate_type") or "").lower() == "variable" \
                and l.get("type") in ("mortgage", "heloc"):
            try:
                d = datetime.strptime(rd, "%Y-%m-%d").date()
                if 0 <= (d - today).days <= arm_horizon_days:
                    arm_resets.append((l.get("loan_id"), rd, _f(l.get("balance"))))
            except (ValueError, TypeError):
                pass
    if arm_resets:
        lines += ["", f"## ARM resets within {arm_horizon} months", "",
                    "| Loan | Reset date | Balance |", "| :--- | :--- | ---: |"]
        for lid, rd, bal in arm_resets:
            lines.append(f"| `{lid}` | {rd} | ${bal:,.0f} |")

    out_path.write_text("\n".join(lines) + "\n")

    return {"weighted_avg_rate": weighted_avg, "variable_exposure_pct": var_pct,
            "variable_exposure_usd": variable}


# -----------------------------------------------------------------------------
# Payoff timeline
# -----------------------------------------------------------------------------

def compute_payoff_months(balance: float, rate: Optional[float],
                            payment: Optional[float]) -> Optional[int]:
    """Months to payoff via straight amortization."""
    if not balance or not payment or balance <= 0 or payment <= 0:
        return None
    if rate is None or rate <= 0:
        return int(math.ceil(balance / payment))
    monthly_rate = rate / 12
    monthly_interest = balance * monthly_rate
    if payment <= monthly_interest:
        return None  # payment doesn't cover interest
    try:
        n = -math.log(1 - monthly_rate * balance / payment) / math.log(1 + monthly_rate)
        return int(math.ceil(n))
    except (ValueError, ZeroDivisionError):
        return None


def _is_truthy_str(v: Any) -> bool:
    """CSV round-trip turns booleans into strings. Handle both."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def write_payoff_timeline(loans: list[dict], out_path: Path) -> None:
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["loan_id", "type", "balance", "rate", "scheduled_payment",
                    "months_to_payoff", "payment_estimated", "note"])
        for l in loans:
            status = l.get("status")
            if status in ("paid_in_full",):
                continue
            balance = _f(l.get("balance")) or 0
            rate = _f(l.get("rate"))
            payment = _f(l.get("scheduled_payment"))
            est = _is_truthy_str(l.get("payment_estimated"))
            note_parts: list[str] = []
            months: Optional[int]
            if status == "informal":
                months = None
                note_parts.append("informal — no schedule")
            elif status == "revolving":
                months = None
                note_parts.append("indefinite (revolving)")
            else:
                months = compute_payoff_months(balance, rate, payment)
                if months is None and balance > 0 and payment and payment <= balance * (rate or 0) / 12:
                    note_parts.append("payment doesn't cover interest at current rate")
                if est and months is not None:
                    note_parts.append("payment estimated — verify on refresh")
            w.writerow([
                l.get("loan_id"), l.get("type"), f"{balance:.2f}",
                f"{rate:.4f}" if rate is not None else "",
                f"{payment:.2f}" if payment is not None else "",
                months if months is not None else "",
                "true" if est else "false",
                "; ".join(note_parts),
            ])


# -----------------------------------------------------------------------------
# Anomalies
# -----------------------------------------------------------------------------

def write_anomalies(loans: list[dict], thresholds: dict, out_path: Path) -> list[dict]:
    th = thresholds.get("thresholds", {})
    findings: list[dict] = []

    # High-rate revolving (CCs, HELOCs in draw)
    for l in loans:
        if l.get("status") == "revolving":
            rate = _f(l.get("rate"))
            bal = _f(l.get("balance")) or 0
            if rate and rate > th.get("high_rate_revolving_apr", 0.18) and bal > 0:
                findings.append({
                    "kind": "high_rate_revolving",
                    "loan_id": l.get("loan_id"),
                    "fact": f"`{l.get('loan_id')}` revolving at {rate*100:.2f}% APR, balance ${bal:,.0f}",
                })

    # High-rate amortizing (auto, student, personal — NOT mortgage which has its own
    # cost dynamics tied to housing). Caught the 12.5% student loan gap from real-data runs.
    high_amort = th.get("high_rate_amortizing_apr", 0.10)
    for l in loans:
        if l.get("status") == "amortizing" and l.get("type") not in ("mortgage", "heloc"):
            rate = _f(l.get("rate"))
            bal = _f(l.get("balance")) or 0
            if rate and rate > high_amort and bal > 0:
                findings.append({
                    "kind": "high_rate_amortizing",
                    "loan_id": l.get("loan_id"),
                    "fact": f"`{l.get('loan_id')}` ({l.get('type')}) amortizing at {rate*100:.2f}% APR, balance ${bal:,.0f} — above {high_amort*100:.1f}% threshold",
                })

    # ARM resets — surface ALL ARMs with a reset date (descriptive); flag near-term as a sub-kind.
    arm_near_term_days = th.get("arm_reset_horizon_months", 12) * 30
    today = date.today()
    for l in loans:
        rd = l.get("reset_date")
        if rd and (l.get("rate_type") or "").lower() == "variable" \
                and l.get("type") in ("mortgage", "heloc"):
            try:
                d = datetime.strptime(rd, "%Y-%m-%d").date()
                days_to_reset = (d - today).days
                if days_to_reset < 0:
                    # Reset already happened — config is stale; flag separately
                    findings.append({
                        "kind": "arm_reset_passed",
                        "loan_id": l.get("loan_id"),
                        "fact": f"`{l.get('loan_id')}` ARM reset date {rd} has passed — config may be stale (rate is whatever it adjusted to)",
                    })
                    continue
                months_to_reset = round(days_to_reset / 30.4)
                kind = "arm_reset_near_term" if days_to_reset <= arm_near_term_days else "arm_reset_scheduled"
                horizon_note = (f"within {th.get('arm_reset_horizon_months', 12)} months"
                                if kind == "arm_reset_near_term"
                                else f"in ~{months_to_reset} months / {months_to_reset/12:.1f} yrs")
                findings.append({
                    "kind": kind,
                    "loan_id": l.get("loan_id"),
                    "fact": f"`{l.get('loan_id')}` ARM resets {rd} ({horizon_note})",
                })
            except (ValueError, TypeError):
                pass

    # Near-payoff
    near = th.get("near_payoff_months", 6)
    for l in loans:
        try:
            term = int(l.get("term_months_remaining") or 0)
        except (ValueError, TypeError):
            term = 0
        if 0 < term <= near and l.get("status") == "amortizing":
            findings.append({
                "kind": "near_payoff",
                "loan_id": l.get("loan_id"),
                "fact": f"`{l.get('loan_id')}` within {near} months of payoff ({term} months remaining)",
            })

    # Tax-debt at high rate
    tax_alarm = th.get("tax_debt_rate_alarm", 0.07)
    for l in loans:
        if l.get("type") == "tax":
            rate = _f(l.get("rate"))
            if rate and rate > tax_alarm:
                findings.append({
                    "kind": "tax_debt_high_rate",
                    "loan_id": l.get("loan_id"),
                    "fact": f"`{l.get('loan_id')}` (tax debt) at {rate*100:.2f}% — above {tax_alarm*100:.1f}% alarm threshold",
                })

    # Payment-below-interest
    for l in loans:
        if l.get("status") == "amortizing":
            balance = _f(l.get("balance")) or 0
            rate = _f(l.get("rate")) or 0
            payment = _f(l.get("scheduled_payment")) or 0
            if balance > 0 and rate > 0 and payment > 0:
                monthly_interest = balance * rate / 12
                if payment < monthly_interest:
                    findings.append({
                        "kind": "payment_below_interest",
                        "loan_id": l.get("loan_id"),
                        "fact": f"`{l.get('loan_id')}` scheduled payment (${payment:,.2f}) below monthly interest (${monthly_interest:,.2f}) — balance growing",
                    })

    # Informal loans without rate (data-completeness flag)
    for l in loans:
        if l.get("status") == "informal" and (_f(l.get("rate")) or 0) == 0:
            findings.append({
                "kind": "informal_no_rate",
                "loan_id": l.get("loan_id"),
                "fact": f"`{l.get('loan_id')}` informal — no rate documented",
            })

    # Estimated payments (data-confidence flag) — payoff timelines for these
    # loans should be read as approximate.
    est_ids = [l.get("loan_id") for l in loans
                if _is_truthy_str(l.get("payment_estimated"))
                and l.get("status") == "amortizing"]
    if est_ids:
        findings.append({
            "kind": "payment_estimated",
            "loan_id": ", ".join(est_ids),
            "fact": (f"Scheduled payment estimated (not user-supplied) for: "
                        f"{', '.join('`'+i+'`' for i in est_ids)}. "
                        f"Months-to-payoff figures for these loans are approximate — "
                        f"verify from real statements on next refresh."),
        })

    # Write Anomalies.md
    lines = ["# Anomalies", "",
                "_Descriptive observations only. Each is a fact about the data, not a recommendation._",
                ""]
    if not findings:
        lines += ["No anomalies above configured thresholds."]
    else:
        by_kind: dict[str, list[dict]] = {}
        for f in findings:
            by_kind.setdefault(f["kind"], []).append(f)
        for kind, fs in by_kind.items():
            # Use ### (level 3) so the section nests under the report's
            # `## 6. Anything unusual?` heading without colliding.
            lines.append(f"### {kind.replace('_', ' ').title()}")
            lines.append("")
            for f in fs:
                lines.append(f"- {f['fact']}")
            lines.append("")
    out_path.write_text("\n".join(lines))

    return findings


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work_folder", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()

    if not args.work_folder.is_dir():
        print(f"error: not a directory: {args.work_folder}", file=sys.stderr)
        return 2

    config: dict[str, Any] = {}
    resolved = auto_discover_config(args.work_folder, args.config)
    if resolved:
        config = load_yaml(resolved)
        if not args.config:
            print(f"  Using config: {resolved}")

    thresholds = load_yaml(THRESHOLDS_PATH)
    # User overrides
    user_th = config.get("thresholds", {})
    if user_th:
        thresholds.setdefault("thresholds", {}).update(user_th)

    io_dir = args.work_folder / ".analysis"
    in_path = io_dir / "loans_classified.csv"
    if not in_path.is_file():
        print(f"error: {in_path} not found — run classify.py first", file=sys.stderr)
        return 2

    with in_path.open() as f:
        loans = list(csv.DictReader(f))

    totals_summary = write_totals(loans, io_dir / "Totals.csv")
    rate_summary = write_rate_exposure(loans, thresholds, io_dir / "RateExposure.md")
    write_payoff_timeline(loans, io_dir / "PayoffTimeline.csv")
    anomalies = write_anomalies(loans, thresholds, io_dir / "Anomalies.md")

    summary = {
        "total_debt": totals_summary["total_debt"],
        "loan_count_headline": len([l for l in loans if l.get("status") not in ("paid_in_full", "informal")]),
        "weighted_avg_rate": rate_summary.get("weighted_avg_rate"),
        "variable_exposure_pct": rate_summary.get("variable_exposure_pct"),
        "variable_exposure_usd": rate_summary.get("variable_exposure_usd"),
        "secured": totals_summary["secured"],
        "unsecured": totals_summary["unsecured"],
        "by_type": totals_summary["by_type"],
        "by_owner": totals_summary["by_owner"],
        "by_tax_treatment": totals_summary["by_tax_treatment"],
        "anomaly_count": len(anomalies),
    }
    (io_dir / "_analyze_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    print(f"Analysis complete.")
    print(f"  Total debt: ${totals_summary['total_debt']:,.0f}")
    if rate_summary.get("weighted_avg_rate") is not None:
        print(f"  Weighted-avg rate: {rate_summary['weighted_avg_rate']*100:.2f}%")
    if rate_summary.get("variable_exposure_usd"):
        print(f"  Variable-rate exposure: ${rate_summary['variable_exposure_usd']:,.0f} "
                f"({rate_summary['variable_exposure_pct']*100:.1f}%)")
    print(f"  Anomalies: {len(anomalies)}")
    print(f"Output:")
    for n in ("Totals.csv", "RateExposure.md", "PayoffTimeline.csv", "Anomalies.md"):
        print(f"  {io_dir / n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
