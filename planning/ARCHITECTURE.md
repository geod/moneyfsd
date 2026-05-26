# fsdmoney Architecture

Reference for how skills compose. Decomposed by **data domain** (not pipeline step), in four layers.

```
┌──────────────────────────────────────────────────────────────────┐
│ LAYER 4 — Front door                                             │
│   fsdmoney      (thin: routes, onboards, composes)               │
├──────────────────────────────────────────────────────────────────┤
│ LAYER 3 — Planning (adds goals, horizon, risk)                   │
│   retirement-projection    fire-tracker      tax-optimization    │
│   portfolio-rebalance      debt-payoff       cash-flow-forecast  │
├──────────────────────────────────────────────────────────────────┤
│ LAYER 2 — Synthesizers (compose Layer-1 ledgers)                 │
│   balance-sheet   (= investments + debts + non-investable)       │
│   cash-flow       (= income − expenses, over time)               │
│   net-worth       (= balance-sheet snapshots over time)          │
├──────────────────────────────────────────────────────────────────┤
│ LAYER 1 — Domain ledgers (raw data → structured ledger)          │
│   investments  ●live   debts             non-investable-assets   │
│   income       ●beta   expenses ●live                            │
└──────────────────────────────────────────────────────────────────┘
```

## Core invariants

1. **Each Layer-1 skill produces a clean CSV ledger as its persistent output.** That ledger is the contract for higher layers.
2. **Layer 2+ skills do not re-read raw statements.** They read Layer-1 ledger outputs only.
3. **Every Layer-1 skill is independently useful.** A half-built fsdmoney still delivers value from any one domain.
4. **Descriptive vs prescriptive** — Layers 1–2 describe current state. Only Layer 3 adds recommendations, and only with explicit goals + horizon as inputs.

## Layer-1 ledger outputs

| Skill | Output ledger | Owns |
|---|---|---|
| `investments` | `Investment Positions.csv` | What you own + leverage on it: financial positions, all real estate (primary + investment) + their mortgages, margin, SBLOC, 401(k) loans against retirement balances |
| `debts` | `Debt Ledger.csv` | Unsecured + non-real-estate-secured debt: credit cards, student loans, personal loans, BNPL, medical, tax debt, family loans. Auto loans live here until `non-investable-assets` exists. |
| `income` | `Income Summary.csv` | W-2 today; 1099 / K-1 / rental / investment income later |
| `expenses` | `Lifestyle Expenses.csv` | Categorized transactions, person-attributed |
| `non-investable-assets` | `Other Assets.csv` | Primary home, vehicles, collectibles |

## Boundary calls

**Core rule: secured debt lives with the asset it's secured against, in the asset skill that owns the asset.** Net-worth questions (LTV, equity, "what's my house actually worth to me?") require the pairing, so we pair them at the source rather than relying on Layer-2 composition.

Applied:

- **All real estate + their mortgages → `investments`** — primary residence (`use: primary`, excluded from investable allocation), investment properties (`use: investment`, included in real-estate sleeve). Investments skill already owns the `real_estate` block shape.
- **Margin / SBLOC / 401(k) loans against retirement balances → `investments`** — leverage on financial accounts.
- **Vehicles + auto loans → `non-investable-assets`** (when this skill is built). Auto loans temporarily live in `debts` until then.
- **Unsecured + non-real-estate-secured debt → `debts`** — credit cards, student loans, personal loans, BNPL, medical, tax debt, family loans.
- **Mortgage payments → `expenses`** (cashflow view) AND **mortgage balance → `investments`** (balance-sheet view via the property's `mortgage` field). Two views of the same instrument; both correct.

Why this rule: the alternative — splitting asset value into `non-investable-assets` and the matching mortgage into `debts` — forces every "home equity?" question through Layer-2 composition, leaving each Layer-1 skill telling half a story. Pairing at the source keeps each Layer-1 skill complete on its own scope.

## Build order

1. Finish Layer 1 — graduate `investments` and `income` from beta; build `debts`, then `non-investable-assets`.
2. Build `balance-sheet` (Layer 2) — first synthesizer, validates the compose-from-ledgers pattern.
3. Build `cash-flow` (Layer 2) — second synthesizer, same pattern.
4. Build `fsdmoney` wrapper (Layer 4) — only once 5+ skills exist and discovery friction is real.
5. Start Layer 3 with `retirement-projection` — consumes balance-sheet + cash-flow + goals.

## What the wrapper does (and does not) do

**Does:** route ("what aspect of your finances?"), onboard (privacy + household once, not per skill), compose (sequences Layer-1 runs for cross-domain views).

**Does not:** re-implement domain logic, block standalone invocation, hold state beyond a shared `household.yaml`.

The wrapper is a TOC, not a god-object.

## Open questions

- Does `non-investable-assets` warrant a full skill, or just a section in `balance-sheet`? Probably section-in-synthesizer until inputs get richer (vehicle VINs → KBB lookups, collectibles → appraisals).
- Naming: `debts` (chosen over `liabilities` for plain-language clarity; "liability" carries accounting/future-obligation connotation users don't expect). Balance-sheet output may still use "Liabilities" as a column heading where accounting convention applies — skill names don't have to match presentation labels.
- `cash-flow` is both a Layer 2 synthesizer (descriptive) and a Layer 3 input (`cash-flow-forecast`). Keep distinct: Layer 2 describes history; Layer 3 projects forward.
