"""
Config-driven consolidation of multiple expense source files into a single
ledger with uniform schema:

    Date | Source | Description | Category | Subcategory | Amount | Processor | Original Category

Sign convention: positive = outflow.

Usage:
    python consolidate.py --config user_config.yaml --output "Lifestyle Expenses.csv"

The config (YAML) describes the user's accounts, exclusions, and taxonomy.
See assets/example_config.yaml for the schema.

The categorization logic uses a keyword table loaded from a YAML taxonomy file,
plus user-confirmed one-off overrides specified in the config.
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# PDF support — pdfplumber is auto-installed on first PDF source
# ---------------------------------------------------------------------------

def _ensure_pdfplumber():
    """Import pdfplumber, installing it via pip if missing."""
    try:
        import pdfplumber
        return pdfplumber
    except ImportError:
        print("Installing pdfplumber (one-time, ~5s)...", flush=True)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "pdfplumber"]
        )
        import pdfplumber
        return pdfplumber


def _resolve_pdf_paths(file_spec, base):
    """Resolve a config 'file:' value to a list of PDF paths.
    Accepts a single PDF, a folder of PDFs, or a glob pattern."""
    p = Path(file_spec)
    if not p.is_absolute():
        p = base / p
    if p.is_dir():
        paths = sorted(p.glob("*.pdf"))
        if not paths:
            raise ValueError(f"No PDFs found in folder: {p}")
        return paths
    if p.exists():
        return [p]
    matches = sorted(Path(base).glob(file_spec))
    if matches:
        return matches
    raise FileNotFoundError(f"No PDF source matched: {file_spec}")


# Statement period header — captures the closing date so we can attach a year
# to MM/DD-only transaction lines. Supports both MM/DD/YY and long-form
# ("May 13, 2025 through June 11, 2025") formats.
_PERIOD_NUMERIC_RE = re.compile(
    r"(\d{2}/\d{2}/\d{2,4})\s*(?:through|to|[-–])\s*(\d{2}/\d{2}/\d{2,4})",
    re.IGNORECASE,
)
_PERIOD_LONG_RE = re.compile(
    r"([A-Z][a-z]+ \d{1,2},?\s*\d{4})\s*(?:through|to|[-–])\s*"
    r"([A-Z][a-z]+ \d{1,2},?\s*\d{4})",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"], 1)}

# Card-style transaction line: MM/DD <description> <amount>
_TXN_RE = re.compile(
    r"^(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$"
)
# Checking-style transaction line: MM/DD <description> <amount> <running balance>
_CHECKING_TXN_RE = re.compile(
    r"^(\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})\s*$"
)

# Chase Sapphire Checking statements occasionally collapse a section-end
# marker into the following transaction line. Example seen in the wild:
#   "*end*transac0tion detail6/04 Rocket Mortgage ... -10,478.65 35,460.94"
# (the "0" of "06/04" gets fused into "transaction"). The plain regex above
# fails because the line no longer starts with a date. _recover_marker_bleed
# rescues those lines by finding the embedded MM/DD or M/DD and rebuilding a
# clean prefix.
def _recover_marker_bleed(stripped):
    if "*start*" not in stripped.lower() and "*end*" not in stripped.lower():
        return stripped
    dm = re.search(r"(\d{1,2})/(\d{2})\s+", stripped)
    if not dm:
        return stripped
    m, d = dm.groups()
    return f"{int(m):02d}/{d} " + stripped[dm.end():]


# ---------------------------------------------------------------------------
# Statement-summary calibration helpers
#
# Most bank PDFs print a summary box on page 1 that totals withdrawals,
# fees, and checks paid for the period. After parsing transactions we compare
# our total to the summary; if drift > 2% something silently dropped.
# ---------------------------------------------------------------------------
def _extract_checking_summary_outflow(text):
    """Sum all outflow categories from a Chase-style checking summary box.
    Returns float or None if no recognisable summary was found."""
    patterns = [
        r'ATM\s*&\s*Debit\s*Card\s*Withdrawals\s+-?\$?([\d,]+\.\d{2})',
        r'Electronic\s+Withdrawals\s+-?\$?([\d,]+\.\d{2})',
        r'^\s*Fees\s+-?\$?([\d,]+\.\d{2})',
        r'Checks\s+Paid\s+-?\$?([\d,]+\.\d{2})',
        r'Other\s+Withdrawals\s+-?\$?([\d,]+\.\d{2})',
    ]
    total = 0.0
    found = False
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            total += float(m.group(1).replace(',', ''))
            found = True
    return total if found else None


def _extract_card_summary_outflow(text):
    """Sum 'Purchases' + 'Fees Charged' + 'Interest Charged' from a card summary.
    Returns float or None if not found."""
    patterns = [
        r'Purchases\s+\+?\$?([\d,]+\.\d{2})',
        r'Cash\s*Advances\s+\+?\$?([\d,]+\.\d{2})',
        r'Balance\s*Transfers\s+\+?\$?([\d,]+\.\d{2})',
        r'Fees\s+Charged\s+\+?\$?([\d,]+\.\d{2})',
        r'Interest\s+Charged\s+\+?\$?([\d,]+\.\d{2})',
    ]
    total = 0.0
    found = False
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            total += float(m.group(1).replace(',', ''))
            found = True
    return total if found else None


def _calibration_warn(path_name, parsed_gross, summary_total,
                      drift_pct=0.05, drift_abs=100.0):
    """Compare parsed outflow total to statement summary; warn on drift.
    Two-threshold model: only fire if BOTH a meaningful percentage drift
    (default 5%) AND a non-trivial absolute diff (default $100) are exceeded.
    This filters out the dozen of $23 "annual fee" false positives that
    come from card statements where the summary includes line items we
    deliberately excluded.

    Suppresses warnings when summary_total looks suspiciously partial
    (one orphan summary line under $200) — likely a regex miss, not a
    real parsing problem.
    """
    if summary_total is None or summary_total < 200:
        return None
    if parsed_gross == 0:
        return None
    diff = parsed_gross - summary_total
    drift = abs(diff) / summary_total
    if drift < drift_pct or abs(diff) < drift_abs:
        return None
    sev = 'warn' if drift <= 0.10 else 'error'
    return (sev, f"  [{sev}] {path_name}: parsed ${parsed_gross:,.2f} vs statement summary ${summary_total:,.2f} "
                 f"(drift {drift*100:.1f}%, diff ${diff:+,.2f}) — possible parser miss")

# Default checking exclusions — patterns that contaminate "lifestyle" if kept.
# Extend per-source via source_config['exclude_description_patterns'].
DEFAULT_CHECKING_EXCLUDES = [
    # Credit-card payoffs (already counted on the card side)
    r"APPLECARD\s+GSBANK\s+PAYMENT",
    r"Payment\s+To\s+Chase\s+Card\s+Ending",
    r"CHASE\s+CREDIT\s+CRD\s+AUTOPAY",
    r"CHASE\s+CARD.*EPAY",
    r"AMEX\s+EPAYMENT",
    r"SYNCHRONY\s+BANK\s+(CC\s+PYMT|PAYMENT)",
    r"CITI(BANK)?\s+CARD.*PAYMENT",
    r"CAPITAL\s+ONE.*CRCARDPMT",
    r"DISCOVER.*E-PAYMENT",
    # Investment / brokerage funding (not consumption)
    r"SCHWAB.*MONEYLINK",
    r"VANGUARD.*BUY",
    r"FIDELITY.*FID\s+BKG\s+SVC",
    r"SCHOLARSHARE\s+ACH\s+CONTRIB",
    # IRS / state INCOME tax (separate from lifestyle).
    # NOTE: do NOT exclude property tax here — property tax on a primary or
    # secondary residence is a real lifestyle cost and should land in
    # Housing/Property Tax via the taxonomy.
    r"IRS\s+USATAXPYMT",
    r"FRANCHISE\s+TAX",
]


def _parse_period(text):
    """Return (end_month, end_year) from the statement period header.
    Returns (None, None) if no period is found."""
    head = text[:4000]
    m = _PERIOD_NUMERIC_RE.search(head)
    if m:
        end = m.group(2)
        parts = end.split("/")
        mm, yr = int(parts[0]), int(parts[-1])
        return mm, (yr + 2000 if yr < 100 else yr)
    m = _PERIOD_LONG_RE.search(head)
    if m:
        end = m.group(2)
        toks = re.split(r"[\s,]+", end.strip())
        mm = _MONTHS.get(toks[0].lower())
        yr = int(toks[-1])
        if mm:
            return mm, yr
    return None, None


def _infer_statement_year(text, fallback_path):
    """Pull the closing-date year from the statement period.
    Falls back to the file's mtime year if no period header is found."""
    _, yr = _parse_period(text)
    if yr is not None:
        return yr
    print(f"  WARN: no statement period header in {fallback_path.name} — "
          f"falling back to file mtime year", flush=True)
    return datetime.fromtimestamp(fallback_path.stat().st_mtime).year


