# Analyze

Standard analyses for a consolidated expense dataset. Most user questions fit one of these patterns. Run them, surface the punch line, then offer drill-downs.

The convention throughout: `df` is a DataFrame with the schema from `consolidate.md` (Date, Source, Description, Category, Subcategory, Amount, Original Category).

## Questions you can ask (offer this when entering the analysis pass)

After cleanup terminates (Misc < 5%, no new flagged rules), run the **defaults** silently — by-category breakdown + per-person split — then offer a menu under the heading **"Questions you can ask"**. The menu is starter examples, not an exhaustive list — make this explicit so the user knows custom questions are welcome.

**Don't say "Phase 5" to the user.** Open with something like *"Cleanup's looking solid — Misc at X%. Here's the headline + person split. What do you want to dig into next?"* See `SKILL.md` for vocabulary rules.

The "What it answers" column should **telegraph the capability** ("I can group your Travel transactions into discrete trips"), not just restate the question. Users won't ask for what they don't realize is possible.

| # | Analysis | What it answers (and what we can do) | Output |
|---|---|---|---|
| 1 | **By-category breakdown** *(default)* | "Where does my money go?" | Markdown table, % share, highlights |
| 2 | **Per-person split** *(default)* | "Who's spending on what?" | Category × Person pivot |
| 3 | **Subcategory breakdown** | "What's the structure inside one or several top categories?" — e.g. Travel splits into Airlines / Hotels / Ski / Activities | Subcategory rollup with % within parent |
| 4 | **Drill into one category** | "What's actually inside my $XXk Travel?" — top merchants, biggest single charges | Sorted merchant table within that category |
| 5 | **Cost of trips** | "How much did each trip cost end-to-end?" — I can group your Travel transactions into discrete trips by date proximity + merchant signal | One row per trip with start/end dates + total |
| 6 | **Recurring subscriptions** | "What am I auto-paying every month I forgot about?" — finds monthly + likely annual subscriptions | Recurring merchants + annualized total |
| 7 | **Year-over-year compare** | "What changed vs prior 12 months?" — categories that grew or shrank >20% | Delta table with $ and % changes |
| 8 | **Anomalies** | "What's weird?" — single transactions over $1k, ballooning categories, Misc gaps | Punch list, low signal-to-noise filtered |
| 9 | **Trip detail** | "How much did the Tulum trip cost end-to-end across all my cards?" | One specific trip cluster + every related charge |
| 10 | **Broader commentary** | "Step back — what's the structural story?" — scale, fixed vs flexible, structural patterns, lifecycle inflection points, visibility gaps, what's working well | Narrative observations, no decisions |

**Always close the menu with this line:** *"These are starter examples — ask anything custom about your data and I'll run it."*

Don't dump every analysis at once. Run defaults (1+2), then offer the rest. Move past Misc cleanup if Misc share is already <5% — chasing the long tail is rarely worth the user's time.

## Output format

User-facing summaries (last-12-months totals, category breakdowns, person splits, excluded-items reports, drill-downs) **must be rendered as markdown tables**, not raw text dumps. **Never write "TTM" in user-facing copy** — most people don't know what trailing-twelve-months means. Always say "Last 12 months" (or just "12 months ending YYYY-MM-DD"). The `consolidate.py` script and inline `pandas.to_string()` calls produce monospace text — that's for *you* to parse. Reformat into markdown before showing the user.

Conventions:

- **Right-align amounts** with `|---:|` so dollar columns line up
- **Include a Share / %** column when showing categories so the user sees relative weight
- **Headline above the table** — one line stating the period and total (e.g. "Last 12 months — $488,105 · 12 months ending 2026-04-26")
- **Drop empty columns** — if every row in a column is blank or zero, remove it
- **Format dollars consistently** — `$133,180` for thousands, `$1.3k` only when space-constrained
- **Add a one-line "Highlights" or notes column** for top categories so the user gets the texture without a drill-down

Example shape for the headline category breakdown:

```markdown
## Last 12 months — $488,105

12 months ending 2026-04-26 · 2,489 transactions

| Category | Last 12 mo | Share | Highlights |
|---|---:|---:|---|
| Housing | $178,466 | 36.6% | Mortgage $133.2k · Home Improvement $27.0k · Property Tax $9.8k |
| Travel | $55,810 | 11.4% | Airlines $17.6k · top resort $19.3k |
| Kids | $44,506 | 9.1% | Private school tuition dominates |
| ... | ... | ... | ... |
```

The same applies to **per-source/person splits**, **excluded-items audit reports**, and **drill-downs** into a single category. The user should never see `pandas` `.to_string()` output unless they specifically asked for raw debugging.

## Last-12-months summary by category

The headline number for "where is my money going."

