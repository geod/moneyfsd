# Ingest

Phase 2: parse each input file, extract positions, validate against statement totals.

This phase is **mechanical**. It does not interpret, classify, or judge — it just extracts what the source says, normalizes the schema, and reconciles. Interpretation happens in `consolidate.md` and `classify.md`.

## Input formats

In priority order — CSV / Excel / spreadsheet are cleaner, PDFs are the fallback.

| Format | When | Tool | Notes |
|---|---|---|---|
| CSV export | User downloaded transactions/positions from custodian portal | `pandas` | Cleanest; tickers + values + cost basis usually present |
| Excel / `.xlsx` | Same as CSV; sometimes the user maintains a balance sheet here | `pandas` + `openpyxl` | Multi-sheet workbooks: read each tab |
| PDF statement | Most retirement/pension/NQDC statements only come as PDF | `pdfplumber` | Auto-install on first encounter (`pip install pdfplumber`) |
| User spreadsheet | Hand-maintained tracker with account-level totals | `pandas` (CSV/Excel) | Treated as a parallel reference for cross-checking, not as a position source |
| Image / screenshot | Last resort | Manual transcription via dialog | Rare; only when no other source exists |

## Custodian / statement-type recognition

After the user drops a folder, inventory it. For each file:

1. Extract first page (PDF) or first 50 rows (CSV/Excel) for fingerprinting.
2. Match against custodian signatures (header text, logo references, account-number formats, footer text).
3. Match against statement-type signatures (account summary structure, position table layout).

Common custodian fingerprints (these are public brokerage platforms, not PII):

| Custodian | Header text signal | Common statement types |
|---|---|---|
| Charles Schwab | "Charles Schwab & Co., Inc. Member SIPC", "schwab.com" | Brokerage, IRA, PCRA, 529 |
| Schwab Trust Bank (TTEE) | "Charles Schwab Trust Bank TTEE" | Qualified plan PCRA sleeve (trustee) |
| Schwab Trust Bank (CUST) | "Charles Schwab Trust Bank CUST" | NQDC PCRA sleeve (custodian) |
| Fidelity | "Fidelity Investments", "fidelity.com" | Brokerage, IRA, 401(k), HSA |
| Vanguard | "The Vanguard Group", "vanguard.com" | Brokerage, IRA, 401(k) |
| E*Trade / Morgan Stanley | "E*TRADE Securities" or "Morgan Stanley" | Brokerage, IRA |
| TIAA | "TIAA-CREF" | 403(b), pension, annuity |
| Empower / Voya / Principal | varies | Plan-recordkeeper statements |

For statement type, look at structural cues:

| Type | Structural signal |
|---|---|
| Taxable brokerage | "Federal Tax Status: Tax-Exempt / Taxable" column; cost basis shown per lot |
| Qualified 401(k) | "401(k) Savings and Retirement Plan", contribution summary, employer-match line |
| NQDC | "Deferred Compensation Plan", "Executive Deferred Comp", trustee CUST relationship |
| Roth IRA | "Roth IRA" in header; contribution limit references |
| Pension (DB) | Lump-sum value with no underlying position detail; sometimes annuity estimate |
| HSA | "Health Savings Account", contribution-limit references, investment threshold |
| 529 | "529 College Savings Plan", beneficiary line, state-plan name |

When a statement matches a known custodian but the type is ambiguous, default to "brokerage" and surface for confirmation.

## Common statement structures

### Pattern A: Taxable brokerage

Typical layout (Schwab-style, generalizable):

```
Page 1: Account Summary
  - Beginning value
  - Activity rollup (deposits, withdrawals, dividends, market appreciation)
  - Ending value
  - Federal tax status indicator

Page 2: Asset Allocation & Income Summary
  - High-level pie (cash, equities, ETFs, MFs, other)
  - Top holdings (top 5 lines)
  - Gain/Loss summary

Pages 3+: Positions Detail
  - "Cash and Cash Investments" section
  - "Positions - Equities" — line per ticker: qty, price, MV, cost basis, gain
  - "Positions - Mutual Funds"
  - "Positions - Exchange Traded Funds"
  - "Positions - Other Assets" (REITs, MLPs, etc.)

Pages after: Transactions Detail
  - Per-date trade and income activity
```

Extract: every line under "Positions - *" sections, plus the cash row. Reconcile sum against the Page 1 ending value.

### Pattern B: Qualified retirement plan with nested PCRA

Most NQDC and qualified plans with a "self-directed brokerage window" produce TWO statements per quarter:

1. **The parent plan statement** — shows balances in core fund options PLUS a single line for "Self-Directed Brokerage Acct: $X" with no underlying detail.
2. **The PCRA statement** — a separate Schwab brokerage statement covering the self-directed sleeve, with full line-item detail.