def _attach_year(mmdd, end_year, end_month):
    """Given a MM/DD string and the statement's closing month/year, return
    MM/DD/YYYY. If the row's month is greater than the closing month, it
    actually belongs to the prior year (statement spans Dec → Jan)."""
    mm = int(mmdd.split("/")[0])
    yr = end_year - 1 if mm > end_month else end_year
    return f"{mmdd}/{yr}"


def ingest_chase_card_pdf(file_spec, source_config, base):
    """Chase credit-card statement PDFs → uniform schema.

    Parses every MM/DD-prefixed transaction line in the statement. Excludes
    rows whose description matches an exclude pattern (default: card-payoff
    rows like 'AUTOMATIC PAYMENT - THANK YOU' to avoid double-counting on
    the checking side). Sign convention: positive = outflow, matches Chase's
    own convention on these statements."""
    pdfplumber = _ensure_pdfplumber()
    paths = _resolve_pdf_paths(file_spec, base)

    exclude_patterns = source_config.get("exclude_description_patterns", [
        # Chase ships several payoff descriptions across statement formats:
        #   "AUTOMATIC PAYMENT - THANK YOU" (auto-pay; hyphen separator)
        #   "Payment Thank You-Mobile"      (mobile-app payoff)
        #   "Payment Thank You"             (web payoff)
        # All are card payoffs that get double-counted if not excluded.
        # The hyphen / whitespace between PAYMENT and THANK varies across
        # statement formats — match either.
        r"PAYMENT[\s\-]+THANK\s+YOU",
    ])
    exclude_re = re.compile("|".join(exclude_patterns), re.IGNORECASE) if exclude_patterns else None

    rows = []
    calibration_warnings = []
    for path in paths:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        end_month, end_year = _parse_period(text)
        if end_year is None:
            end_year = _infer_statement_year(text, path)
            end_month = 12
        per_file_count = 0
        per_file_total = 0.0
        per_file_gross = 0.0  # all outflows in statement, before exclusions (for calibration)
        for line in text.splitlines():
            stripped = _recover_marker_bleed(line.strip())
            mt = _TXN_RE.match(stripped)
            if not mt:
                continue
            mmdd, desc, amt = mt.groups()
            try:
                amount = float(amt.replace("$", "").replace(",", ""))
            except ValueError:
                continue
            if amount > 0:
                per_file_gross += amount
            if exclude_re and exclude_re.search(desc):
                continue
            rows.append({
                "Date": _attach_year(mmdd, end_year, end_month),
                "Desc": desc.strip(),
                "OrigCat": "",
                "Amount": amount,
            })
            per_file_count += 1
            per_file_total += amount
        print(f"  {path.name}: {per_file_count} txns, ${per_file_total:,.2f}")
        # Calibration: compare parsed gross to statement summary box
        summary_total = _extract_card_summary_outflow(text)
        warn = _calibration_warn(path.name, per_file_gross, summary_total)
        if warn:
            calibration_warnings.append(warn[1])
    if calibration_warnings:
        print("Calibration warnings:")
        for w in calibration_warnings:
            print(w)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Source", "Desc", "OrigCat", "Amount"])
    df["Source"] = source_config.get("name", "Chase Card")
    return df[["Date", "Source", "Desc", "OrigCat", "Amount"]]


