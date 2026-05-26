# Report (Phase 5)

Artifacts produced from the classified ledger. **Descriptive only** — never recommend refinance, payoff order, or strategy.

## Artifact set

### A. Totals (embedded in main report)
- **Total debt** — sum of balance across all rows with status ∈ {revolving, amortizing, interest_only}; `paid_in_full` and `informal` excluded from headline
- **By type** — table breaking down balance by loan type
- **By owner** — table breaking down by primary / spouse / joint
- **By tax treatment** — deductible / partially_deductible / non_deductible split
- **By secured-vs-unsecured** — secured loans vs unsecured loans

### B. Rate Exposure (`RateExposure.md`)
- **Weighted-average APR** across all formal debt (informal excluded)
- **Variable-rate exposure** — $ and % of total in variable / promo rates
- **Rate-band distribution** — using bands from `thresholds.yaml` (e.g., <5%, 5–7%, 7–10%, 10–15%, 15%+)
- **Promo end dates** — table of loans with promotional rates ending within the configured horizon
- **ARM reset surface** — table of ARMs with next reset within the configured horizon

### C. Payoff Timeline (`PayoffTimeline.csv`, `chart_payoff_timeline.png`)
For each amortizing loan, compute time-to-payoff at the current scheduled payment using straight amortization:

```
months_to_payoff = -log(1 - (rate/12) * balance / scheduled_payment) / log(1 + rate/12)
```

Handle edge cases:
- Rate = 0 → `months_to_payoff = balance / scheduled_payment`
- Scheduled payment < monthly interest → "indefinite at current pace" (flag in anomalies)
- Revolving loans → skip, flag as "indefinite (revolving)"
- Informal loans → skip, flag as "informal — no schedule"

### D. Anomalies (`Anomalies.md`)

Descriptive observations only. Each is a fact, not a problem:

- **High-rate revolving:** credit cards with non-zero balance + APR > `high_rate_revolving_apr`
- **Upcoming ARM resets:** within `arm_reset_horizon_months` of today
- **Near-payoff loans:** within `near_payoff_months` of full payoff
- **PMI candidates:** mortgages with active PMI + reported LTV < `pmi_ltv_threshold`
- **Expiring promos:** promotional rates ending within `promo_expiry_horizon_days`
- **Tax-debt at high rate:** tax-debt rate > `tax_debt_rate_alarm`
- **Payments below interest:** scheduled payment insufficient to cover monthly interest (balance growing)
- **Informal loans without rate:** family loans flagged for documentation completeness

### E. Consolidated Report (`Debt Report.md`) — primary artifact

Single Markdown report, structured around questions a debt holder typically asks. Section order:

1. **How much do I owe, and to whom?** — total debt + composition pie (inline) + breakdown table by type
2. **What's it costing me?** — weighted-avg rate, distribution by rate band, variable-rate exposure ($ and %)
3. **When does each loan pay off at current pace?** — payoff timeline table + chart (inline)
4. **Where is the debt secured?** — secured vs unsecured split + secured-by-asset matrix
5. **What's tax-deductible?** — deductible / partial / non breakdown (acknowledge that final deductibility depends on filer's MAGI/SALT context — this skill flags the eligibility, not the actual deduction)
6. **Anything unusual in the data?** — anomalies section
7. **What changed since last refresh?** — conditional, only on refresh runs (compare current ledger to prior snapshot)

Closing section: **"Pair with `investment-analysis` for a balance-sheet view"** pointing to the future Layer-2 `balance-sheet` skill.

### F. Charts

Inline in main report:
1. `chart_composition_pie.png` — by loan type (Section 1)
2. `chart_payoff_timeline.png` — months-to-payoff per loan, sorted (Section 3)

Generated but not embedded:
3. `chart_rate_by_loan.png` — APR per loan (Section 2 table covers it)
4. `chart_debt_by_owner.png` — owner split (Section 1 table covers it)

## Folder layout

```
<user-folder>/
├── <loan statement files>
├── Debt Report.md
├── Debt Ledger.csv
├── debts_config.yaml
└── .analysis/
    ├── raw_loans.csv
    ├── loans_consolidated.csv
    ├── loans_classified.csv
    ├── statements_meta.json
    ├── Totals.csv
    ├── RateExposure.md
    ├── PayoffTimeline.csv
    ├── Anomalies.md
    ├── consolidation_summary.md
    ├── _analyze_summary.json
    └── chart_*.png
```

## Chat-side wrap-up

After the report writes, message the user with:

- Total debt + loan count
- Weighted-average rate
- Variable-rate exposure ($ and %)
- Top 3 anomalies (if any) — facts, not advice
- Pointer to `Debt Report.md`

End with the cross-skill hint:

> *"This describes the current debt picture. Pair it with `investment-analysis` to see your full balance sheet — and when a `debt-payoff` planning skill exists, it'll take this ledger plus your cashflow to surface payoff strategies."*