The PCRA statement's ending value should EXACTLY MATCH the single-line entry on the parent plan statement. This match is how you confirm the nesting relationship.

**Critical: do not sum both.** If you treat the PCRA statement as a separate account *and* leave its value in the parent, you'll double-count by hundreds of thousands of dollars.

Detection rule:
1. Read the parent plan statement. Find the single line referencing "self-directed brokerage" / "PCRA" / "BrokerageLink" / similar, with its dollar amount.
2. Look for another statement in the folder whose grand total matches that dollar amount.
3. If found → mark the second statement as `nested_inside` the first. Its positions become the line-item detail for that parent line; the parent line's dollar amount is replaced by the sum of child positions in the consolidated ledger.

Same pattern applies to qualified plan PCRA (trustee model) and NQDC PCRA (custodian model — see "trustee vs custodian distinction" below).

### Pattern C: NQDC vs qualified plan — trustee vs custodian distinction

For statements from "Schwab Trust Bank" (or equivalent), the suffix matters:

- **TTEE (Trustee)** — qualified plan structure. The trust holds the assets for the participant's benefit. Tax treatment: tax-deferred, can be rolled over.
- **CUST (Custodian)** — NQDC structure. The assets are book-entry holdings of the employer, with the custodian tracking. Tax treatment: tax-deferred at deferral, ordinary income at distribution per the user's elected schedule, no rollover.

Both produce similar-looking PCRA statements. The wrapper type is what differs. Detect from the header text and set `type: qualified_401k` (nested or parent) vs `type: nqdc`.

### Pattern D: Pension statement

Often just a single value — no underlying positions. Two flavors:

- **Defined benefit (DB)** — promises a future income stream. The "value" is sometimes the lump-sum equivalent ("commuted value"); sometimes just an annuity estimate; sometimes both.
- **Cash balance** — has an account balance that grows at a stated rate. Looks more like a 401(k) but isn't directly investable.

For both, model as a single position with `type: pension_db` or `type: pension_cb`, classify as `us_bonds` for asset-allocation purposes (DB pensions are bond-like income streams), and surface `vested: true/false` and `vest_date` if the statement provides them.

### Pattern E: HSA statement

Two parts:

1. **Cash balance** — the "spending portion" held in cash sweep, usable for medical expenses.
2. **Invested balance** (if above the custodian's investment threshold) — held in an investment sub-account, often with limited fund choices.

Some HSAs are 100% cash sweep (the user hasn't crossed the investment threshold or hasn't opted in). The default assumption should be cash sweep unless the statement shows otherwise. Surface for user confirmation.

### Pattern F: 529 plan statement

Similar to a target-date fund — usually a single age-based portfolio with an underlying mix. Extract the named portfolio and use `classify.md`'s through-the-fund logic.

529s are typically **excluded from net worth** in this skill's analysis (the user's spreadsheet had this flag and it's a reasonable default). Track them as a separate `account_type: 529`, but don't roll up into total investable.

### Pattern G: Held-direct crypto

Crypto is usually NOT delivered as a statement; the user enters it manually or provides an exchange CSV. Schema:

```yaml
manual_holdings:
  - account: crypto_holdings
    type: crypto
    owner: primary
    assets:
      - { ticker: BTC, quantity: 1.5, value: 100000 }
      - { ticker: ETH, quantity: 25, value: 80000 }
```

For asset-allocation purposes, each crypto holding gets its own asset class (`crypto_btc`, `crypto_eth`, etc., or a generic `crypto_other`). Don't treat as equity, don't treat as alts — give it its own bucket.

### Pattern H: User-maintained balance-sheet spreadsheet

When the user provides a consolidated spreadsheet (often Google Sheets exported as CSV, or a `.xlsx`), it typically has columns like:

```
Category | Account | Market Value | Mortgage | Net Asset | Liability | Net Equity | Vested | Liquid | Notes
```

Or similar. Treat this as **a parallel reference**, not a position source:

- Use its **account-level totals** to reconcile against the statement-extracted totals. Mismatches indicate one is stale (usually the spreadsheet is more current than the quarterly statements).
- Use its **non-statement entries** (cars, crypto, manual holdings) to populate `manual_holdings` in config.
- Use its **annotations** (FOLLOW_UP markers, custom notes) to seed the anomalies list.
- Use its **methodology choices** (40% tax haircut on NQDC, carrying value on RE) as defaults in config.

The spreadsheet's *line-item composition* (which fund is in which account at which value) is almost always less granular than the statements, so don't use it for position detail.

## Validation: per-statement reconciliation

Every parsed statement MUST reconcile to within rounding error. Run this check before moving to consolidate:

```python
for stmt in parsed_statements:
    extracted_total = sum(p.market_value for p in stmt.positions)
    stated_total = stmt.summary.ending_value
    diff = abs(extracted_total - stated_total)
    pct_diff = diff / stated_total if stated_total else 0
    
    if diff > 1.00 and pct_diff > 0.001:  # >$1 AND >0.1%
        emit_warning(stmt.filename, extracted_total, stated_total, diff)
```

Tolerance: $1 absolute *and* 0.1% relative — both must be exceeded to flag. Statements rarely round to the penny, but they rarely lie by more than that.

**On reconciliation failure**, do not silently proceed. Surface to the user:

> "Reconciliation issue on [filename]: extracted sum is $X, statement total is $Y, off by $Z. Likely missed a position section or an unparsed cash line. Want me to dump the parsed positions for a manual check, or proceed with the discrepancy noted?"

Common reconciliation failures and causes:

- **Off by exactly one position's value** — a section was skipped (e.g., "Other Assets" treated as boilerplate)
- **Off by accrued interest / pending dividends** — usually shown in the summary but not in positions table; treat as a known small delta, document it
- **Off by margin / debit balance** — debit positions sometimes carry a negative value; extraction needs to preserve sign
- **Off by fractional shares** — DRIP residue, often shown to 4 decimal places that round-trip wrong if quantity is truncated

## Output schema: `raw_positions.csv`

One row per extracted line. Columns:

```
source_file          # e.g., "schwab_brokerage_2026Q1.pdf"
custodian            # e.g., "schwab"
statement_type       # e.g., "taxable_brokerage", "qualified_401k", "nqdc"
statement_date       # ISO date — period end of the statement
account_number       # masked if present (e.g., "****-*149")
account_name         # nickname / label from the statement
section              # "cash", "equities", "etfs", "mutual_funds", "other"
ticker               # primary identifier; CUSIP if no ticker
description          # security name from the statement
quantity             # shares or units (blank for cash)
price                # per-share price (blank for cash)
market_value         # $ value
cost_basis           # if statement provides
unrealized_gain      # if statement provides
est_annual_income    # if statement provides (estimated dividends/interest)
est_yield            # if statement provides
reconciled           # True / False / "partial:$X off"
```

This file is intermediate — the consolidate phase rewrites it into the final `positions.csv`.

## Common failure modes (and what to do)

**1. PDF text extraction loses table structure.** `pdfplumber` is generally good but some statements use weird layouts. Fallback: extract `extract_words()` with bounding-box coords and reconstruct rows by Y-coordinate clustering.

**2. The statement is image-based (no extractable text).** Some scanned-and-re-PDFed statements are essentially just images. Options:
   - Try `pdf2image` + Tesseract OCR. Slow and error-prone.
   - Ask the user for a CSV export from the custodian portal.
   - If neither works, ask for manual entry of the position-level data.

**3. The statement is from a recordkeeper you don't recognize.** Empower, Voya, ADP Retirement, Principal, etc. — many flavors of 401(k) recordkeeper statements exist. Don't try to handle each one with a custom parser. Instead, treat the file as "unknown format," do a best-effort text extraction, surface the positions you found, and ask the user to confirm. The skill should improve over time as users encounter new formats and the patterns get added here.

**4. A position has a quantity but no value.** Some statements (especially trust pension statements) show units of a non-tradable interest. Treat the value as 0 with a note; surface to user for manual entry.

**5. The statement's "total" is itself wrong.** Rare, but it happens at quarter boundaries when a transaction posts after the summary is computed. If the per-position sum is clean and reasonable but the stated total is off, document it and trust the per-position sum.

**6. Two statements have overlapping date ranges.** When ingesting multiple quarters, use only the most recent statement per account. If the user wants a time-series view, that's a separate analysis (defer to a downstream skill).

## Auto-install / dependency management

Detect missing libraries and auto-install on first need:

```python
try:
    import pdfplumber
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pdfplumber", "-q"])
    import pdfplumber
```

Required for this phase:
- `pandas` (almost certainly present)
- `pdfplumber` (PDF extraction)
- `openpyxl` (Excel files)

Optional / auto-installed only when needed:
- `pdf2image` + `pytesseract` (OCR fallback) — heavy dependency, only install if explicitly requested.

## What this phase does NOT do

- It does not classify holdings into asset classes (that's `classify.md`).
- It does not infer account types from anything other than file structure (that's `consolidate.md`).
- It does not run any analysis or commentary.
- It does not deduplicate nested wrappers (detection only — actual dedup happens in `consolidate.md` once all statements are parsed).
- It does not write any output other than `raw_positions.csv` and reconciliation warnings.