def ingest_generic_checking_pdf(file_spec, source_config, base):
    """Generic checking statement PDFs → uniform schema.

    Most US bank checking statements have a transactions table per page with
    Date / Description / Amount. Treats outflows as positive. Excludes any
    line whose description matches an exclusion pattern from source_config."""
    pdfplumber = _ensure_pdfplumber()
    paths = _resolve_pdf_paths(file_spec, base)

    exclude_patterns = source_config.get(
        "exclude_description_patterns", DEFAULT_CHECKING_EXCLUDES)
    exclude_re = re.compile("|".join(exclude_patterns), re.IGNORECASE) if exclude_patterns else None

    # Checking PDFs print '<txn_amount> <running_balance>' at the end of each
    # transaction line. Use the two-amount regex; the FIRST number is the txn
    # amount, the second is the balance. Sign convention: negative = outflow.
    rows = []
    calibration_warnings = []
    for path in paths:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        end_month, end_year = _parse_period(text)
        if end_year is None:
            end_year = _infer_statement_year(text, path)
            end_month = 12

        per_file_count = 0
        per_file_total = 0.0
        per_file_gross = 0.0  # all outflows pre-exclusion (for calibration)
        for line in text.splitlines():
            stripped = _recover_marker_bleed(line.strip())
            mt = _CHECKING_TXN_RE.match(stripped)
            if not mt:
                continue
            mmdd, desc, amt, _balance = mt.groups()
            try:
                amount = float(amt.replace(",", ""))
            except ValueError:
                continue
            sign = source_config.get("amount_sign", "negative_is_outflow")
            is_outflow = (amount < 0) if sign == "negative_is_outflow" else (amount > 0)
            if not is_outflow:
                continue  # inflow / deposit — not lifestyle
            absamt = abs(amount)
            per_file_gross += absamt
            if exclude_re and exclude_re.search(desc):
                continue
            rows.append({
                "Date": _attach_year(mmdd, end_year, end_month),
                "Desc": desc.strip(),
                "OrigCat": "",
                "Amount": absamt,
            })
            per_file_count += 1
            per_file_total += absamt
        print(f"  {path.name}: {per_file_count} txns, ${per_file_total:,.2f}")
        # Calibration: compare parsed gross outflow to summary box
        summary_total = _extract_checking_summary_outflow(text)
        warn = _calibration_warn(path.name, per_file_gross, summary_total)
        if warn:
            calibration_warnings.append(warn[1])
    if calibration_warnings:
        print("Calibration warnings:")
        for w in calibration_warnings:
            print(w)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Source", "Desc", "OrigCat", "Amount"])
    df["Source"] = source_config.get("name", "Checking")
    return df[["Date", "Source", "Desc", "OrigCat", "Amount"]]


# ---------------------------------------------------------------------------
# Source-specific ingestion
# ---------------------------------------------------------------------------

def ingest_apple_card(path, source_config):
    """Apple Card export → uniform schema."""
    df = pd.read_csv(path)
    df = df.rename(columns={'Transaction Date': 'Date', 'Amount (USD)': 'Amount'})
    df['Amount'] = pd.to_numeric(df['Amount'])

    # Filter Type column
    keep_types = source_config.get('keep_types', ['Purchase', 'Credit', 'Debit', 'Other'])
    df = df[df['Type'].isin(keep_types)].copy()

    # Drop Daily Cash Adjustment rows (cashback reversal, not real expense)
    df = df[~df['Description'].fillna('').str.contains(
        'DAILY CASH ADJUSTMENT', case=False)].copy()

    # Cardholder mapping
    cardholder_map = source_config.get('cardholder_map', {})
    if cardholder_map and 'Purchased By' in df.columns:
        df['Source'] = df['Purchased By'].map(cardholder_map).fillna(source_config.get('name', 'Apple Card'))
    else:
        df['Source'] = source_config.get('name', 'Apple Card')

    df['Desc'] = df['Merchant'].fillna(df['Description']) if 'Merchant' in df.columns else df['Description']
    df['OrigCat'] = df.get('Category', '')
    return df[['Date', 'Source', 'Desc', 'OrigCat', 'Amount']]


def ingest_chase_card(path, source_config):
    """Chase credit card export → uniform schema."""
    df = pd.read_csv(path)
    df = df.rename(columns={'Transaction Date': 'Date', 'Amount (USD)': 'Amount'})
    df['Amount'] = pd.to_numeric(df['Amount'])

    # Identify card payoff rows (exclude — already counted on checking side)
    payoff_pattern = source_config.get(
        'payoff_pattern', 'AUTOMATIC PAYMENT - THANK YOU')
    payoff = df['Description'].fillna('').str.contains(payoff_pattern, case=False)

    keep_types = source_config.get('keep_types', ['Sale', 'Purchase', 'Fee', 'Credit', 'Return'])
    df = df[
        df['Type'].isin(keep_types)
        | ((df['Type'] == 'Payment') & ~payoff)  # merchant refunds tagged Payment
    ].copy()

    df['Source'] = source_config.get('name', 'Chase Card')
    df['Desc'] = df['Description']
    df['OrigCat'] = df.get('Category', '')
    return df[['Date', 'Source', 'Desc', 'OrigCat', 'Amount']]


def ingest_generic_checking(path, source_config):
    """Generic bank checking → uniform schema."""
    df = pd.read_csv(path)

    # Try to detect amount column
    if 'Amount (USD)' in df.columns:
        df['Amount'] = pd.to_numeric(df['Amount (USD)'])
    elif 'Amount' in df.columns:
        df['Amount'] = pd.to_numeric(df['Amount'])
    else:
        raise ValueError(f"No Amount column found in {path}")

    # Date column
    date_col = 'Transaction Date' if 'Transaction Date' in df.columns else 'Date'
    df = df.rename(columns={date_col: 'Date'})

    # Exclude non-lifestyle categories
    exclude = set(source_config.get('exclude_categories', [
        'Credit Card Payments', 'Investment', 'Income', 'Taxes', 'Rental Property'
    ]))
    if 'Category' in df.columns:
        df = df[~df['Category'].isin(exclude)].copy()

    # Keep only outflows; flip sign to positive=outflow
    df = df[df['Amount'] < 0].copy()
    df['Amount'] = -df['Amount']

    df['Source'] = source_config.get('name', 'Checking')
    df['Desc'] = df['Description']
    if 'Category' in df.columns and 'Subcategory' in df.columns:
        df['OrigCat'] = df['Category'].fillna('') + ' / ' + df['Subcategory'].fillna('')
    elif 'Category' in df.columns:
        df['OrigCat'] = df['Category'].fillna('')
    else:
        df['OrigCat'] = ''
    return df[['Date', 'Source', 'Desc', 'OrigCat', 'Amount']]


