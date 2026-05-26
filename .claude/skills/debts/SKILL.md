---
name: debts
description: Interview-driven workflow that consolidates loan statements (mortgage, HELOC, auto, student, credit card) plus manual entries (401(k) loans, family loans, BNPL, medical debt, tax-debt payment plans) into a single household debt ledger and produces structured analysis — total debt by type, weighted-average cost of debt, variable-rate exposure, payoff timeline at current pace, anomaly surface. Strictly descriptive — describes what you owe and at what rate, never recommends refinancing, payoff order, consolidation, or strategy. Use whenever the user wants to understand their debt picture, prepare a balance sheet, or audit their debt stack. Trigger on phrases like "analyze my debts", "what do I owe", "debt breakdown", "consolidate my loan statements", "debt audit", "liabilities", "my liability picture", "weighted average interest rate", "time to payoff", "mortgage statements", "student loan summary", or when the user drops a folder of loan statements and wants to make sense of them. Also trigger on refresh asks — the skill is built to re-run quarterly against a stable config and surface what changed (balance moved, rate reset, loan paid off, new loan added).
---

# Debt Analysis

## What this skill does

Walks the user from raw loan statements + a few manual entries → a single consolidated, classified, owner-attributed debt ledger they can analyze. Interview-driven (same 3-stage flow as `investments`, lighter where appropriate).

Output is a clean debt dataset with this schema:

| Column | Meaning |
|---|---|
| Loan ID | Stable alias (e.g., "primary_mortgage", "auto_civic") |
| Owner | Household member; `joint` for joint debt |
| Type | mortgage / heloc / auto / student_federal / student_private / credit_card / personal / 401k_loan / bnpl / medical / tax / family / other |
| Lender | Servicer / issuer alias |
| Balance | Current outstanding principal |
| Original Amount | If known (mortgages especially) |
| Rate | APR |
| Rate Type | fixed / variable / promo |
| Reset Date | For ARMs / promotional periods; null for fixed |
| Term Months Remaining | Months left at the current schedule |
| Min Payment | For revolving (credit cards); null for amortizing |
| Scheduled Payment | Monthly P&I (+ escrow if combined into one billed payment) |
| Status | revolving / amortizing / interest_only / paid_in_full |
| Tax Treatment | deductible / partially_deductible / non_deductible |
| Secured By | "primary_residence" / "vehicle_X" / "investment_account" / null |
| Co-signer | bool |
| Notes | freeform |

Plus derived analyses (totals by type, weighted-avg rate, variable-rate exposure, payoff timeline, anomalies) and editorial charts.

## What this skill does NOT do

**Descriptive only.** Strictly out of scope:

- "You should refinance this" — that's a market-comparison + closing-cost decision, separate skill
- "Pay off X before Y" — that's avalanche/snowball strategy, requires goals + cashflow input
- "Consolidate these into a single loan" — strategic recommendation
- "Pay extra $X/month" — cashflow trade-off decision
- "Sell asset to pay off debt" — cross-skill strategy
- Performance projections, scenario modeling

Those belong to a future `debt-payoff` planning skill (Layer 3) that takes this skill's ledger + cashflow + goals as inputs. **Do not leak prescriptive language into this skill's output.**

## When to trigger

Fire this skill when the user wants to do **any** of:

- Consolidate loan statements into one view
- See their total debt + breakdown by type
- Compute weighted-average cost of debt
- Map debt by tax-treatment, variable-rate exposure, secured-by
- See time-to-payoff for each loan at current pace
- Identify anomalies: still-active PMI, ARM resets coming, high-rate revolving balances
- Refresh a prior analysis

If the user asks for *what to do* about their debt (refinance, payoff order, consolidate), this is not the right skill — surface that and route to the future `debt-payoff` skill.

## The five phases (agent-internal vocabulary — NEVER show to the user)

