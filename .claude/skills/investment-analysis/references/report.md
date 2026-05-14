# Report

Phase 5: produce the full artifact set + editorial commentary. **Descriptive only.** This is where the discipline against recommendation language matters most — pattern surfacing, fact statement, no judgment.

## Inputs

- `positions_classified.csv` from classify
- `references/data/thresholds.yaml` — concentration thresholds, idle-cash limits, dust-position cutoffs
- User's local `investment_analysis_config.yaml` — overrides on thresholds, exclusions, methodology
- *(Optional)* Prior run's `positions_classified.csv` for delta computation

## Outputs

Eight artifacts. All written to the user's working folder (same directory as the source statements):

| File | Purpose |
|---|---|
| `Investment Positions.csv` | Flat ledger — every position row, post-classification |
| `Allocation.csv` | Through-the-fund roll-up by sleeve, sub-class, account, owner |
| `Concentration.md` | Top exposures vs configured thresholds, as facts |
| `TaxLocation.md` | Asset class × wrapper matrix, with descriptive notes |
| `Fees.csv` | Per-fund and weighted ER; total annual fee load |
| `Income.csv` | Annualized income by holding, broken down by character |
| `Anomalies.md` | Idle cash, duplicates, dust, missing data, follow-ups |
| `Commentary.md` | Descriptive narrative — "what stands out about the current state" |

Plus the chart pack (PNGs + one interactive HTML), described later.

## Vested vs unvested discipline

Every artifact must clearly label which view it's reporting. Default to **vested-only** for headline numbers; surface **vested + unvested** as a memo line.

The reason: unvested awards (LTIPs, RSUs) represent economic exposure but are not the user's money today. Mixing them silently into "investable" inflates the picture in a misleading way. The user needs both views — they're answering different questions ("what do I own" vs "what's my total economic exposure to firm X").

Concrete: every output that totals dollars carries two columns or two clearly-labeled sections — vested vs vested+unvested.

## Refresh delta (when prior run exists)

If the working folder contains a prior `positions_classified.csv` from an earlier run, every artifact should also surface the **delta vs prior**:

- New positions added (deposits, vest events, new accounts)
- Removed positions (sales, distributions, account closures)
- Value changes per holding ($ delta + % delta)
- Allocation drift per sleeve
- Concentration changes (e.g., "PIMCO exposure went from 25% → 22%")
- Anomalies resolved since last run; new anomalies introduced

Surface deltas as a fact, not a judgment ("Tech exposure +3 pp" — not "tech exposure has grown concerningly to..."). Same descriptive discipline.

If no prior run exists, skip the delta section entirely.

---

## Artifact A: Allocation breakdown

**File:** `Allocation.csv`

Schema:

```
view                  # "by_sleeve" / "by_asset_class" / "by_account" / "by_owner" / "by_wrapper"
group                 # the bucket name (e.g., "us_equity", "qualified_401k", "primary")
value_gross           # $
value_net             # $ after tax_haircut applied
pct_of_investable     # 0.0–1.0
pct_change_vs_prior   # null on first run; signed % on refresh
```

Each view is a separate stack of rows. Read with `df[df['view'] == 'by_sleeve']` to get the sleeve roll-up.

**Sleeve definitions:**

| Sleeve | Includes |
|---|---|
| Equity | `us_equity`, `intl_dev_equity`, `intl_em_equity` |
| Fixed income | `us_bonds`, `intl_bonds` |
| Cash | `cash` (across all accounts; investment-account cash, not operational checking) |
| Real estate | `real_estate` (investment use; primary residence optionally) |
| Alternatives | `alt_concentrated`, `crypto` |
| Unknown | `unknown` (if any survived classification) |

Surface unknown as its own line, never roll into another sleeve.

**Chart:** `chart_allocation_pie.png` — sleeve breakdown, percentages on segments, sleeve totals in a corner box.

**Chart:** `chart_asset_class_bars.png` — within-sleeve breakdown (e.g., within Equity: US / intl dev / EM as a stacked bar; within Fixed income: by issuer/manager).

---

## Artifact B: Concentration map

**File:** `Concentration.md`

Surfaces top exposures **as facts**, against thresholds from config. Each row is a fact statement, no judgment.

Sections:

### 1. Top 10 single-name exposures

| Rank | Ticker / Holding | $ Value | % of Investable | Above 5% threshold? |
|---:|---|---:|---:|:---:|
| 1 | EXAMPLE_HOLDING_A | $X | Y% | ✓ |

Threshold pulled from `concentration_thresholds.single_name`. The "above threshold" column is a fact, not a problem.

### 2. Single-sector concentration (through-the-fund)