def ingest_chase_total_checking_pdf(file_spec, source_config, base):
    """Chase Total Checking statement PDFs → uniform schema.

    Chase ships two distinct checking layouts. Total/Premier/Business
    Checking statements use a section-based layout marked with
    '*start*<section>' / '*end*<section>' tags, with no running-balance
    column. Outflow sections we keep: atm debit withdrawal, electronic
    withdrawal, other withdrawals, checks paid section, fees section.
    Inflow ('deposits and additions') is skipped."""
    pdfplumber = _ensure_pdfplumber()
    paths = _resolve_pdf_paths(file_spec, base)

    OUTFLOW_SECTIONS = {
        "atm debit withdrawal",
        "electronic withdrawal",
        "other withdrawals",
        "checks paid section",
        "fees section",
    }
    SECTION_RE = re.compile(r"^\*(start|end)\*([a-z &]+?)\s*$")
    TXN_RE = re.compile(
        r"^(\d{2}/\d{2})\s+(.+?)\s+\$?(-?[\d,]+\.\d{2})\s*$"
    )

    exclude_patterns = source_config.get(
        "exclude_description_patterns", DEFAULT_CHECKING_EXCLUDES)
    exclude_re = re.compile("|".join(exclude_patterns), re.IGNORECASE) if exclude_patterns else None

    rows = []
    calibration_warnings = []
    for path in paths:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)

        end_month, end_year = _parse_period(text)
        if end_year is None:
            end_year = _infer_statement_year(text, path)
            end_month = 12

        section = None
        per_file_count = 0
        per_file_total = 0.0
        per_file_gross = 0.0
        for line in text.splitlines():
            stripped = line.strip()
            sm = SECTION_RE.match(stripped)
            if sm:
                tag, name = sm.groups()
                if tag == "start":
                    section = name
                else:
                    section = None
                continue
            if section not in OUTFLOW_SECTIONS:
                continue
            # Skip section total / header rows
            if stripped.lower().startswith("total"):
                continue
            if stripped.upper().startswith("DATE DESCRIPTION"):
                continue
            mt = TXN_RE.match(stripped)
            if not mt:
                continue
            mmdd, desc, amt = mt.groups()
            try:
                amount = float(amt.replace(",", ""))
            except ValueError:
                continue
            per_file_gross += amount
            if exclude_re and exclude_re.search(desc):
                continue
            # Outflow sections list amounts as positive values
            rows.append({
                "Date": _attach_year(mmdd, end_year, end_month),
                "Desc": desc.strip(),
                "OrigCat": section,
                "Amount": amount,
            })
            per_file_count += 1
            per_file_total += amount
        print(f"  {path.name}: {per_file_count} txns, ${per_file_total:,.2f}")
        summary_total = _extract_checking_summary_outflow(text)
        warn = _calibration_warn(path.name, per_file_gross, summary_total)
        if warn:
            calibration_warnings.append(warn[1])
    if calibration_warnings:
        print("Calibration warnings:")
        for w in calibration_warnings:
            print(w)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Source", "Desc", "OrigCat", "Amount"])
    df["Source"] = source_config.get("name", "Chase Total Checking")
    return df[["Date", "Source", "Desc", "OrigCat", "Amount"]]


INGEST_HANDLERS = {
    'apple_card': ingest_apple_card,
    'chase_card': ingest_chase_card,
    'generic_checking': ingest_generic_checking,
    'chase_card_pdf': ingest_chase_card_pdf,
    'generic_checking_pdf': ingest_generic_checking_pdf,
    'chase_total_checking_pdf': ingest_chase_total_checking_pdf,
}


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

EXCLUSION_KINDS = {
    'card_payoff':         'Card payoff (already counted on the card side)',
    'investment':          'Investment / brokerage transfer',
    'income_tax':          'Income tax payment',
    'internal_transfer':   'Internal transfer between own accounts',
    'rental_operating':    'Rental P&L — operating expense',
    'rental_escrow':       'Rental escrow round-trip (deposits, etc.)',
    'business':            'Business / work-reimbursable expense',
    'family_transfer':     'Family / friend transfer',
    'other':               'Other (uncategorized exclusion)',
}


def apply_exclusions(df, exclusions):
    """Drop rows matching any exclusion rule. Each rule:
        { description: <str>,
          kind: <one of EXCLUSION_KINDS> (optional, defaults 'other'),
          match: { date: [...], description_contains: [...] | str, amount: <float> } }

    Sub-types help the user separate true rental P&L from escrow round-trips
    (deposits returned) from family transfers from card payoffs. All are
    excluded from lifestyle, but the audit trail is clearer.
    """
    excluded_count = 0
    excluded_amount = 0.0
    by_kind = {}  # kind -> (count, amount)
    for rule in exclusions or []:
        match = rule.get('match', {})
        kind = rule.get('kind', 'other')
        mask = pd.Series([True] * len(df), index=df.index)
        if 'date' in match:
            mask &= df['Date'].isin(match['date'])
        if 'description_contains' in match:
            kw = match['description_contains']
            if isinstance(kw, str):
                kw = [kw]
            pattern = '|'.join(re.escape(k) for k in kw)
            mask &= df['Desc'].fillna('').str.contains(pattern, case=False, regex=True)
        if 'amount' in match:
            mask &= df['Amount'].round(2) == round(float(match['amount']), 2)
        if 'source' in match:
            mask &= df['Source'] == match['source']
        n = int(mask.sum())
        if n > 0:
            amt = df.loc[mask, 'Amount'].sum()
            print(f"  Excluding rule '{rule.get('description', '?')}' [{kind}]: {n} rows, ${amt:,.2f}")
            excluded_count += n
            excluded_amount += amt
            prev_n, prev_a = by_kind.get(kind, (0, 0.0))
            by_kind[kind] = (prev_n + n, prev_a + amt)
            df = df[~mask].copy()
    if excluded_count:
        print(f"Total excluded: {excluded_count} rows / ${excluded_amount:,.2f}")
        if by_kind:
            print("By kind:")
            for kind, (n, a) in sorted(by_kind.items(), key=lambda x: -x[1][1]):
                label = EXCLUSION_KINDS.get(kind, kind)
                print(f"  {label}: {n} rows, ${a:,.2f}")
    return df


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------

def load_taxonomy(path):
    """Load a taxonomy YAML file mapping (category, subcategory) -> [keywords]."""
    with open(path) as f:
        return yaml.safe_load(f)


