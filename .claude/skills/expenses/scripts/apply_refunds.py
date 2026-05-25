"""
Append refund / return / credit rows to a Lifestyle Expenses CSV.

Each refund is added as a negative-amount row in the same Category/Subcategory
as the original purchase, preserving the audit trail.

Idempotent: drops any existing rows tagged REFUND/RETURN/CREDIT in the
'Original Category' column before re-appending. Safe to rerun after each
refund batch.

Usage:
    python apply_refunds.py --csv "Lifestyle Expenses.csv" --refunds refunds.yaml

refunds.yaml format:
    refunds:
      - date: 07/20/2025
        source: Partner AmEx
        description: "SUMMER CAMP REFUND (RETURN)"
        category: Kids
        subcategory: Kids
        amount: -140.00
        original_category: "Partner AmEx / RETURN"
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml


REFUND_TAG_REGEX = r'REFUND|RETURN|CREDIT'


def drop_existing_refunds(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop rows whose `Original Category` is tagged REFUND/RETURN/CREDIT.

    Returns the trimmed DataFrame and the count of dropped rows. Combined
    with ``build_refund_rows``, makes ``apply_refunds_to_df`` idempotent:
    re-running with the same spec produces the same final dataset.
    """
    mask = df['Original Category'].fillna('').str.contains(REFUND_TAG_REGEX, case=False)
    removed = int(mask.sum())
    return df[~mask].copy(), removed


def build_refund_rows(spec: dict) -> list[dict]:
    """Translate a refunds-spec dict into uniform refund rows."""
    rows = []
    for r in spec.get('refunds', []):
        rows.append({
            'Date': r['date'],
            'Source': r['source'],
            'Description': r['description'],
            'Category': r['category'],
            'Subcategory': r['subcategory'],
            'Amount': r['amount'],
            'Original Category': r.get('original_category', f"{r['source']} / REFUND"),
        })
    return rows


def apply_refunds_to_df(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Pure-function form of the CLI: returns a new DataFrame with refund
    rows appended (and any pre-existing refund rows dropped first).
    """
    trimmed, _ = drop_existing_refunds(df)
    rows = build_refund_rows(spec)
    if not rows:
        return trimmed
    add = pd.DataFrame(rows)
    return pd.concat([trimmed, add], ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', required=True)
    parser.add_argument('--refunds', required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    trimmed, removed = drop_existing_refunds(df)
    if removed:
        print(f"Dropped {removed} existing refund/credit rows before re-append")

    with open(args.refunds) as f:
        spec = yaml.safe_load(f)

    rows = build_refund_rows(spec)
    if not rows:
        print("No refunds in spec; nothing to append.")
        trimmed.to_csv(args.csv, index=False)
        return

    add = pd.DataFrame(rows)
    out = pd.concat([trimmed, add], ignore_index=True)
    out.to_csv(args.csv, index=False)
    print(f"Added {len(add)} refund rows totaling ${add['Amount'].sum():,.2f}")
    print(f"New total: ${out['Amount'].sum():,.2f} ({len(out):,} txns)")


if __name__ == '__main__':
    main()
