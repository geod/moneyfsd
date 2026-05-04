"""Rental P&L generator.

Reads the same expenses_config.yaml as consolidate.py, re-ingests the
sources, and produces a separate `Rental P&L.csv` containing ONLY rows
matching exclusions tagged with `kind: rental_operating` or
`kind: rental_escrow`.

Why a separate script? consolidate.py correctly excludes rental items so
the lifestyle ledger is clean — but loses visibility into the rental side.
This script consumes the same exclusion rules in reverse: it keeps the
rental rows and drops everything else.

Usage:
    python rental_pnl.py --config expenses_config.yaml

Output schema:
    Date | Source | Description | Amount | Bucket | Rule
        - Bucket: rental_operating | rental_escrow
        - Rule:   the human-readable description from the YAML rule
                  (so you can trace each row back to the rule that kept it)

Income tracking is a TODO. Lifestyle outflows are easy because every
ingester filters to outflows by default. To track tenant rent receipts,
you'll need to either:
  1. Re-run the ingester with an `include_inflows: true` flag added (not
     yet implemented in consolidate.py), OR
  2. Manually append rental-income rows to this CSV before tax filing.
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

# Re-use ingest handlers from the sibling consolidate.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from consolidate import INGEST_HANDLERS  # noqa: E402

RENTAL_KINDS = {"rental_operating", "rental_escrow"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="Rental P&L.csv")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    base = config_path.parent
    with open(config_path) as f:
        config = yaml.safe_load(f)

    rental_rules = [r for r in (config.get("exclusions") or [])
                    if r.get("kind") in RENTAL_KINDS]
    if not rental_rules:
        print("No exclusions tagged with kind: rental_operating or rental_escrow.")
        print("Add 'kind:' fields to your rental exclusions in expenses_config.yaml.")
        print("Example:")
        print("  exclusions:")
        print("    - description: \"Rental property — HOA / management fee\"")
        print("      kind: rental_operating")
        print("      match: { description_contains: <property-management firm name> }")
        return 1

    # Ingest each source — apply NO exclusions; we'll select rental rows below
    frames = []
    for src in config["sources"]:
        handler = INGEST_HANDLERS.get(src["type"])
        if not handler:
            print(f"WARN: unknown source type '{src['type']}', skipping")
            continue
        print(f"Ingesting {src['type']}: {src['file']}")
        if src["type"].endswith("_pdf"):
            df = handler(src["file"], src, base)
        else:
            path = src["file"]
            if not Path(path).is_absolute():
                path = base / path
            df = handler(path, src)
        frames.append(df)

    if not frames:
        print("No sources ingested.")
        return 1

    all_tx = pd.concat(frames, ignore_index=True)

    # Apply each rental rule INVERTED — keep matching rows, tag with bucket
    rental_rows = []
    for rule in rental_rules:
        match = rule.get("match", {})
        mask = pd.Series([True] * len(all_tx), index=all_tx.index)
        if "date" in match:
            mask &= all_tx["Date"].isin(match["date"])
        if "description_contains" in match:
            kw = match["description_contains"]
            if isinstance(kw, str):
                kw = [kw]
            pattern = "|".join(re.escape(k) for k in kw)
            mask &= all_tx["Desc"].fillna("").str.contains(pattern, case=False, regex=True)
        if "amount" in match:
            mask &= all_tx["Amount"].round(2) == round(float(match["amount"]), 2)
        if "source" in match:
            mask &= all_tx["Source"] == match["source"]
        n = int(mask.sum())
        if n == 0:
            continue
        sub = all_tx[mask].copy()
        sub["Bucket"] = rule.get("kind", "other")
        sub["Rule"] = rule.get("description", "?")
        rental_rows.append(sub)

    if not rental_rows:
        print("No rental rows matched any rule.")
        return 1

    out = pd.concat(rental_rows, ignore_index=True)
    out = out.rename(columns={"Desc": "Description", "OrigCat": "Original Category"})
    out = out[["Date", "Source", "Description", "Amount", "Bucket", "Rule"]]
    out = out.sort_values("Date")

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = base / output_path
    out.to_csv(output_path, index=False)

    print(f"\nSaved rental P&L: {output_path} ({len(out):,} rows)")

    # Summary by bucket
    op_mask = out["Bucket"] == "rental_operating"
    es_mask = out["Bucket"] == "rental_escrow"
    op_total = out.loc[op_mask, "Amount"].sum()
    es_total = out.loc[es_mask, "Amount"].sum()
    print(f"  Operating expenses: ${op_total:>12,.2f}  ({op_mask.sum()} rows)")
    print(f"  Escrow round-trips: ${es_total:>12,.2f}  ({es_mask.sum()} rows)")
    print(f"  P&L impact (operating only): ${-op_total:,.2f}  (negative = net loss before income)")
    print()
    print("To complete the rental P&L for tax prep:")
    print("  - Add rental income (Zelle from tenants, lease payments) — see Income tracking note in this script")
    print("  - Verify the Bucket column splits operating vs. escrow correctly")
    print("  - Escrow round-trips (deposits collected/returned) are NOT P&L items;"
          " they're balance-sheet events. Don't include them in income/expense totals.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