def categorize_row(row, taxonomy, overrides, source_category_maps):
    """Apply categorization rules in order:
       1. User-confirmed (Date, desc, amount) overrides
       2. Source-specific bank category mapping (e.g., Apple Card categories)
       3. Merchant keyword matching from taxonomy
       4. Misc / Unknown
    """
    d = (row['Desc'] or '').lower()
    src = row['Source']
    oc = str(row['OrigCat'] or '')
    amt = round(float(row['Amount']), 2)

    # 1. Overrides
    for ov in overrides or []:
        m = ov.get('match', {})
        if 'date' in m and row['Date'] != m['date']:
            continue
        if 'description_contains' in m:
            kw = m['description_contains']
            if isinstance(kw, str):
                kw = [kw]
            if not any(k.lower() in d for k in kw):
                continue
        if 'amount' in m and round(float(m['amount']), 2) != amt:
            continue
        if 'source' in m and m['source'] != src:
            continue
        return (ov['category'], ov['subcategory'])

    # 2. Source-specific bank-category map (e.g., Apple)
    for src_pattern, cat_map in (source_category_maps or {}).items():
        if src_pattern in src:
            if oc in cat_map:
                return tuple(cat_map[oc])

    # 3. Keyword matching — order matters; first match wins.
    # Matching rules (in order of preference):
    #   a. Explicit regex: "\bword\b" → re.search
    #   b. Trailing space ("ritz "): require word boundary after
    #   c. Else: word-boundary anchored substring match (avoids "rei" hitting
    #      "wineries" while still catching "REI" / "REI #1234")
    for category, subs in taxonomy.items():
        for subcategory, keywords in subs.items():
            for kw in keywords:
                kw_l = kw.lower().strip()
                if not kw_l:
                    continue
                if kw_l.startswith('\\b') and kw_l.endswith('\\b'):
                    if re.search(kw_l, d):
                        return (category, subcategory)
                elif kw.endswith(' '):
                    # Trailing-space keyword: require explicit space or end-of-string
                    if re.search(r'\b' + re.escape(kw_l) + r'(\s|$)', d):
                        return (category, subcategory)
                else:
                    # Word-boundary anchored substring (default)
                    if re.search(r'\b' + re.escape(kw_l) + r'\b', d):
                        return (category, subcategory)

    # 4. Fallback
    return ('Misc', 'Unknown')


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Payment-processor prefix table
#
# Many bank descriptors come wrapped in a short prefix that names the
# payment processor, not the merchant ("Sa*Www.Thepegasu..." = Stripe-
# routed school-tuition payment). Stripping these has three benefits:
#   1. Cluster grouping merges variants of the same merchant.
#   2. Web search returns the merchant, not the processor.
#   3. The Processor column preserves the audit trail.
#
# Maps the prefix (case-insensitive, includes the trailing *) to a
# human-readable processor label. AMBIGUOUS_PREFIXES are stripped for
# grouping but should NOT be auto-searched (could mean different things).
# ---------------------------------------------------------------------------
PROCESSOR_PREFIXES = {
    'sa*':    'Stripe',           # web merchants — note: also some Square variants
    'sp*':    'Stripe',           # Stripe direct
    'bb*':    'BackerKit/Stripe',
    'sq*':    'Square',
    'tst*':   'Toast POS',
    'pp*':    'PayPal',
    'pay*':   'PayPal',
    'sqsp*':  'Squarespace',
    'pyl*':   'PayLeap',
    'act*':   'Active Network',
    'qdi*':   'Quest Diagnostics',
    'ltf*':   'Life Time Fitness',
    'nic*':   'NIC USA (govt services)',
    'tlf*':   'Teleflora',
    'snack*': 'Snackpass',
    'med*':   'Medical billing',
    'lsp*':   'LSP gateway',
    'spo*':   'SpotOn POS',
    'amz*':   'Amazon Marketplace',
    'amzn*':  'Amazon',
    'fsp*':   'Faster Payment Service',
    'par*':   'PaR services',
    'fiv*':   'Five Loyalty',
    'nya*':   'NYA Vending',
    'wf *':   'Worldpay',
    'apl*':   'Apple',
    'itu*':   'Apple iTunes',
    'ggl*':   'Google Pay',
    'etsy*':  'Etsy',
    'eb*':    'eBay',
    'wpy*':   'WePay',
    'patreon*': 'Patreon',
}
# Prefixes whose merchant identity is too noisy to auto-classify; strip for
# grouping but do not feed to web search.
AMBIGUOUS_PREFIXES = {'cpp*', 'ms*'}

_PREFIX_RE = re.compile(
    r'^(' + '|'.join(re.escape(p) for p in
                     list(PROCESSOR_PREFIXES) + list(AMBIGUOUS_PREFIXES)) + r')\s*',
    re.IGNORECASE,
)


def detect_processor(desc):
    """Return the processor label for a description, or '' if no known prefix."""
    if not desc:
        return ''
    m = _PREFIX_RE.match(str(desc))
    if not m:
        return ''
    return PROCESSOR_PREFIXES.get(m.group(1).lower().strip(), '')


def strip_processor_prefix(desc):
    """Strip a known payment-processor prefix from a description."""
    if not desc:
        return desc
    return _PREFIX_RE.sub('', str(desc), count=1).lstrip()


