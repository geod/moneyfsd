# Consolidate

Per-source ingestion patterns. Each source type below has its own quirks; document them once and reuse via `scripts/consolidate.py`.

## Output schema (uniform across sources)

After ingestion, every row has:

| Column | Type | Note |
|---|---|---|
| Date | str (MM/DD/YYYY) | Or normalize to ISO if you prefer |
| Source | str | e.g., "Alex AmEx", "Partner Chase", "Joint Checking" |
| Desc | str | Merchant name or transaction description |
| OrigCat | str | Bank's original category (audit field; may be blank) |
| Amount | float | **Positive = outflow.** Refunds/credits = negative. |

## Apple Card

Apple's CSV export has a `Type` column that's the most important signal. Values seen in the wild:

| Type | Meaning | Include? |
|---|---|---|
| Purchase | Normal charge | **Yes** |
| Credit | Merchant return / dispute credit / statement credit / travel credit | **Yes** (will be negative amount) |
| Debit | Dispute reversal — the dispute was denied | **Yes** (positive, offsets the prior Credit) |
| Other | Misc charges (some Apple Store entries) | **Yes** |
| Payment | Card payoff from checking | **No** — would double-count |
| Installment | Monthly slice of an installment plan | **No** — original purchase already counted |

Also drop **"DAILY CASH ADJUSTMENT"** rows — these reverse Apple's cashback when a purchase is refunded; affects Daily Cash balance, not expenses.

Cardholder attribution: the `Purchased By` column. Map names to your `Source` convention.

```python
apple = pd.read_csv(...)
apple = apple.rename(columns={'Transaction Date':'Date','Amount (USD)':'Amount'})
apple = apple[apple['Type'].isin(['Purchase','Credit','Debit','Other'])]
apple = apple[~apple['Description'].fillna('').str.contains('DAILY CASH ADJUSTMENT', case=False)]
apple['Source'] = apple['Purchased By'].map(cardholder_map).fillna('Apple Card')
apple['Desc'] = apple['Merchant'].fillna(apple['Description'])
apple['OrigCat'] = apple['Category']
```

Apple's `Category` column is **surprisingly useful** for tagging (Restaurants, Grocery, Gas, Airlines, Hotels, etc.) — preserve it as `OrigCat` and let the taxonomy mapper trust it where reasonable.

## Chase credit cards (Sapphire, Freedom, etc.)

Chase's export `Type` column:

| Type | Meaning | Include? |
|---|---|---|
| Sale | Purchase | **Yes** |
| Fee | Annual fee, late fee, foreign txn fee | **Yes** |
| Credit | Statement credit, travel credit | **Yes** (negative) |
| Payment, "AUTOMATIC PAYMENT - THANK YOU" | Card payoff | **No** |
| Payment, *anything else* with negative amount | Merchant refund miscategorized as Payment by the parser | **Yes** (rare but happens — PayPal refunds, etc.) |
| Return | Merchant return | **Yes** (negative) |

The trick is distinguishing the two `Payment` cases. Use the description:

```python
chase = pd.read_csv(...)
payoff = chase['Description'].fillna('').str.contains('AUTOMATIC PAYMENT - THANK YOU', case=False)
chase = chase[
    chase['Type'].isin(['Sale','Purchase','Fee','Credit','Return'])
    | ((chase['Type']=='Payment') & ~payoff)
]
chase['Source'] = config['source_name']  # e.g., 'Alex ChaseCard'
chase['Desc'] = chase['Description']
chase['OrigCat'] = chase['Category']
```

If the rental property has its insurance (Lemonade, etc.) on the Chase card, exclude those rows here.

## Generic bank checking (Chase, BofA, Wells Fargo, …)

Most bank checking exports use:

- Negative `Amount` = outflow (debit)
- Positive `Amount` = inflow (deposit, refund)

Keep only outflows for lifestyle, then **flip the sign** so positive = outflow (matches the card convention).

The big risk is double-counting card payoffs: if you've already counted the card transactions, you don't want to re-count "Chase Sapphire ePay" in checking. The user's checking export probably has a `Category` like "Credit Card Payments" — exclude that category.

Common categories to exclude from a checking source (varies by bank):

- Credit Card Payments
- Investment / Brokerage Transfers
- Income
- Taxes
- Rental Property (if the user has one)

```python
NON_LIFESTYLE = {'Credit Card Payments','Investment','Income','Taxes','Rental Property'}
chk = pd.read_csv(...)
chk['Amount'] = pd.to_numeric(chk['Amount (USD)'])
chk = chk[~chk['Category'].isin(NON_LIFESTYLE)]
chk = chk[chk['Amount'] < 0]
chk['Amount'] = -chk['Amount']
chk['Source'] = config['source_name']
chk['Desc'] = chk['Description']
chk['OrigCat'] = chk['Category'] + ' / ' + chk['Subcategory'].fillna('')
```

If the user's checking has subcategories (e.g., Mint-style "Restaurants & Bars"), preserve them — they often beat keyword matching.

## Capital One, Amex, Discover, etc.

These follow the same pattern as Chase but with different column names. Read the file once (`pd.read_csv(...).head()`), identify the date / amount / description / category columns, and add a new `type:` to `consolidate.py`.

The signals to look for:

- A type/transaction-class column that distinguishes purchases from payments
- A date column (often "Transaction Date" or "Posted Date" — prefer Transaction)
- An amount column (check sign convention)
- A merchant or description column
- Optionally: a category column from the bank
- Optionally: a cardholder column (joint cards)

