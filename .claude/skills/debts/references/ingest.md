# Ingest (Phase 2)

Per-format extraction patterns. Each section maps a statement type to the regex / structural cues used by `scripts/extract_loans.py` to pull the canonical fields.

**Reconciliation invariant:** for each parsed statement, the extracted balance must match the statement's own "Current Balance" / "Outstanding Principal" line within $1. Off-by-cents is fine; off-by-anything-else means a parse error to surface in Stage 3.

---

## Common output schema

Every parser produces rows with these columns:

| Column | Source |
|---|---|
| source_file | Filename |
| loan_type | Inferred from header (one of `loan_type_taxonomy.yaml` types) |
| lender | From statement header |
| statement_date | Statement period end |
| balance | Outstanding principal |
| original_amount | If disclosed |
| rate | APR |
| rate_type | fixed / variable / promo |
| reset_date | For ARMs / promos |
| term_months_remaining | Computed from maturity date − statement date |
| scheduled_payment | Monthly P&I (excludes escrow) |
| min_payment | For revolving accounts only |
| ytd_interest_paid | If disclosed (relevant for tax docs) |
| borrower | Primary borrower from header |
| co_borrower | If present |

---

## Mortgage statements (CFPB-standardized)

Regulation Z requires a standardized billing statement format for closed-end mortgages. Look for these landmarks:

- **Header:** "Mortgage Statement" or "Periodic Statement"
- **Account Summary box** with labeled fields:
  - "Principal Balance" → `balance`
  - "Interest Rate" → `rate`
  - "Maturity Date" → used to compute `term_months_remaining`
- **Explanation of Amount Due section:**
  - "Principal" + "Interest" → sum is `scheduled_payment`
  - "Escrow" → excluded from `scheduled_payment` but captured separately as `escrow_payment`
- **Year-to-Date totals box:**
  - "Interest Paid Year to Date" → `ytd_interest_paid`

**ARM-specific markers:**
- "Adjustable Rate" or "ARM" in the loan-info section
- "Next Adjustment Date" → `reset_date`, `rate_type: variable`
- If absent, default `rate_type: fixed`

**Common quirks:**
- Wells Fargo statements bury the principal balance in a side panel labeled "Loan Information" rather than in the main Account Summary
- Rocket / Quicken statements put the rate in a different box than the maturity date
- Some servicers report YTD interest in a separate "Tax Document Summary" rather than the main statement

---

## HELOC statements

Similar to mortgage but with phase-aware fields:

- **Phase indicator:** "Draw Period" vs "Repayment Period" — drives `status` (revolving vs amortizing)
- During draw: `min_payment` = interest-only payment
- Rate is almost always variable; look for "Prime + X%" or "Variable APR"
- `secured_by: primary_residence` by default

---

## Auto loan statements

- **Header:** "Auto Loan" or "Vehicle Financing"
- **VIN or vehicle description** → `secured_by` alias (e.g., "vehicle_civic")
- "Payoff Amount" vs "Principal Balance": use **principal balance** for the ledger; payoff amount includes per-diem interest and isn't a stable comparable

---

## Federal student loans

The five major federal servicers (MOHELA, Nelnet, EdFinancial, ECSI, Aidvantage) have similar but not identical formats. Common fields:

- **Current Balance** → `balance`
- **Interest Rate** → `rate` (fixed for federal loans)
- **Repayment Plan** → captured in notes (Standard, Graduated, Income-Driven, Forbearance)
- **Loan Group ID** → use as `loan_id` to dedupe across servicer transfers

**Quirks:**
- Income-driven repayment plans may show $0 monthly payment with interest accruing — flag in notes
- Administrative forbearance (e.g., COVID-era pause) may show 0% interest accrual — capture with notes
- A single borrower may have multiple loan groups; treat each as a separate ledger row

---

## Credit card billing statements (TILA-mandated)

The CARD Act mandates a standardized "Account Summary" box. Look for:

- **Statement Balance** → `balance` (this is the prior cycle's ending balance; use as the current balance)
- **Minimum Payment Due** → `min_payment`
- **Annual Percentage Rate (APR)** → `rate`, almost always variable
- **Interest Charge Calculation** section confirms variable nature

**Important behavior:**
- If the user paid the statement in full after the statement date, balance ≠ revolving debt. The Stage 3 question disambiguates: revolving=true keeps it; revolving=false marks as `paid_in_full` and excludes from headline debt.
- Promotional rates (0% balance transfers) often shown in a separate APR breakdown box — capture `promo_end_date`

---

## Personal loans / BNPL / fintech installment

Highly varied formats. Strategy:

- Try regex against headers (Affirm, Klarna, Afterpay, SoFi, LendingClub, Marcus, Upstart, etc.)
- Fall back to "manual entry" prompt: ask the user for balance + rate + term + payment

---

## Output

Write `<work_folder>/.analysis/raw_loans.csv` (one row per parsed statement) and `<work_folder>/.analysis/statements_meta.json` (one entry per file with reconciliation status).

If reconciliation fails for a statement, set `reconciled: false` and include a `reconciliation_note` — Stage 3 will surface for user resolution.