Computed by:
1. Sum direct exposure (e.g., VGT, MSFT individual)
2. Add implied exposure through broad-market ETFs (VTI's tech weight × VTI value)
3. Roll up by sector

| Sector | Direct $ | Implied $ (through broad ETFs) | Total $ | % of Equity |
|---|---:|---:|---:|---:|
| Technology | $X | $Y | $Z | W% |

Flag any sector exceeding `concentration_thresholds.single_sector` (default 25% of equity) — as a fact, not a prescription.

### 3. Single-fund concentration (within sleeves)

For each sleeve, the largest single-fund share:

| Sleeve | Largest fund | $ | % of sleeve |
|---|---|---:|---:|
| Fixed income | PIMIX | $X | Y% |

Flag any fund exceeding `concentration_thresholds.single_fund_in_sleeve` (default 50%).

### 4. Single-issuer / single-employer aggregation

The most consequential check for the user. Sum across ALL forms of exposure to a single firm:

- Direct equity holdings (e.g., MSFT shares if Microsoft is the employer)
- Employer-linked wrappers (NQDC, EDCP balance — note: holdings *inside* are NOT firm risk, but the *wrapper* itself is)
- Concentrated comp awards (M Units, LTIPs, RSUs, profit units) — both vested and unvested
- ESPP holdings
- Pension exposure to the employer (if not yet PBGC-protected)

Output:

| Issuer / Employer | Direct | Wrapper | Comp awards (vested) | Comp awards (unvested) | Total | % of investable |
|---|---:|---:|---:|---:|---:|---:|
| EMPLOYER_A | $X | $Y | $Z | $W | $T | P% |

Show two columns of totals — vested-only and vested+unvested. Flag any issuer exceeding `concentration_thresholds.single_issuer` (default 25%) — as a fact.

### 5. Geographic concentration

| Region | $ | % of Equity |
|---|---:|---:|
| US | $X | Y% |
| International developed | $X | Y% |
| Emerging markets | $X | Y% |

Surface as percentages of *equity*, not of total investable.

### Wording

For each flag, use descriptive language only:

- ✗ "You should reduce tech exposure" — banned
- ✗ "Consider trimming this position" — banned
- ✗ "Above the comfortable threshold" — banned (implies prescription)
- ✓ "Technology sector exposure (direct + implied) is X% of equity, above the configured threshold of 25%"
- ✓ "Issuer-aggregated exposure to EMPLOYER_A is X% of investable, above the configured threshold of 25%"

**Chart:** `chart_concentration_heat.png` — horizontal bar chart of top 15 exposures with color intensity = % of investable; threshold line drawn at the configured limit.

---

## Artifact C: Tax-location audit

**File:** `TaxLocation.md`

A matrix: asset class (rows) × wrapper type (columns), filled with $ values. **Describes where things sit. Does not prescribe where they should sit.**

```
                       Taxable    Qualified    Roth    NQDC    HSA    529    Direct    Total
us_equity              $X         $X           $X      $X      $X     $X     $X        $X
intl_dev_equity        ...
intl_em_equity         ...
us_bonds               ...
intl_bonds             ...
cash                   ...
real_estate            ...
alt_concentrated       ...
crypto                 ...
unknown                ...
```

Below the matrix, surface descriptive facts. Examples of acceptable language:

- "$X of growth-oriented equity is held in NQDC wrappers."
- "$Y of high-yield bonds is held in taxable accounts."
- "$Z of tax-exempt income is generated annually (from muni holdings)."
- "$W of foreign-tax-credit-eligible international equity is held in taxable accounts."
- "$V of REIT exposure is held in taxable accounts (REIT distributions are largely ordinary income)."

**Banned language for this section** (recommendation territory):

- "These bonds should be moved to..."
- "Growth assets are inefficient in NQDC; consider..."
- "Tax-location optimization would suggest..."

**Distribution character roll-up** (auxiliary table):

| Character | Account types holding it | $ income / year | % of total income |
|---|---|---:|---:|
| Qualified dividend | Taxable, Roth | $X | Y% |
| Ordinary | Qualified, NQDC, Taxable | $X | Y% |
| Muni (federal exempt) | Taxable | $X | Y% |
| Return of capital | Taxable, IRA | $X | Y% |

**Chart:** `chart_tax_location_matrix.png` — heatmap of the asset-class × wrapper matrix. Cell intensity = $ value; cells with descriptive callouts annotated.

---

## Artifact D: Fee analysis

**File:** `Fees.csv`

Per-fund expense ratios, weighted by holding value. Schema:

```
holding              # ticker
description          # fund name
holding_value        # $ position size
expense_ratio        # annual %
annual_fee_dollars   # holding_value × expense_ratio
asset_class          # sleeve assignment
account              # where held
notable              # flag if ER > 0.75% (active fund threshold) or position > $100k
```

Aggregations to surface:

- Total annual fee load ($)
- Weighted ER by sleeve
- Top 5 fee-paying holdings by absolute $
- Holdings with no ER data (individual stocks have null ER; flag if material)

Descriptive facts only:

- ✓ "Total annual fee load: $X. Weighted ER: Y%."
- ✓ "Largest fee-paying position: ABC at $X/yr (W% ER on $Y position)."
- ✗ "Consider lower-cost alternatives" — banned
- ✗ "The ER on PIMIX is high" — borderline; "PIMIX ER is 0.62%, compared to a registry-typical Agg ER of 0.03%" is OK as a fact

**Chart:** `chart_fees_bar.png` — fee load by sleeve, in dollars.

---

## Artifact E: Income & yield map

**File:** `Income.csv`

Estimated annual income from every yielding position. Schema:

```
holding              # ticker
description
holding_value
est_annual_income    # $ per year
est_yield_pct        # %
distribution_character
account
wrapper_tax_treatment   # how the income is taxed given the wrapper
                        # e.g., qualified-dividend-in-taxable = 23.8% (LTCG+NIIT)
                        # vs qualified-dividend-in-NQDC = ordinary rate at distribution
```

Aggregations:

- Total estimated annual investment income
- By distribution character
- By wrapper (which slice generates income in which tax envelope)

Descriptive facts only. The `wrapper_tax_treatment` column is the closest to "advice" but it's just labeling the character that already applies — not recommending anything.

---

## Artifact F: Anomaly surface

**File:** `Anomalies.md`

Surface observations as facts, not problems. Each section is a category of anomaly.

### 1. Idle cash

Cash sitting in investment accounts above thresholds.

| Account | Cash $ | % of account | Threshold | Note |
|---|---:|---:|---:|---|
| brokerage_1 | $X | Y% | 5% | Recent deposit on [date], not yet deployed |

Thresholds: `concentration_thresholds.idle_cash_in_account` (per-account) and `idle_cash_total` (across all investment accounts).

### 2. Substantially-overlapping funds (potential TLH pairs)

When the user holds multiple funds with similar exposure but different indices:

| Fund A | Fund B | Asset class | Indices |
|---|---|---|---|
| VTI | SCHB | us_equity | CRSP US Total / DJ US Broad Stock Market |

Note that this is *useful infrastructure for tax-loss harvesting* — different indices = not substantially identical = legal swap partners. Surface as a fact: "These two funds have substantially overlapping exposure but track different indices, making them a TLH-eligible pair." No recommendation about whether or when to harvest.

### 3. Dust positions

Holdings below `concentration_thresholds.dust_position` (default $1k).

| Account | Ticker | Value | Description |
|---|---|---:|---|

Surface count + total dollars. ("23 dust positions totalling $X — typically DRIP residue or direct-indexing artifacts.")

### 4. Missing cost basis

Positions where the statement didn't supply cost basis. Affects gain/loss reporting and tax planning downstream. Surface as a data gap.

### 5. Reconciliation mismatches (vs household balance sheet)

Material differences between consolidated totals and the user's balance-sheet spreadsheet.

### 6. Configured `FOLLOW_UP` markers

Items the user explicitly flagged in their spreadsheet or config as needing attention (e.g., "verify pension value" / "check StandardLife status").

### 7. Stale data warnings

Positions whose underlying fund's `last_verified` registry date is more than 1 year old. The asset-class breakdown may have drifted.

---

## Artifact G: Commentary

**File:** `Commentary.md`

A short editorial narrative — **descriptive** — answering "what stands out about the current state of this portfolio?" Aim for ~500–800 words. Sections:

1. **Headline numbers.** Total investable (vested), total net worth (vested + unvested), sleeve split. One paragraph.

2. **What's structurally notable.** Concentrations, unusual placements, things that would surprise a fresh observer.

3. **What's surprising in the data.** Comparing to typical portfolios at this scale, what's atypical? (Not "wrong" — atypical.)

4. **Deltas since last refresh** (if applicable). What changed, in plain language.

5. **Data caveats.** Anything classified with low confidence, unresolved unknowns, methodology choices the reader should know.

**Fair-game topics:**

- Notable single-name, sector, fund, or issuer concentrations
- Where assets are located (wrapper-wise) and the character of income they generate
- Idle, duplicated, or dust patterns
- Vested vs unvested gap
- Anything genuinely surprising in the data — e.g., "no international equity exposure at all" or "100% of fixed income with one issuer"

**NOT fair-game:**

- What the user should do about anything
- Comparisons to a "target," "ideal," "model," or "optimal" allocation
- Phrases starting with "consider," "should," "would benefit from," "is inefficient in," "is the wrong wrapper for"
- Speculation about the user's goals or intentions
- Comparisons to outside benchmarks unless purely descriptive ("US-equity is 75% of equity; the global market cap weighting is about 60% US")

**Tone:** an investment-savvy CFO reading the household balance sheet for the first time. Curious, observant, factual. Not advisory.

---

## Artifact H: Charts

PNG charts with the same aesthetic as the `expenses` skill: cream background (`#FAF7F2`), muted palette, Georgia serif titles, horizontal-only gridlines, percentages annotated on segments where helpful.

| File | Type | Content |
|---|---|---|
| `chart_allocation_pie.png` | Pie | Sleeve breakdown with totals |
| `chart_asset_class_bars.png` | Stacked bar | Within-sleeve breakdown |
| `chart_concentration_heat.png` | Horizontal bar | Top 15 concentrations with threshold lines |
| `chart_tax_location_matrix.png` | Heatmap | Asset class × wrapper |
| `chart_fees_bar.png` | Bar | Fee load by sleeve |
| `chart_income_breakdown.png` | Stacked bar | Income by character |
| `chart_sankey.html` | Plotly Sankey | Owner → Wrapper → Asset class flows |

Sankey is optional — auto-generated only if `plotly` is installed. PNGs always render with matplotlib alone.

For all charts:

- Title in Georgia serif, weight bold, 14pt
- Axis labels in same font, 10pt, normal weight
- Threshold lines (where applicable) dashed in a muted red (`#A04040`)
- Color palette: pull from a consistent named palette (defined in `scripts/generate_charts.py` so all charts visually rhyme with `expenses`)
- Each chart has a one-line subtitle below the title that summarizes the takeaway *descriptively* (e.g., "US equity 36%, intl 12%, bonds 24%, real assets 12%, alts 16%" — not "you're under-allocated to international")

---

## End-of-phase summary

After all artifacts are written, end the conversation with a **drill-down offer**, not a "next-steps" or "recommendations" pitch. Template:

> "Analysis written. Files saved to [folder]:
>
> - `Investment Positions.csv` — flat ledger, [N] positions
> - `Allocation.csv` — through-the-fund breakdown
> - `Concentration.md` — top exposures vs thresholds
> - `TaxLocation.md` — asset class × wrapper matrix
> - `Fees.csv` — fee load
> - `Income.csv` — income by character
> - `Anomalies.md` — idle cash, duplicates, dust, follow-ups
> - `Commentary.md` — what stands out
> - 7 chart files
>
> Investable (vested): $X. Net worth (vested + unvested + RE equity): $Y.
>
> Want to drill into any specific sleeve, account, holding, or anomaly? Or pull on a particular thread — concentration map, fees, income character, tax-location matrix?"

**Banned closing phrases:**

- "Want me to recommend rebalancing moves?"
- "Should we look at optimization opportunities?"
- "Here's what I'd suggest doing about it..."
- "Want to think about where to deploy the cash?"

If the user asks for recommendations:

> "Recommendations need financial planning context — your spending, goals, horizon, FI status — that lives in a separate skill. This one stops at description. Once a `financial-planning` skill exists, it'd take this analysis as input alongside those planning inputs and produce target allocations and rebalancing moves. For now, ask me anything *descriptive* — drill-downs, deeper looks at any holding or sleeve, sanity checks on the numbers."

## Output file conventions

- All filenames use **Title Case** for `.md` and `.csv` files visible to the user (`Allocation.csv`, `Concentration.md`) — matches the `expenses` skill convention (`Lifestyle Expenses.csv`).
- Chart filenames use `lowercase_snake_case` prefixed with `chart_` (`chart_allocation_pie.png`) — internal naming, less user-facing.
- All files written to the same folder as the input statements.
- If the folder name contains the user's surname or personal identifiers, do not embed that into the filenames — keep names generic.

## What this phase does NOT do

- It does not change the underlying classified data — `positions_classified.csv` is the input, not modified here.
- It does not iterate. If the user asks for a different view of the same data, that's a follow-up drill-down using the same artifacts.
- It does not call out to any LLM or external service after the artifacts are generated. The narrative in `Commentary.md` is template-driven from the classified data + a small set of language patterns. Reproducibility matters: running the same analysis twice should produce identical artifacts (modulo the chart's stochastic layout if any).
- It does not produce trade lists, target allocations, model portfolios, rebalancing recommendations, tax-location moves, or any prescription. Ever.