def _misc_stem(desc):
    """Normalize a transaction description into a clusterable merchant stem.
    Strips: payment-processor prefixes (Sa*, Tst*, etc.), Web/PPD ID footers,
    Zelle confirmation codes, long numeric / alphanumeric IDs.
    Keeps the first 4 tokens of what remains."""
    s = strip_processor_prefix(str(desc or '')).lower()
    s = re.sub(r'\bweb id:.*$', '', s)
    s = re.sub(r'\bppd id:.*$', '', s)
    s = re.sub(r'\bjpm[a-z0-9]+\b', '', s)
    s = re.sub(r'\b\d{6,}\b', '', s)
    # Strip mixed letter+digit alphanumeric IDs (e.g. "Jpm99Bp7Bpyl"), but
    # leave pure-letter brand names alone (e.g. "Premiergarage", "Kickresume").
    s = re.sub(r'\b(?=\w*\d)[a-z0-9]{10,}\b', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return ' '.join(s.split()[:4]).strip()


# ---------------------------------------------------------------------------
# Visibility-gap detection (Phase 5 default output)
# ---------------------------------------------------------------------------

# Patterns indicating an outflow to a card whose statements probably aren't in
# scope (auto-pay from checking to a card issuer that isn't represented as a
# source). If we see these AND no source name contains the issuer, warn the
# user that card spending is invisible.
_CARD_PAYOFF_PATTERNS = {
    'amex': r'(american express|amex)\s+(ach|crcardpmt|card pymt|autopay|epayment|epay|gold|platinum|payment)',
    'discover': r'discover\s+(financial|mobile pmt|e-payment|crcardpmt|card pmt|payment)',
    'citi': r'citi\s+(autopay|card online|crcardpmt|card pymt|mobile pmt|payment)',
    'capital_one': r'capital one\s+(mobile pmt|crcardpmt|card pymt|online|payment)',
    'bofa': r'(bank of america|bofa)\s+(online pmt|crcardpmt|card pymt|mobile|payment)',
    'barclays': r'barclay(card)?\s+(us online|crcardpmt|card pymt|mobile|payment)',
    'wells': r'wells fargo\s+(card|crcardpmt|card pymt)',
    'synchrony': r'synchrony\s+(bank crcardpmt|card pymt|mobile)',
}


def detect_loan_drift(all_tx):
    """Find recurring monthly payments whose amounts drift downward over
    >=3 consecutive months. Fixed mortgages don't drift; declining payments
    indicate ARM, HELOC, escrow recalc, or a similar variable-rate product.

    Returns list of (severity, message) tuples."""
    out = []
    df = all_tx.copy()
    df['_dt'] = pd.to_datetime(df['Date'])
    df['_stem'] = df['Desc'].apply(_misc_stem)
    df['_month'] = df['_dt'].dt.to_period('M')
    grouped = df.groupby('_stem')
    for stem, g in grouped:
        if not stem or len(g) < 3:
            continue
        # Need at least 3 distinct months and amount range > $1
        months = g['_month'].nunique()
        if months < 3 or g['Amount'].max() - g['Amount'].min() < 1:
            continue
        # Amount looks loan-shaped: consistent positive outflow above $500,
        # roughly monthly cadence (one txn/month +/- 1)
        if g['Amount'].mean() < 500 or g['Amount'].max() < 1000:
            continue
        # Get amount per month (use mean if multiple)
        per_month = g.groupby('_month')['Amount'].mean().sort_index()
        if len(per_month) < 3:
            continue
        # Check for monotone decline of >= 3 months
        deltas = per_month.diff().dropna()
        decreasing = (deltas <= 0).sum()
        increasing = (deltas > 0).sum()
        if decreasing >= 3 and increasing == 0 and (per_month.iloc[0] - per_month.iloc[-1]) >= 10:
            drop = per_month.iloc[0] - per_month.iloc[-1]
            pct = drop / per_month.iloc[0] * 100
            out.append(('info',
                f"Loan-payment drift: '{stem}' decreased ${per_month.iloc[0]:,.0f} → ${per_month.iloc[-1]:,.0f} "
                f"({-pct:.1f}%) over {len(per_month)} months — likely ARM / HELOC / escrow recalc, not a fixed mortgage."))
    return out


def detect_multiple_loan_streams(all_tx):
    """Detect ≥2 distinct recurring monthly streams that look like mortgage/loan
    payments (≥$1000, monthly cadence, ≥6 occurrences). Surface them so the
    user can attribute each to the right property/loan."""
    out = []
    df = all_tx.copy()
    df['_dt'] = pd.to_datetime(df['Date'])
    df['_stem'] = df['Desc'].apply(_misc_stem)
    df['_month'] = df['_dt'].dt.to_period('M')
    candidates = []
    for stem, g in df.groupby('_stem'):
        if not stem or len(g) < 6:
            continue
        if g['Amount'].mean() < 1000:
            continue
        # Roughly one per month
        months = g['_month'].nunique()
        if months < 6 or len(g) > months * 2:
            continue
        # Description hints at a loan
        kws = ('mortgage', 'mtg pymt', 'loan', 'auto', 'ach pmt', 'lease')
        d = stem.lower()
        if not any(k in d for k in kws) and g['Amount'].mean() < 1500:
            continue
        candidates.append((stem, len(g), g['Amount'].sum(), g['Amount'].mean()))
    if len(candidates) >= 2:
        lines = ', '.join(f"'{s}' (${total:,.0f}/yr, ${avg:,.0f}/mo × {n})"
                          for s, n, total, avg in sorted(candidates, key=lambda x: -x[2]))
        out.append(('info',
            f"Multiple loan-shaped recurring streams detected ({len(candidates)}): {lines}. "
            f"Confirm which property / loan each belongs to."))
    return out


def detect_orphan_airfare(all_tx, lookback_days=5, threshold=500):
    """Find airline charges ≥ $threshold with no other Travel-category charges
    within ±lookback_days. Suggests tickets for a trip not yet taken (or hidden)."""
    out = []
    if 'Category' not in all_tx.columns:
        return out
    df = all_tx.copy()
    df['_dt'] = pd.to_datetime(df['Date'])
    travel = df[df['Category'] == 'Travel']
    # Non-capturing group (?:...) keeps pandas' str.contains quiet — it
    # warns when the compiled regex has match groups it can't expose.
    air_re = re.compile(
        r'(?:airline|airways|air canada|air france|alaska air|american airlines|'
        r'delta air|jetblue|southwest|united airlines|swiss international|'
        r'frontier airlines|spirit airlines|lufthansa|british airways|virgin atlantic|'
        r'klm|qantas|emirates|cathay)', re.IGNORECASE)
    air = travel[travel['Desc'].fillna('').str.contains(air_re)]
    air_big = air[air['Amount'] >= threshold]
    for _, row in air_big.iterrows():
        d = row['_dt']
        nearby = travel[(travel['_dt'] >= d - pd.Timedelta(days=lookback_days)) &
                        (travel['_dt'] <= d + pd.Timedelta(days=lookback_days)) &
                        (travel.index != row.name)]
        # Need at least one non-airline travel charge nearby (hotel, rental, etc.)
        non_air_nearby = nearby[~nearby['Desc'].fillna('').str.contains(air_re)]
        if len(non_air_nearby) == 0:
            out.append(('info',
                f"Orphan airfare: ${row['Amount']:,.2f} {row['Desc'][:40]} on {row['Date']} "
                f"with no surrounding hotel/rental/destination charges — tickets for a future trip "
                f"or someone else's travel?"))
    return out


def detect_visibility_gaps(all_tx, config):
    """Surface gaps in the user's source coverage:
    1. Card auto-pay outflows to issuers NOT in `sources` (missing card source)
    2. No outflows matching brokerage / IRA / 529 keywords (savings invisible)
    3. Total inflows >> total outflows on checking sources (income side off-screen)

    Returns a list of (severity, message) tuples for the wrap-up."""
    gaps = []
    source_names = ' '.join(s.get('name', '').lower() for s in config.get('sources', []))
    descs = all_tx['Desc'].fillna('').str.lower() if 'Desc' in all_tx.columns else all_tx['Description'].fillna('').str.lower()

    for issuer, pat in _CARD_PAYOFF_PATTERNS.items():
        mask = descs.str.contains(pat, regex=True, na=False)
        if mask.sum() == 0:
            continue
        if issuer not in source_names:
            total = all_tx.loc[mask, 'Amount'].sum()
            n = int(mask.sum())
            gaps.append(('warn',
                f"{n} auto-pay rows ({issuer}, ${total:,.0f}/yr) detected, but no {issuer} card source in config — that card's spending is invisible."))

    # 2. Brokerage / savings outflows visibility. Each term gets word boundaries
    # so digit-only terms ("529") don't match transaction IDs like "0305298".
    savings_pat = r'\b(schwab|vanguard|fidelity|wealthfront|betterment|robinhood|brokerage|529|coverdell|scholarshare|nyable|hsa)\b'
    if not descs.str.contains(savings_pat, regex=True, na=False).any():
        gaps.append(('info',
            "No outflows to brokerage / 529 / HSA accounts detected from these sources — savings may be funded from a separate account or via paycheck deduction (not visible from spending alone)."))

    return gaps


def export_misc_clusters(out_df, output_path):
    """Write a misc_clusters.csv next to the output, ranking unique merchant
    stems in the Misc bucket with totals, counts, and sample descriptions.
    Consumed by Claude during the misc-classify step."""
    misc = out_df[out_df['Category'] == 'Misc'].copy()
    if not len(misc):
        return None
    misc['stem'] = misc['Description'].apply(_misc_stem)
    grp = misc.groupby('stem')
    rows = []
    for stem, g in grp:
        samples = list(dict.fromkeys(g['Description'].astype(str).tolist()))[:3]
        rows.append({
            'stem': stem,
            'total': round(g['Amount'].sum(), 2),
            'count': len(g),
            'sample_descriptions': ' || '.join(samples),
        })
    cluster_df = pd.DataFrame(rows).sort_values('total', ascending=False)
    cluster_path = output_path.parent / 'misc_clusters.csv'
    cluster_df.to_csv(cluster_path, index=False)
    return cluster_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', default='Lifestyle Expenses.csv')
    parser.add_argument('--taxonomy', help='Path to taxonomy YAML (default: same dir as config)')
    parser.add_argument('--export-misc', action='store_true',
                        help='Write misc_clusters.csv alongside output for Claude to classify in the cleanup step.')
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    base = config_path.parent
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Load taxonomy
    taxonomy_path = args.taxonomy or config.get('taxonomy_file')
    if not taxonomy_path or taxonomy_path == 'default':
        # Use the bundled default
        skill_dir = Path(__file__).resolve().parent.parent
        taxonomy_path = skill_dir / 'assets' / 'default_taxonomy.yaml'
    taxonomy = load_taxonomy(taxonomy_path)

    # Ingest each source
    frames = []
    for src in config['sources']:
        handler = INGEST_HANDLERS.get(src['type'])
        if not handler:
            print(f"WARNING: unknown source type '{src['type']}', skipping")
            continue
        print(f"Ingesting {src['type']}: {src['file']}")
        if src['type'].endswith('_pdf'):
            # PDF handlers resolve their own paths (file or folder) against base
            df = handler(src['file'], src, base)
        else:
            path = src['file']
            if not os.path.isabs(path):
                path = base / path
            df = handler(path, src)
        print(f"  {len(df)} rows, ${df['Amount'].sum():,.2f}")
        frames.append(df)

    all_tx = pd.concat(frames, ignore_index=True)

    # Apply exclusions
    print("\nApplying exclusions:")
    all_tx = apply_exclusions(all_tx, config.get('exclusions'))

    # Time window filter
    tw = config.get('time_window')
    if tw and tw != 'all':
        all_tx['_dt'] = pd.to_datetime(all_tx['Date'])
        # Accept 'TTM' (legacy) or 'last_12_months' / 'last-12-months' (preferred).
        if tw in ('TTM', 'last_12_months', 'last-12-months', 'L12M'):
            end = pd.Timestamp(config.get('period_end') or pd.Timestamp.today())
            start = end - pd.DateOffset(years=1)
            mask = (all_tx['_dt'] >= start) & (all_tx['_dt'] <= end)
            all_tx = all_tx[mask].copy()
        elif tw == 'YTD':
            end = pd.Timestamp(config.get('period_end') or pd.Timestamp.today())
            start = pd.Timestamp(year=end.year, month=1, day=1)
            mask = (all_tx['_dt'] >= start) & (all_tx['_dt'] <= end)
            all_tx = all_tx[mask].copy()
        all_tx = all_tx.drop(columns=['_dt'])

    # Categorize
    print(f"\nTagging {len(all_tx):,} rows...")
    overrides = config.get('overrides', [])
    source_category_maps = config.get('source_category_maps', {})
    cats = all_tx.apply(
        lambda r: categorize_row(r, taxonomy, overrides, source_category_maps),
        axis=1)
    all_tx['Category'] = [c[0] for c in cats]
    all_tx['Subcategory'] = [c[1] for c in cats]

    # Reorder & rename for output. Tag each row with its payment processor
    # if a known prefix (Sa*, Tst*, Pyl*, etc.) is detected.
    all_tx['Processor'] = all_tx['Desc'].apply(detect_processor)
    out = all_tx.rename(columns={'Desc': 'Description', 'OrigCat': 'Original Category'})
    out = out[['Date', 'Source', 'Description', 'Category', 'Subcategory',
               'Amount', 'Processor', 'Original Category']]

    # Save (preserve previous version for diff if it exists)
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = base / output_path
    prev_path = output_path.with_suffix('.prev.csv')
    if output_path.exists():
        try:
            output_path.replace(prev_path)
        except Exception:
            pass
    out.to_csv(output_path, index=False)
    print(f"\nSaved: {output_path} ({len(out):,} rows)")

    # Refresh delta vs previous run: new rows, removed rows, reclassifications,
    # and category-by-category dollar deltas. Helps users see what changed
    # since the last refresh of the same data.
    if prev_path.exists():
        try:
            prev = pd.read_csv(prev_path)
            # Reclassifications (rows present in both)
            merged = out.merge(prev, on=['Date', 'Source', 'Description', 'Amount'],
                               suffixes=('_new', '_old'), how='inner')
            moved = merged[(merged['Category_new'] != merged['Category_old']) |
                           (merged['Subcategory_new'] != merged['Subcategory_old'])]
            if len(moved):
                print(f"\nReclassified rows: {len(moved)} (top 15 by amount)")
                top = moved.nlargest(15, 'Amount')[
                    ['Date', 'Description', 'Amount',
                     'Category_old', 'Subcategory_old',
                     'Category_new', 'Subcategory_new']]
                print(top.to_string(index=False))

            # New rows (in current but not previous)
            key_cols = ['Date', 'Source', 'Description', 'Amount']
            new_rows = out.merge(prev[key_cols], on=key_cols,
                                 how='left', indicator=True)
            new_only = new_rows[new_rows['_merge'] == 'left_only']
            removed_rows = prev.merge(out[key_cols], on=key_cols,
                                      how='left', indicator=True)
            removed_only = removed_rows[removed_rows['_merge'] == 'left_only']
            if len(new_only) or len(removed_only):
                print(f"\nRefresh delta: +{len(new_only):,} new rows "
                      f"(${new_only['Amount'].sum():,.2f}) "
                      f"-{len(removed_only):,} removed "
                      f"(${removed_only['Amount'].sum():,.2f})")

            # Category-level dollar deltas
            new_by_cat = out.groupby('Category')['Amount'].sum()
            old_by_cat = prev.groupby('Category')['Amount'].sum()
            cat_delta = (new_by_cat.subtract(old_by_cat, fill_value=0)
                                   .round(2)
                                   .sort_values(key=lambda x: x.abs(),
                                                ascending=False))
            material = cat_delta[cat_delta.abs() >= 100]
            if len(material):
                print("\nCategory-level deltas vs previous run:")
                for cat, d in material.head(10).items():
                    arrow = '↑' if d > 0 else '↓'
                    print(f"  {arrow} {cat:30s}  ${d:+,.0f}")
        except Exception:
            pass  # best-effort diff; don't fail the run

    # Visibility gaps + structural anomaly checks (always run)
    gaps = detect_visibility_gaps(all_tx, config)
    if gaps:
        print("\nVisibility gaps:")
        for sev, msg in gaps:
            print(f"  [{sev}] {msg}")

    drifts = detect_loan_drift(all_tx)
    multi = detect_multiple_loan_streams(all_tx)
    orphans = detect_orphan_airfare(all_tx)
    structural = drifts + multi + orphans
    if structural:
        print("\nStructural anomalies (worth surfacing to user):")
        for sev, msg in structural:
            print(f"  [{sev}] {msg}")

    # Summary
    total = out['Amount'].sum()
    print(f"\n{'='*60}\nTOTAL: ${total:,.2f} across {len(out):,} transactions\n{'='*60}")
    by_cat = (out.groupby('Category')['Amount'].agg(['count', 'sum'])
                .rename(columns={'count': 'txns', 'sum': 'total'})
                .sort_values('total', ascending=False))
    by_cat['pct'] = (by_cat['total'] / total * 100).round(1)
    print(by_cat.to_string())

    misc = out[out['Category'] == 'Misc'].sort_values('Amount', ascending=False)
    if len(misc):
        print(f"\nMISC rows for review (top 10 of {len(misc)}):")
        for _, r in misc.head(10).iterrows():
            print(f"  {r['Date']}  ${r['Amount']:>8,.2f}  [{r['Source']:>14}]  {str(r['Description'])[:70]!r}")

    # Export Misc clusters for Claude-driven classification (cleanup phase)
    if args.export_misc and len(misc):
        cluster_path = export_misc_clusters(out, output_path)
        if cluster_path:
            n_stems = sum(1 for _ in open(cluster_path)) - 1
            print(f"\n  Misc clusters: {cluster_path} ({n_stems} unique stems, ${misc['Amount'].sum():,.0f})")
            print(f"  Next: have Claude read this file and append overrides to your config (see references/misc_classify.md).")

    # Write decisions audit log
    by_cat_pct_list = [(c, by_cat.loc[c, 'pct']) for c in by_cat.index]
    write_decisions_log(config, output_path, total, by_cat_pct_list)


def write_decisions_log(config, output_path, total, by_cat_pct):
    """Write a human-readable DECISIONS.md next to the output CSV.
    Captures every exclusion + override the config encodes, with the
    rationale string the user gave when adding it. This becomes the audit
    trail next session — read this file before re-asking the user."""
    log_path = output_path.parent / "DECISIONS.md"
    lines = ["# Categorization decisions",
             "",
             f"Auto-generated by `consolidate.py` on {datetime.now():%Y-%m-%d}.",
             "Read this on a return visit before re-asking the user — every rule here was confirmed by them.",
             ""]

    excl = config.get('exclusions') or []
    if excl:
        lines += ["## Exclusions (rows dropped from lifestyle)", ""]
        for rule in excl:
            lines.append(f"- **{rule.get('description', '?')}** — match: `{rule.get('match', {})}`")
        lines.append("")

    overrides = config.get('overrides') or []
    if overrides:
        lines += ["## Overrides (rows recategorized)", ""]
        for rule in overrides:
            cat = rule.get('category', '?')
            sub = rule.get('subcategory', '?')
            lines.append(f"- **{rule.get('description', '?')}** → {cat} / {sub}")
        lines.append("")

    lines += ["## Last consolidation run", "",
              f"- Total: ${total:,.0f}",
              f"- Top categories: " + ", ".join(f"{c} {p:.0f}%" for c, p in by_cat_pct[:5]),
              ""]
    log_path.write_text("\n".join(lines))
    print(f"  Decisions log: {log_path}")


if __name__ == '__main__':
    main()