```python
ttm_start = pd.Timestamp.today() - pd.DateOffset(years=1)
ttm = df[pd.to_datetime(df['Date']) >= ttm_start]

total = ttm['Amount'].sum()
by_cat = (ttm.groupby('Category')['Amount']
            .agg(['count','sum'])
            .rename(columns={'count':'txns','sum':'total'})
            .sort_values('total', ascending=False))
by_cat['pct'] = (by_cat['total'] / total * 100).round(1)

print(f"Last 12 months total: ${total:,.0f} across {len(ttm):,} transactions")
print(by_cat.to_string())
```

Present the top 8 categories by amount; everything else can be folded into "Other" if the list is too long. Format dollars with commas, no cents.

## Category × Person pivot

Useful for couples — who is spending on what.

```python
ttm['Person'] = ttm['Source'].str.split().str[0]  # 'Alex AmEx' -> 'Alex'
pivot = ttm.pivot_table(index='Category', columns='Person', values='Amount',
                        aggfunc='sum', fill_value=0).round(0)
pivot['Total'] = pivot.sum(axis=1)
pivot = pivot.sort_values('Total', ascending=False)
print(pivot.to_string())
```

If the household has joint accounts, the pivot will show "Joint" as a third column. That's fine — it's accurate.

## Drill-down into a category

When the user says "show me everything in Food & Dining":

```python
fd = ttm[ttm['Category']=='Food & Dining'].sort_values('Amount', ascending=False)
print(fd.head(30).to_string())  # top 30 by amount

# Subcategory breakdown
print(fd.groupby('Subcategory')['Amount'].agg(['count','sum']).round(0))

# Top merchants
top_merchants = (fd.assign(Merchant=fd['Description'].str.split().str[:2].str.join(' '))
                   .groupby('Merchant')['Amount'].sum()
                   .sort_values(ascending=False).head(10))
print(top_merchants)
```

## Visibility gaps (default output, always run)

A partial picture risks confident-sounding wrong conclusions. The script auto-detects three classes of gap and reports them as part of the wrap-up:

1. **Missing card sources** — auto-pay outflows from checking to card issuers (AmEx, Discover, Citi, Capital One, BofA, Barclays, Wells, Synchrony) where no matching card statement is in `sources`. That card's spending is invisible.
2. **Savings invisible** — no outflows to Schwab / Vanguard / Fidelity / 529 / HSA / brokerage. Savings may be funded via paycheck deduction or a separate account.
3. **Income off-screen** — checking inflows (payroll, etc.) pass through but only spend is in scope. The skill answers "where money goes," not "what comes in."

These are facts about *coverage*, not judgments. Surface them in the Phase 5 default output so the user knows what's not in the analysis. See `consolidate.py: detect_visibility_gaps()`.

## Broader commentary (menu item #10)

When the user asks for "broader commentary" / "step back" / "anything else worth saying" — switch from line-item drill-downs to structural observations. Patterns to surface, in order:

1. **Scale anchor** — total annualized spend in plain context (e.g., "top X% of US households" without a value judgment). Sets the frame.
2. **Fixed vs flexible split** — what % is contractual (mortgages, tuition, insurance, auto loan) vs discretionary (travel, dining, shopping, hobbies). Tells the user how much elasticity they have.
3. **Multi-property weight** — if Holiday Home or rental exists, surface as a combined % of total to make the bundle visible.
4. **Concentration patterns** — e.g., "3 trips own 70% of Travel" or "1 merchant = 40% of Kids." Important for "if I cut X, what does that mean?" reasoning.
5. **Visibility gaps** (see above) — what's NOT in scope.
6. **Division of household labor** — if there's a person split, describe who covers infrastructure vs daily ops. Confirm intentional, not accidental.
7. **Lifecycle inflection points** — what step-changes are coming? Mortgage payoff, kids leaving private school, holiday-home liquidation. Names the dates without doing the math.
8. **One thing working well** — surface a positive pattern (e.g., groceries:restaurants ratio is healthy). Don't make this a flattery line — only include if there's a real positive signal.

Format: 5–8 short paragraphs, each with a heading. Don't use a table — this is narrative, not a punch list. End with: *"Want to dig into any of these?"*

This is **distinct from Phase 6 Actions** — broader commentary is observational. Actions convert observations into commit/snooze/reject candidates.

## Subcategory breakdown

When the user wants to see the *structure* inside one or more top categories — without drilling all the way to merchant rows. E.g. "Travel splits into Airlines/Hotels/Ski/Activities/Parking — here's the share of each."

```python
sub = ttm.groupby(['Category', 'Subcategory'])['Amount'].agg(['count','sum']).reset_index()
sub = sub.sort_values(['Category', 'sum'], ascending=[True, False])

# Or just one category:
travel_sub = (ttm[ttm['Category']=='Travel']
              .groupby('Subcategory')['Amount'].agg(['count','sum'])
              .sort_values('sum', ascending=False))
travel_sub['pct'] = (travel_sub['sum'] / travel_sub['sum'].sum() * 100).round(1)
print(travel_sub)
```

This is one level above merchant drill-down — useful when the user wants "where's my Travel money going?" but doesn't yet care about which specific airline.

## Cost of trips (was: Trip clustering)

Travel transactions are a stream of charges. Group them into discrete trips so the user can answer "what did the Mexico trip cost?"