## PDF statements

PDFs are common — many users don't have CSV exports, especially for older months or banks where CSV download is buried. The skill handles them via `pdfplumber` (auto-installed on first PDF source).

**Configuring a PDF source.** Point `file:` at either a single PDF or a folder of PDFs (one statement per file is typical). Use the `_pdf` variant of the source type:

```yaml
sources:
  - name: Alex ChaseCard
    file: alex-chase/        # folder of monthly statement PDFs
    type: chase_card_pdf
    cardholder: Alex
  - name: Joint Checking
    file: joint-checking/
    type: generic_checking_pdf
```

Available PDF handlers in `consolidate.py`:

- `chase_card_pdf` — Chase credit-card statements (Sapphire, Freedom, etc.). Matches every `MM/DD <desc> <amount>` line in the statement; positive = purchase/fee, negative = credit/refund. Excludes "PAYMENT THANK YOU" rows by default (configurable via `exclude_description_patterns`).
- `generic_checking_pdf` — Chase **Sapphire Checking** style statements where each transaction line has the form `MM/DD <desc> <amount> <running_balance>`. Negative amounts are outflows. Default exclusions cover credit-card payoffs (Apple Card, Chase, Amex, Citi, Cap One, Discover), brokerage funding, 529 contributions, and tax payments.
- `chase_total_checking_pdf` — Chase **Total Checking / Premier / Business Checking** style. These statements use a section-based layout (`*start*deposits and additions`, `*start*atm debit withdrawal`, `*start*electronic withdrawal`, etc.) with amounts as positive numbers within each outflow section. **No running-balance column.** Use this handler when `generic_checking_pdf` returns "0 txns, $0.00" across multiple statements.

> **How to pick a checking handler:** dump the first 2k chars of a sample PDF. If you see lines like `06/02 Foo Web ID: 12345 -1,492.98 60,783.00` (two amounts per line) → `generic_checking_pdf`. If you see `*start*deposits and additions` followed by `DATE DESCRIPTION AMOUNT` and rows like `06/02 Foo $1,492.98` (single amount) → `chase_total_checking_pdf`.

**PDF parser robustness.** The script handles a known Chase quirk where `*end*<section>` markers occasionally fuse into the following transaction line and consume the leading digit of the date (e.g., `*end*transac0tion detail6/04 Rocket Mortgage ...`). The `_recover_marker_bleed` helper recovers these by finding the embedded MM/DD prefix and rebuilding a clean line.

**Calibration is automatic.** After parsing each PDF, the script extracts the summary box from page 1 (e.g., `ATM & Debit Card Withdrawals -X` + `Electronic Withdrawals -X` + `Fees -X`) and compares it to the sum of parsed outflows. Drift > 5% with a > $100 absolute diff fires a warning. Card statements include exclusions (PAYMENT THANK YOU rows) so calibration uses the pre-exclusion gross. Use these warnings to catch parser misses early — investigate any flagged statement before trusting downstream analysis.

**Year inference.** Statement PDFs only show MM/DD on transaction lines. The handler reads the **statement period** from the header to assign the year, and handles year-end wrap (Dec rows in a Dec 15 → Jan 14 statement get the prior year). If a statement has no detectable period header, the handler falls back to the file's mtime year and warns.

**Calibration is mandatory.** PDF text extraction is brittle. After ingestion, the script prints per-file row counts and totals. **Compare against the statement summary printed on the PDF's first page** before trusting downstream analysis. Common failure modes:

- Multi-line descriptions split into ghost rows
- Amount columns wrapping to the next line
- Footers ("Page X of Y, continued on next page") accidentally matching the line regex
- Foreign-currency rows with two amounts (FX + USD) — handler keeps only USD

If totals diverge by more than a few percent from the printed statement summary, ask the user to grab a CSV for that account instead. Don't try to debug a regex on a one-off statement format.

**Other banks.** For PDF formats not covered (Amex statements, Capital One statements, Citi, etc.), add a new handler in `consolidate.py` modeled on `chase_card_pdf`. The pattern is:

1. Extract full text per page with `pdfplumber`
2. Find a section header that delimits transactions
3. Apply a line regex like `^(\d{2}/\d{2})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})\s*$` — most US banks use this layout
4. Resolve the year from the statement period header

Document each new handler in this file with a one-line note on what it expects.

**Mixed sources are fine.** A single config can have CSV sources for some accounts and PDF sources for others — the consolidation step concats them after each is normalized to the uniform schema.

## Combining sources

Once each source is normalized to the uniform schema, simply:

```python
all_tx = pd.concat([apple, chase, chk, ...], ignore_index=True)
all_tx['desc_l'] = all_tx['Desc'].fillna('').str.lower()  # for keyword matching
```

Now you're ready to tag (Phase 3).

## Reporting

Always print a per-source summary after consolidation:

```
TOTAL LIFESTYLE EXPENSES: $568,432 across 2,719 transactions
  Alex AmEx       :  1,430 txns  $312,447
  Partner AmEx    :    287 txns   $64,103
  Alex ChaseCard  :    412 txns   $89,221
  Joint Checking  :    590 txns  $102,661
```

And a **one-line "what was excluded" report**:

```
Excluded: 142 card-payoff rows ($245,300), 23 investment transfers ($120,000),
12 tax payments ($89,400), 4 work-trip rows ($681), 8 rental-property rows ($14,200)
```

This builds trust with the user — they see what you took out and can challenge any of it.
