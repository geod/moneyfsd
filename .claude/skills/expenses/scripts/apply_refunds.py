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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', required=True)
    parser.add_argument('--refunds', required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.csv)

    # Drop existing refund rows
    refund_mask = df['Original Category'].fillna('').str.contains('REFUND|RETURN|CREDIT', case=False)
    removed = int(refund_mask.sum())
    if removed:
        print(f"Dropped {removed} existing refund/credit rows before re-append")
    df = df[~refund_mask].copy()

    with open(args.refunds) as f:
        spec = yaml.safe_load(f)

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

    if not rows:
        print("No refunds in spec; nothing to append.")
        df.to_csv(args.csv, index=False)
        return

    add = pd.DataFrame(rows)
    out = pd.concat([df, add], ignore_index=True)
    out.to_csv(args.csv, index=False)
    print(f"Added {len(add)} refund rows totaling ${add['Amount'].sum():,.2f}")
    print(f"New total: ${out['Amount'].sum():,.2f} ({len(out):,} txns)")


if __name__ == '__main__':
    main()