**Pattern:** group consecutive Travel rows where the gap between dates is ≤ 7 days, with the cluster getting a label from the highest-amount merchant.

```python
travel = ttm[ttm['Category']=='Travel'].sort_values('Date').copy()
travel['Date'] = pd.to_datetime(travel['Date'])
travel['gap'] = travel['Date'].diff().dt.days.fillna(99)
travel['trip_id'] = (travel['gap'] > 7).cumsum()

trips = (travel.groupby('trip_id')
         .agg(start=('Date','min'),
              end=('Date','max'),
              total=('Amount','sum'),
              n=('Amount','count'),
              top=('Description','first'))
         .sort_values('total', ascending=False))
print(trips)
```

Refine with location signals if available (airport codes in descriptions, hotel names mapping to a city, currency markers). For longer trips with intervening stops at home, the cluster gets split — that's usually fine.

When labeling trips, prefer the destination over the airline ("Mexico Trip" over "American Airlines"). The user is most likely to recognize trips by where they went.

## Recurring subscriptions

```python
subs = ttm[ttm['Category']=='Subscriptions & Software'].copy()
recur = (subs.groupby('Description')
         .agg(n=('Amount','count'),
              total=('Amount','sum'),
              avg=('Amount','mean'))
         .sort_values('total', ascending=False))
recur = recur[recur['n'] >= 6]  # at least 6 hits in last 12 months

# Also catch ANNUAL subscriptions (1 hit/yr) — same merchant, same amount,
# total > $50. Most annual subs hit common price points: $99, $149, $199, $299.
annual_candidates = (df.groupby(['Description', 'Amount'])
                       .size().reset_index(name='n')
                       .query('n == 1'))
# Filter to plausible annual subs: round-ish amount, > $50
annual_candidates = annual_candidates[annual_candidates['Amount'] > 50]
# Merge with categorize-able merchants
# (Final list is the union of monthly recurring + likely annuals.)
print(recur)
```

Adjust the threshold — annual subscriptions only show up once. For those, look for amounts that match common subscription tiers ($99, $149, $199, $299, etc.).

## Time-period filters

- **Last 12 months (default):** rolling window from today back 12 months. (Internally called TTM in code; user-facing copy says "Last 12 months".)
- **YTD:** Jan 1 of current year onward.
- **Last calendar year:** Jan 1 to Dec 31 of the prior year.
- **Last quarter:** previous 3 months.
- **By month:** `df.groupby(df['Date'].dt.to_period('M'))['Amount'].sum()` — useful for seasonality.
- **YoY:** compare last 12 months with the prior 12 months (`-2 years` to `-1 year`). Highlight categories that grew >20% or shrank >20%.

## Anomaly surfacing

Run these proactively after any consolidation, even if the user didn't ask:

### Top Misc rows

```python
misc = ttm[ttm['Category']=='Misc'].sort_values('Amount', ascending=False)
print(misc.head(20).to_string())
```

These are the rows the keyword tables didn't catch. Big amounts in Misc are categorization gaps the user should address.

### Single transactions over $1k

```python
big = ttm[ttm['Amount'].abs() >= 1000].sort_values('Amount', ascending=False)
print(big.head(30).to_string())
```

These deserve eyeballing — some will be legitimate (mortgage payment, big-box run, vacation hotel), others might be miscoded.

### Categories that grew vs prior year

```python
prior_start = ttm_start - pd.DateOffset(years=1)
prior = df[(pd.to_datetime(df['Date']) >= prior_start) &
           (pd.to_datetime(df['Date']) < ttm_start)]
ttm_by_cat = ttm.groupby('Category')['Amount'].sum()
prior_by_cat = prior.groupby('Category')['Amount'].sum()
delta = pd.DataFrame({'Last 12 mo': ttm_by_cat, 'Prior': prior_by_cat}).fillna(0)
delta['$ change'] = delta['Last 12 mo'] - delta['Prior']
delta['% change'] = ((delta['Last 12 mo'] / delta['Prior'] - 1) * 100).round(0)
delta = delta.sort_values('$ change', ascending=False)
print(delta)
```

Flag anything ±20% as worth a look.

### Recurring fees / interest / late charges

```python
fees = ttm[ttm['Category']=='Fees']
print(fees.groupby('Subcategory')['Amount'].agg(['count','sum']))
```

Especially useful for "you're paying $1,000/yr in credit card interest — set up autopay."

## Presentation

Lead with the punch line:

> "Last 12 months: $568k. Top three categories: Housing $231k (35%), Kids $103k (17%), Travel $69k (12%). The other 36% is split across 12 smaller categories."

Then offer the menu under **"Questions you can ask"**:

> "Want me to break Housing into mortgage vs taxes vs utilities? Or see the cost-of-trips breakdown for Travel? Or — ask anything custom about your data."

Don't dump every analysis at once. Give them the headline; let them pick what to look at next. Always end the menu with a line that makes clear it's starter examples, not an exhaustive list.