| # | Phase | Mode | Termination signal |
|---|---|---|---|
| 1 | **Interview** | Discovery (3 internal stages) | User confirms setup summary |
| 2 | **Ingest** | Mechanical | Statements parsed + manual_entries injected |
| 3 | **Consolidate** | Mechanical | Loans deduped, owners attributed, household total reconciles |
| 4 | **Classify** | Mechanical | Every loan has status + tax_treatment + secured_by |
| 5 | **Report** | Pattern surface | Artifacts written; user has drilled in |

### User-facing transition prompts

Same convention as `investments` — never name the phase to the user.

| Transition | What you say |
|---|---|
| Stage 1 → Stage 2 | *"Got it — that's your expected debt inventory. Now drop loan statements into one folder. Auto, student, credit-card, personal-loan statements — anything you have. (Mortgage statements go in the `investments` folder, not this one — same skill that tracks home value.) If something doesn't have a statement (family loan, 401(k) loan), I'll capture it in a sec."* |
| Stage 2 → Stage 3 | *"Read [N] loan statements. Before I run the full analysis, [K] things to clear up:"* |
| Stage 3 → Phase 3 | *"Setup confirmed. Consolidating now."* |
| Phase 3 → Phase 4 | *"Consolidated. [N] loans totalling $X.XM. Classifying tax treatment and status."* |
| Phase 4 → Phase 5 | *"Classification done. Writing the report."* |
| Phase 5 → done | *"Report written — `Debt Report.md` walks through total debt, type breakdown, rate exposure, payoff timeline, and anomalies. Companion CSV/MD drill-downs in `.analysis/`. Pair this with the investment-analysis output to see your full balance sheet."* |

### Banned vocabulary in user-facing output

Same descriptive-only rules as `investments`:

- "You should ___", "Consider ___", "I recommend ___"
- "Refinance", "consolidate", "pay off ___ first", "pay extra"
- "Sell ___ to pay down ___"
- "Optimize" (when implying action)
- "Snowball" / "avalanche" (those are strategies, not facts)

Replace with descriptive equivalents:
- "The largest loan is X at $Y"
- "$Z of debt is variable-rate"
- "Weighted-average rate is N% across all loans"
- "Loan X has W months remaining at current scheduled payments"

Detailed instructions for each phase live in `references/`.

## Second-visit flow (return user — refresh, not redo)

**Always check first:** does the user's working folder already contain `debts_config.yaml` + a prior `Debt Ledger.csv`? If yes → refresh, not new setup.

> "I see you ran this before — your config tracks [N] loans across [type breakdown]. Ledger is from [date].
>
> Two questions before I refresh:
>
> 1. **Drop any fresh statements in the same folder.** I'll re-read and surface deltas.
> 2. **Anything new since last refresh?** [Show the Stage-1 coverage checklist with already-tracked categories pre-marked as `✓ already tracked`.]"

Read the prior config and prior ledger before asking anything. Don't re-ask things already in the config.

---

## Phase 1: Interview

**Goal:** Same as `investments` — learn just enough, without making the user defend account-by-account knowledge before they've gathered statements.

Phase 1 runs as **three internal stages**. Read `references/interview.md` for the full script. Briefly:

### Stage 1 — Opener (before any files are touched)

- **Privacy + outcome hook.** What the user *gets* (consolidated debt view, weighted-avg rate, variable-rate exposure, payoff timeline, anomaly surface). Strictly descriptive — what *is*, not what to *do*.
- **Coverage checklist via `AskUserQuestion`, two grouped multi-selects in one call:**
  1. *Most common debts* — ordered by US household incidence: Credit cards (revolving), Auto, Student, Personal loan/LOC
  2. *Other types of debt* — neutral framing (NOT "easily-forgotten" — that signals weird stuff): BNPL, 401(k) loan, Medical/collections, Family/informal
