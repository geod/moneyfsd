# Classify (Phase 4)

Take consolidated loans → map each to `status`, `tax_treatment`, `secured_by`. Mechanical.

## Status

| Status | Applies to |
|---|---|
| `revolving` | Credit cards with non-zero balance + `revolving: true`. HELOCs in draw period. |
| `amortizing` | Mortgages, auto, student, personal, BNPL, medical, tax, 401(k) loans, HELOCs in repayment. |
| `interest_only` | Some HELOCs in draw period explicitly marked interest-only. |
| `paid_in_full` | Credit cards with `revolving: false` (statement balance but paid off by user). |
| `informal` | Family loans. Excluded from weighted-avg-rate and payoff-timeline analyses. |

Default by type lives in `references/data/loan_type_taxonomy.yaml`.

## Tax treatment

Apply IRS rules current as of the statement year:

### Deductible (interest fully deductible up to limits)
- **Primary-residence mortgage** — up to $750k principal (post-2017 TCJA limit; $1M for loans originated before Dec 16, 2017)
- **HELOC used for home improvement** — interest deductible (subject to the same $750k combined cap with primary mortgage)
- **Federal and private student loan interest** — up to $2,500/year, phased out above MAGI thresholds (the classify step doesn't know MAGI; tag as `deductible` and let the planning layer apply phase-out)

### Partially deductible
- **Mortgage principal above the $750k cap** — interest on the portion above the limit is not deductible
- **HELOC with mixed use** (some home-improvement, some other) — pro-rated

### Non-deductible
- Auto loans
- Credit card balances
- Personal loans
- 401(k) loans (paid back with after-tax dollars)
- BNPL
- Medical debt
- Tax debt
- Family / informal loans

## Secured by

Inference rules (in order):

1. **Explicit config field** `secured_by` → use as-is
2. **By loan type:**
   - `mortgage` → `primary_residence`
   - `heloc` → `primary_residence`
   - `auto` → `vehicle_<alias>` (use VIN-derived alias or user-provided name)
   - `401k_loan` → `retirement_balance`
3. **Otherwise** → null (unsecured)

## Edge cases — surface for one-shot review

After applying mechanical rules, surface a one-shot review list to the user for genuinely ambiguous cases:

- HELOCs without an explicit `use` flag → ask "home improvement, mixed, or other?" Affects deductibility.
- Mortgages on secondary properties → ask "primary residence, investment, or vacation?" Affects deductibility class.
- Loans with `lender` matching the user's stated employer → ask "401(k) loan or personal loan?" (Sometimes employers offer employee personal loans.)

Apply defaults silently for the rest.

## Output

`<work_folder>/.analysis/loans_classified.csv` — adds `status`, `tax_treatment`, `secured_by` columns to the consolidated ledger.
