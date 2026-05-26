#!/usr/bin/env python3
"""
Phase 4: classify each loan with `status`, `tax_treatment`, `secured_by`.

Reading:
- <work_folder>/.analysis/loans_consolidated.csv
- <skill_dir>/references/data/loan_type_taxonomy.yaml
- <skill_dir>/references/data/thresholds.yaml
- <work_folder>/debts_config.yaml (auto-discovered)

Writing:
- <work_folder>/.analysis/loans_classified.csv

Usage:
    python classify.py <work_folder> [--config PATH]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import yaml  # noqa: E402

from _config_discover import auto_discover_config  # noqa: E402


SKILL_DIR = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = SKILL_DIR / "references" / "data" / "loan_type_taxonomy.yaml"
THRESHOLDS_PATH = SKILL_DIR / "references" / "data" / "thresholds.yaml"


def load_yaml(p: Path) -> dict:
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def classify_loan(loan: dict, taxonomy: dict, defaults: dict, config: dict) -> dict:
    """Mutates and returns the loan row with status/tax_treatment/secured_by populated."""

    loan_type = loan.get("type", "other")
    type_meta = taxonomy.get("types", {}).get(loan_type, {})

    # --- Status -----------------------------------------------------------
    if not loan.get("status"):
        # Special case: credit_card with no balance OR config-flagged paid_in_full
        if loan_type == "credit_card":
            try:
                bal = float(loan.get("balance", 0) or 0)
            except (TypeError, ValueError):
                bal = 0
            if bal <= 0:
                loan["status"] = "paid_in_full"
            else:
                loan["status"] = type_meta.get("default_status", "revolving")
        else:
            loan["status"] = type_meta.get("default_status", "amortizing")

    # --- Tax treatment ----------------------------------------------------
    # Inference order:
    # 1. Explicit per-loan override in config (not currently supported; future hook)
    # 2. HELOC use flag → home_improvement vs mixed vs other
    # 3. Mortgage on primary vs secondary
    # 4. Type default from taxonomy
    if loan_type == "heloc":
        # Look up the matching config entry by loan_id — checking BOTH
        # `accounts` (statement-backed) and `manual_entries` (manual loans).
        # Earlier versions only checked accounts, which silently lost the
        # `use: home_improvement` flag on manually-entered HELOCs and
        # mis-classified them as non-deductible.
        all_entries = (config.get("accounts") or []) + (config.get("manual_entries") or [])
        config_entry = next(
            (e for e in all_entries if e.get("loan_id") == loan.get("loan_id")),
            {},
        )
        use = config_entry.get("use", "unspecified")
        if use == "home_improvement":
            loan["tax_treatment"] = defaults.get("heloc_home_improvement", "deductible")
        elif use == "mixed":
            loan["tax_treatment"] = defaults.get("heloc_mixed_use", "partially_deductible")
        else:
            loan["tax_treatment"] = defaults.get("heloc_unspecified", "non_deductible")
    elif loan_type == "mortgage":
        # IRS $750k cap (post-2017 TCJA): interest deductible only on the
        # first $750k of mortgage principal. Loans above that limit are
        # `partially_deductible` — the portion of interest attributable to
        # the cap is deductible, the rest isn't. (Pre-Dec-16-2017 loans
        # have a $1M cap — not modeled here; would need origination date.)
        try:
            balance = float(loan.get("balance", 0) or 0)
        except (TypeError, ValueError):
            balance = 0
        if balance > 750_000:
            loan["tax_treatment"] = "partially_deductible"
        else:
            loan["tax_treatment"] = type_meta.get("default_tax_treatment", "deductible")
    else:
        loan["tax_treatment"] = type_meta.get("default_tax_treatment", "non_deductible")

    # --- Secured by -------------------------------------------------------
    if not loan.get("secured_by"):
        loan["secured_by"] = type_meta.get("default_secured_by")

    return loan


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

    taxonomy = load_yaml(TAXONOMY_PATH)
    thresholds = load_yaml(THRESHOLDS_PATH)
    defaults = thresholds.get("tax_treatment_defaults", {})

    io_dir = args.work_folder / ".analysis"
    in_path = io_dir / "loans_consolidated.csv"
    out_path = io_dir / "loans_classified.csv"

    if not in_path.is_file():
        print(f"error: {in_path} not found — run consolidate.py first", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with in_path.open() as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(classify_loan(row, taxonomy, defaults, config))

    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Classified {len(rows)} loan(s).")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