- **Long-tail items captured conversationally** *after* the checklist: IRS/state tax plan, anything else.
- **Mortgage / HELOC is explicitly NOT on the debts checklist** — those live in `investments` next to the residence they secure (per the architecture's "secured debt lives with the asset" rule). The opener must explicitly tell the user this, or they'll tick a missing option and be confused later.
- **Why force-rank by commonality and start with high-incidence:** Leading with the most common items primes recall on the categories that matter most for the most users. Starting with unusual debts ("401(k) loan...") signals "we're going to ask weird stuff" and users mentally check out.
- **What NOT to ask in Stage 1:** revolving-vs-paid intent, rate-type detail, ARM reset dates, co-signer attribution. All deferred to Stage 3.

### Stage 2 — Drop & silent inference

- *"Drop loan statements into one folder. Anything you have right now. If something's a pain to grab, leave it — we'll deal with it in a minute."*
- Run `scripts/extract_loans.py`. Silently parse known formats (mortgage, auto, student-federal, credit-card billing summaries). Infer lender, loan type, balance, rate, payment from statement structure.
- Reconciliation failures, unknown lenders, ambiguous loan types → flag for Stage 3.

### Stage 3 — Gap reconciliation

Compute the diff between **ticked categories** and **inferred-from-statements**. Three buckets (same pattern as `investments`):

| Bucket | What to do |
|---|---|
| Ticked AND found | Silent |
| **Ticked but NOT found** | Ask once: drop now / manual entry (balance + rate) / skip |
| Found but NOT ticked | Confirm |

**Statement-only questions** (asked only for relevant ticked categories):

- **Credit cards** → revolving or paid-in-full each month? (Pay-in-full cards exit the ledger; revolving stays. Default: assume revolving if balance > 0.)
- **Mortgages / ARMs** → fixed or variable? If ARM, next reset date? (Default: fixed.)
- **Promotional 0% balances** (BNPL, balance transfers) → promo end date? (Default: assume current rate continues.)
- **Family / informal loans** → balance, rate (if any), repayment expectation (Default: 0% rate, indefinite term, flag as informal.)
- **Co-signers / co-borrowers** → split or single-owner? (Default: single owner = whoever's named first on the statement.)

Apply defaults silently. **Never make the user defend not knowing.**

### Closing the interview

Write a one-paragraph setup summary and wait for confirmation before running the full pipeline.

**Never expose source-format quirks** ("Wells Fargo mortgage statements bury the principal in a footnote", etc.) — agent-only knowledge, lives in `references/ingest.md`.

---

## Phase 2: Ingest

**Goal:** Parse each statement. Pull balance, rate, payment, lender, loan type per statement. Inject manual_entries from config.

Read `references/ingest.md` for per-format patterns. Covers:

- **Mortgage statements** (CFPB-standardized): Statement Date, Outstanding Principal, Interest Rate, Monthly Payment (P&I + escrow), YTD Interest Paid, Loan Maturity Date
- **Auto loan statements**: similar regulated structure
- **Student loan statements** (federal servicers): MOHELA, Nelnet, EdFinancial, ECSI, Aidvantage
- **Credit card billing statements** (TILA-mandated): Account Summary box, Interest Charge Calculation, APR, Statement Balance, Minimum Payment Due
- **HELOC**: variable-rate mortgage variant
- **Personal loans / BNPL**: fall back to manual entry if no consistent format

Output: a flat `raw_loans.csv` with uniform columns. The `extract_loans.py` script handles known patterns; modify per servicer as encountered.

**Reconciliation:** for each statement, the extracted balance must match the statement's "Current Balance" line within $1. Off-by-rounding is fine; off-by-anything-else means a parse error to surface.

---

## Phase 3: Consolidate

**Goal:** Take raw loans + manual_entries, attribute to owners, dedupe duplicates (same loan appearing in two statement formats), reconcile.

Read `references/consolidate.md`. Key operations:

- **Owner attribution** via `accounts[].owner` or statement headers (Borrower / Co-Borrower).
- **Joint debt** gets `joint` owner attribution + split per the user's rule (default 50/50).
- **Manual entries** injected from config — first-class rows in the ledger.
- **Reconciliation** against any user-provided balance-sheet spreadsheet (if dropped alongside statements).

Output: `loans_consolidated.csv` ready for classification.

---

## Phase 4: Classify

**Goal:** Map each loan to status + tax_treatment + secured_by. Mechanical.

Read `references/classify.md`. Key operations:

- **Status**: revolving (credit cards, HELOCs in draw period) / amortizing (mortgages, autos, student, personal) / interest_only (rare — some HELOCs) / paid_in_full (zero balance, kept for audit)
- **Tax treatment**: 
  - `deductible`: primary-mortgage interest within IRS limits ($750k post-2017), student loan interest within phase-out, HELOC interest if used for home improvement
  - `partially_deductible`: mortgages above the deduction cap, mixed-use HELOCs
  - `non_deductible`: auto, personal, credit card, BNPL, family, medical, tax-debt
- **Secured by**: from statement headers / loan type (mortgage → primary residence, auto → vehicle, 401(k) loan → retirement balance, HELOC → home equity)

Surface a one-shot review list for ambiguous cases ("This HELOC — home improvement or mixed use? Affects deductibility."). Apply defaults silently for clear cases.

Output: `loans_classified.csv` with status, tax_treatment, secured_by populated.

---

## Phase 5: Report

**Goal:** Produce the analysis artifact set. **Descriptive only.**

Read `references/report.md`. Standard outputs:

### A. Totals (`Totals.csv`, embedded in main report)

- Total debt
- Breakdown by type (mortgage / auto / student / CC / etc.)
- Breakdown by owner
- Breakdown by tax treatment
- Breakdown by secured-vs-unsecured

### B. Rate exposure (`RateExposure.md`)

- Weighted-average APR across all debt
- Variable-rate exposure: $ and % of total
- Promo / introductory rates with end dates
- ARM reset surface (any reset in next 12 months)
- Distribution by rate band (<5%, 5-7%, 7-10%, 10-15%, 15%+)

### C. Payoff timeline (`PayoffTimeline.csv`, `chart_payoff_timeline.png`)

For each amortizing loan, time-to-payoff at the current scheduled payment. Revolving loans flagged as "indefinite at current min payment."

**Not** a payoff recommendation — just a fact about each loan at its current trajectory.

### D. Anomaly surface (`Anomalies.md`)

Descriptive observations, not problems:

- Credit cards with non-zero balances + APRs > 18% (highest-cost debt)
- ARM resets within next 12 months
- Loans approaching payoff (< 6 months remaining)
- Active PMI on mortgages where reported LTV < 78% (PMI may be removable)
- Promotional 0% balances expiring within 60 days
- Family loans flagged with no rate (informal — note it's outside formal credit)

### E. Consolidated Report (`Debt Report.md`) — primary artifact

Single Markdown report organized around questions a debt holder typically asks:

1. **How much do I owe, and to whom?** — aggregate total + composition pie
2. **What's it costing me?** — weighted-avg rate, distribution by rate band, variable-rate exposure
3. **When does each loan pay off at current pace?** — payoff timeline
4. **Where is the debt secured?** — secured-vs-unsecured breakdown, secured-by-asset matrix
5. **What's tax-deductible?** — deductible/partial/non breakdown
6. **Anything unusual in the data?** — anomalies
7. **What changed since last refresh?** — conditional, only on refresh runs

Then a closing **"Pair with `investment-analysis` for a balance-sheet view"** section pointing to the future `balance-sheet` Layer-2 skill.

### F. Charts

1. **Composition pie** (`chart_composition_pie.png`) — by loan type, inline
2. **Rate-by-loan bar** (`chart_rate_by_loan.png`) — inline
3. **Payoff timeline** (`chart_payoff_timeline.png`) — inline
4. **Debt by owner** (`chart_debt_by_owner.png`) — generated, not embedded (table covers it)

Run via `python scripts/generate_charts.py <work_folder>`.

---

## Output

### Folder layout

Same pattern as `investments`:

```
<user-folder>/
├── <statement files>          ← user's own loan statements
├── Debt Report.md       ← primary deliverable
├── Debt Ledger.csv      ← user-facing flat ledger
├── debts_config.yaml     ← config (re-read on refresh)
└── .analysis/                  ← all intermediates and drill-down
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

### Primary artifact

`Debt Report.md` at the root of the user's folder. Auto-opens on completion (same `--no-open` flag as `investments`).

### Chat-side wrap-up

Tight summary:

- Total debt + count of loans
- Weighted-average rate
- Variable-rate exposure ($ and %)
- Top 3 anomalies (if any)
- Pointer to `Debt Report.md`

End with the cross-skill hint:

> *"This describes the current debt picture. Pair it with `investment-analysis` to see your full balance sheet — and when a `debt-payoff` planning skill exists, it'll take this ledger plus your cashflow to surface payoff strategies."*

Do **not** offer debt strategy recommendations directly.

---

## Common pitfalls

**1. Counting a credit card with $0 balance as debt.** Filter it out (or flag as `paid_in_full` and exclude from the headline total). Headline "you have $50k of debt" shouldn't include 12 cards with $0 balance.

**2. Double-counting joint debt.** A joint mortgage shows up on both spouses' credit reports. If both users dropped statements, dedupe by `lender + balance + rate` triplet — same loan, not two.

**3. Mortgage payment includes escrow, but escrow isn't interest.** When computing "monthly P&I," strip out escrow. The CFPB-mandated statement breaks it out — use the principal + interest line, not the total payment.

**4. ARM resets buried in fine print.** Mortgage statements usually disclose the next adjustment date in a separate section, not the headline. Look for it during parsing; if absent, mark `reset_date: unknown` and surface in anomalies.

**5. Family / informal loans aren't credit instruments.** They have no APR, no formal term, no minimum payment. Capture them in the ledger but mark `status: informal` so analyses (weighted-avg rate, payoff timeline) can exclude them cleanly.

**6. 401(k) loans inside the retirement plan.** The user's investment-analysis run may already capture them. To avoid double-counting later in `balance-sheet`, this skill marks them with `source: investments_skill` if pulled from there. Cleanest path: read `Investment Positions.csv` if present and pull 401(k) loan rows directly; otherwise ask the user.

**7. Investment-secured debt (margin, SBLOC, rental mortgages).** Stays in `investments`, not here. If a user tries to drop a margin loan statement, redirect: "Margin loan goes in your investment-analysis config — it scales investment exposure, so it lives with the assets it funds."

**8. Mortgages with mixed primary + investment-property combos.** Rare but real — some properties straddle. Force the user to pick a primary categorization (primary, investment); document the call in config notes.

**9. Student loan servicing transfers.** Federal student loans get moved between servicers fairly often. A user might have a statement from a defunct servicer and a current one for the same loan. Dedupe by loan account number (the federal system uses persistent IDs).

**10. Tax debt isn't "regular" debt.** IRS payment plans have specific interest rules (federal short-term rate + 3%) and aren't tax-deductible. Classify separately so the rate-exposure analysis doesn't lump it with mortgage debt.

---

## Files in this skill

- `SKILL.md` — this file
- `references/interview.md` — Phase 1: 3-stage interview script
- `references/ingest.md` — Phase 2: per-format parsing patterns
- `references/consolidate.md` — Phase 3: owner attribution, dedup
- `references/classify.md` — Phase 4: tax treatment, status, secured-by rules
- `references/report.md` — Phase 5: artifact specs
- `references/data/loan_type_taxonomy.yaml` — canonical loan types
- `references/data/thresholds.yaml` — analysis defaults
- `scripts/_config_discover.py` — auto-discover `debts_config.yaml`
- `scripts/extract_loans.py` — statement parsers + manual_entries ingestion
- `scripts/consolidate.py` — dedup, owner attribution
- `scripts/classify.py` — tax treatment + status mapping
- `scripts/analyze.py` — totals, rate exposure, payoff, anomalies
- `scripts/generate_charts.py` — chart pack
- `scripts/generate_report.py` — Debt Report.md + Debt Ledger.csv
- `assets/example_config.yaml` — config template
- `tests/` — pytest suite
