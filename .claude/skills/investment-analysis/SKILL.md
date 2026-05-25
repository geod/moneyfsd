---
name: investment-analysis
description: Interview-driven workflow that consolidates investment statements (PDFs, CSVs, spreadsheets) into a single position ledger and produces structured analysis — through-the-fund allocation, concentration map, tax-location audit, fee breakdown, income/yield map, anomaly surface. Strictly descriptive — describes the current state of a portfolio, never recommends trades or target allocations. Use whenever the user wants to understand what they own, where it sits, how it's distributed, and how concentrated they are. Trigger on phrases like "analyze my investments", "what do I own", "portfolio breakdown", "asset allocation", "consolidate my brokerage statements", "where are my investments", "investment audit", "portfolio concentration", or when the user drops a folder of brokerage / 401(k) / pension statements and wants to make sense of them. Also trigger on refresh asks — the skill is built to re-run quarterly against a stable config and surface what changed.
---

# Investment Analysis

## What this skill does

Walks the user from raw investment statements → a single consolidated, classified, owner-attributed position ledger they can analyze. The skill is **interview-driven**: ask the user about their setup, get them to drop files, run the pipeline, surface gaps iteratively, and produce structured analyses + editorial charts.

The output is a clean position dataset with this schema:

| Column | Meaning |
|---|---|
| Account | Logical account (e.g., "taxable_brokerage_1", "401k_primary") |
| Owner | Household member who owns the position |
| Wrapper | Tax wrapper type — taxable / qualified / roth / nqdc / pension / hsa / 529 / direct |
| Ticker | Security identifier — ticker, CUSIP, or "CASH" |
| Description | Fund / security name |
| Quantity | Shares / units (blank for cash) |
| Market Value | Current $ value |
| Cost Basis | Where statement data permits |
| Unrealized Gain | Where statement data permits |
| Asset Class | Through-the-fund: us_equity, intl_dev_equity, intl_em_equity, us_bonds, intl_bonds, cash, real_estate, alt_concentrated, crypto |
| Sector | For equity holdings (technology, financials, healthcare, …) |
| Expense Ratio | Annual % fee |
| Est. Annual Income | Dividends + interest, annualized |
| Income Character | qualified_dividend / ordinary / muni / return_of_capital |

Plus a set of derived analyses (allocation, concentration, tax-location, fees, anomalies) and editorial charts.

## What this skill does NOT do

This is a **descriptive** skill. It tells the user *what is*, not *what to do*.

Strictly out of scope:

- Target portfolios or model allocations
- Trade lists, rebalancing recommendations, fund swap suggestions
- Tax-location *moves* (the audit surfaces facts; it never recommends)
- Cash deployment plans
- "You should ___" language anywhere in the output
- Performance projections, Monte Carlo, FI analysis, retirement modeling

Those belong in downstream skills (`financial-planning`, `portfolio-optimization`) that take this skill's output as input alongside goals + spending + horizon. **Do not leak prescriptive language into this skill's output.** If the user asks for recommendations, point them at the downstream skills and explain what inputs those need.

## When to trigger

Fire this skill when the user wants to do **any** of:

- Consolidate brokerage / 401(k) / pension / NQDC statements into one view
- See their actual asset allocation across all accounts (through-the-fund)
- Audit concentration — single stock, single sector, single fund, single employer
- Map what's in which tax wrapper (taxable / qualified / Roth / NQDC / etc.)
- Find idle cash, duplicate funds, dust positions, or other anomalies
- See total fee load across their portfolio
- Refresh a prior analysis against new statements

If the user asks for *what to do* with their portfolio (rebalance, deploy cash, pick funds, target allocation), this skill is **not** the right tool — surface that and route to financial planning + portfolio optimization once those skills exist.

## The five phases (agent-internal vocabulary — NEVER show to the user)

Phases are scaffolding for *you*. The user should never see "Phase 3 → Phase 4" or hear the phase names. Use natural transition prompts (see below). The user experiences a smooth journey from "drop your statements" to "here's your portfolio map" without numbered checkpoints.

| # | Phase | Mode | Termination signal |
|---|---|---|---|
| 1 | **Interview** | Discovery | User confirms setup summary |
| 2 | **Ingest** | Mechanical | All sources parsed + per-statement totals reconciled |
| 3 | **Consolidate** | Mechanical | Positions deduped, account types inferred, household total reconciles |
| 4 | **Classify** | Mechanical + LLM | Every holding has an asset class (unknowns flagged) |
| 5 | **Report** | Pattern surface | Artifacts written; user has drilled into what they care about |

**Hard gates matter (internally):**
- **Gate 2→3** — don't consolidate positions you don't trust. Reconcile each statement's extracted total against the statement's own header total before moving on. Off-by-cents = OK; off-by-thousands = something wrong.
- **Gate 4→5** — don't run allocation analysis with unknown funds silently treated as "diversified." Either resolve them (web lookup or user prompt) or surface them as caveats on the output.

### User-facing transition prompts

End every phase by hinting at what's next, in plain language. Never name the phase.

| Internal transition | What you say to the user |
|---|---|
| 1 → 2 | *"Got it — [N statements] across [M accounts], owner attribution mapped. Reading them in now."* |
| 2 → 3 | *(silent — runs inside the script)* |
| 3 → 4 | *"Consolidated. [N] positions across [M] accounts, totalling $X.XM. Anything obviously missing or wrong before I classify?"* |
| 4 → 5 | *"Classification done. [N] of [M] holdings mapped to an asset class. [K] flagged for one-shot review — quick decision on those?"* |
| 5 → done | *"Report written — `Investment Analysis Report.md` walks through how much you have, your asset mix, what you own, where you're concentrated, where things sit tax-wise, fees, and anomalies — with the key charts inline and companion CSV/MD drill-downs in `.analysis/`. Would you like to start building a financial plan from here?"* |

**Banned vocabulary in user-facing copy:** "Phase 3," "Phase 4," "the gate," "termination signal," "phase transition." These are agent terms.

**Allowed and encouraged:** "consolidation," "classification," "analysis," "report," "drill-down," "anomaly." These are user-facing concepts.

### Banned vocabulary across all output

This skill is descriptive. The following language is forbidden in any user-facing output:

- "You should ___", "Consider ___", "I recommend ___", "It would be wise to ___"
- "Target allocation", "model portfolio", "rebalance to ___"
- "Sell ___ and buy ___", "swap ___ for ___"
- "Reduce ___ exposure", "increase ___ exposure"
- "Optimize ___" (when implying action)

Replace with descriptive equivalents:

- "The data shows ___"
- "X stands out about the current state"
- "Y is the largest single-name concentration at Z%"
- "Holdings of type X sit in wrappers Y" (no judgment about whether that's right)

Detailed instructions for each phase live in `references/` — read the relevant file when you enter that phase.

## Second-visit flow (return user — refresh, not redo)

**Always check first:** does the user's working folder already have an `investment_analysis_config.yaml` + a previous position ledger from a prior session? If yes → this is a **refresh**, not a new setup. Skip the interview and offer:

> "I see you ran this before — your config has [N] accounts and [M] manual annotations from last time. Drop your fresh statements in the same folder and I'll re-run with the same rules. Anything change since last refresh I should know about — new account, distribution started, RE valuation update — or just refresh as-is?"

Read the prior config and prior ledger *before* asking any question. Don't re-ask things already in the config:

- "Who's in the household?" — already in `household.members`
- "Which account is taxable vs qualified?" — already in `accounts[].type`
- "What's the EDCP distribution schedule?" — already in `accounts[].distribution_schedule` (if previously captured)
- "What's the RE methodology?" — already in `real_estate[].methodology`

The right second-visit conversation is short:
1. Re-run ingestion + consolidation against the new statements.
2. Surface deltas vs the prior ledger (new positions, removed positions, $-value changes at the holding and asset-category level).
3. Surface any *new* unknowns / anomalies that didn't exist last time.
4. Refresh charts and commentary.
5. Stop.

---

## Phase 1: Interview

**Goal:** Learn what investment data exists, who's in the household, what's in the folder, what's *not* in the folder, and what can't be inferred from the documents themselves. Don't read any files yet — answers shape what to read.

Read `references/interview.md` for the full question list. Briefly:

- **Open with an outcome hook + privacy note before the first question.** Lead with what the user *gets* (consolidated position view, asset allocation, concentration map, tax-location audit, anomaly surface). Address privacy: files stay on local disk; security/holding text does flow through the API for analysis (be honest); per Anthropic's published policy API conversations aren't used for training by default — phrase that as Anthropic's policy, not your guarantee. Point users at the privacy policy if they want stricter assurance.

- **Account-type coverage — coverage prompts, never enumeration.** Prompt the user with categories, not specific institutions:
  - Retirement plans (current and former employer)
  - Pensions — defined benefit, cash balance
  - Direct brokerage / taxable
  - IRAs (traditional, Roth, rollover)
  - Health Savings Account (HSA)
  - Education accounts (529, Coverdell)
  - Employer compensation wrappers (deferred comp, restricted stock, RSUs, options, partnership/profit units)
  - Crypto / digital assets
  - Cash savings (separate from operational checking)
  - Real estate held as investment (rentals, raw land, syndications)
  - Private investments (PE, venture, angel, real estate partnerships)
  
  Never list specific institution names ("Schwab, Fidelity, Vanguard"). The point is to nudge memory for account categories, not to bias toward any custodian.

- **Household structure:** Who's in the household? Whose accounts are whose? Joint accounts? Trust accounts? Minor children with 529s?

- **What can't I tell from the documents themselves?** These don't appear on statements and need direct input:
  - Roth vs Traditional split inside any qualified plan
  - Vesting status of restricted comp (and vest dates)
  - Distribution schedules for deferred comp (NQDC start year, lump vs installment)
  - Cost basis / accumulated depreciation on investment real estate
  - Whether the HSA is invested or in cash sweep
  - Tax-treatment overrides (e.g., user-applied haircut for NQDC at distribution)

- **Real estate methodology:** If the user has investment real estate, ask whether they want it valued at:
  - **Carrying** (MV − Mortgage) — simpler, matches what a balance sheet shows
  - **Liquidation net** (MV − Mortgage − selling costs − cap gains − depreciation recapture estimate) — closer to "deployable wealth"
  - Default: carrying. Document the choice in config so subsequent runs are consistent.

- **Existing config?** Auto-detect first — if `investment_analysis_config.yaml` already exists in the folder, preserve it and offer refresh. Only ask the interview questions when the config is absent.

**Never expose source-format quirks** ("Schwab statements bury cost basis in a footnote", "Fidelity uses CUSIPs not tickers for some lines", etc.) in user-facing prompts. That detail is agent-only and lives in `references/ingest.md` and `scripts/extract_positions.py`.

Use the `AskUserQuestion` tool when there's genuine ambiguity. Don't over-interrogate — five questions max in the opening round. The classify and report phases catch what the interview misses.

After the interview, write a one-paragraph **setup summary** back to the user and ask for confirmation before processing files.

---

## Phase 2: Ingest

**Goal:** Parse each input source. Extract positions. Validate that the extracted total matches the statement's own header total.

Read `references/ingest.md` for source-specific patterns. The reference doc covers:

- PDF extraction with `pdfplumber` (preferred — many users only have PDFs)
- CSV / Excel exports
- Spreadsheet ingestion (when the user maintains a balance sheet of all positions)
- Common statement structures: account summary, position summary, position detail by asset type, transaction detail
- Per-statement validation: sum of extracted positions = statement-stated total (within rounding)

Output of this phase: a flat `raw_positions.csv` with uniform columns:
`Source File | Account Number | Account Name | Statement Date | Holding Type | Ticker/CUSIP | Description | Quantity | Price | Market Value | Cost Basis | Unrealized Gain`

**Use the bundled script** `scripts/extract_positions.py` — it handles the common patterns. Modify the patterns, don't rewrite per session.

**Reconciliation is non-negotiable.** Every statement that's parsed must have its total reconciled against the statement's own summary line. Off-by-cents from rounding is fine; off-by-thousands means an extraction problem — fix it before moving on. Surface reconciliation failures to the user explicitly: *"Statement X says total $Y; I extracted $Z. Difference of $W — let me check what I missed."*

---

## Phase 3: Consolidate

**Goal:** Take the raw positions, infer account types, dedup nested wrappers, attribute to owners, and reconcile against the household-level balance sheet (if provided).

Read `references/consolidate.md`. Key operations:

- **Account type inference.** From statement headers, account-number patterns, employer names, and structural cues, classify each account as: taxable / qualified_401k / qualified_403b / roth_401k / traditional_ira / roth_ira / nqdc / pension_db / pension_cb / hsa / 529 / direct_holdings / cash_savings / real_estate / crypto / alt_concentrated. Apply silent defaults from heuristics. Surface only the genuinely ambiguous cases. Confidence + override pattern lives in `references/data/account_type_taxonomy.yaml`.

- **Nested wrapper deduplication.** Self-directed brokerage windows (PCRA, BrokerageLink, etc.) inside qualified plans show up twice — once as a line in the parent plan summary ("self-directed: $X") and once as a full position breakdown statement. Match by exact dollar value and parent reference. Mark the child as nested and exclude from the parent's "remaining" total. This is the most common consolidation trap.

- **Owner attribution.** Map each account to a household member via `accounts[].owner` in config. Joint accounts get joint attribution and are split per the user's specified rule.

- **Household reconciliation.** If the user provided a balance-sheet spreadsheet with account-level totals, reconcile each one. Flag mismatches — they usually mean drift between the spreadsheet's last-update date and the statement's date.

- **Manual holdings.** Pull in any `manual_holdings` from config — these are positions that don't have statements (M Units, LTIPs, private investments, real estate). Treat them as first-class positions in the ledger.

- **Real estate.** Apply the methodology specified in config (`carrying` vs `liquidation_net`). For liquidation_net, compute the haircut from cost basis + depreciation + jurisdiction-specific tax estimates per `references/data/re_methodology.md`.

Output: a consolidated `positions.csv` ready for classification.

---

## Phase 4: Classify

**Goal:** Map every holding to an asset class breakdown (through-the-fund), sector breakdown for equity, and distribution character for income.

Read `references/classify.md`. The pattern:

1. **Look up each ticker** in `references/data/fund_asset_class_map.yaml` — the curated registry. Covers the major ETFs and target-date funds (the asset classes underlying VTI, VOO, BND, AGG, PIMIX, common TDFs, etc.).
2. **For unknowns**, two options (configurable):
   - **Prompt user once and persist** (default for interactive runs) — surface a one-shot list of unknown tickers, ask for asset class assignment, write to config's `fund_overrides`.
   - **Web lookup** via Morningstar/issuer site — for batch / non-interactive runs.
3. **Never silently apply a generic mix to an unknown fund.** That makes the analysis look complete when it's actually wrong. Always surface unknowns as caveats on the output.

For **individual stocks**, classify by sector (technology, financials, healthcare, …) using a stock-to-sector registry. Single stocks all map to the appropriate regional equity bucket (typically `us_equity` or `intl_dev_equity`).

For **concentrated alts** (M Units, LTIPs, partnership interests, private equity), map to `alt_concentrated` with the employer / issuer flagged for concentration analysis. These are NOT treated as a diversified asset class.

For **real estate**, map to `real_estate` with `investment` vs `primary` use flag from config.

Surface a single one-shot review list to the user: *"Quick check — N unknown tickers + M edge cases. Confirm or correct in one pass?"* Apply defaults silently for everything else.

Output: enriched `positions.csv` with asset class, sector, expense ratio, income character columns populated.

---

## Phase 5: Report

**Goal:** Produce the full analysis artifact set. **Descriptive only** — no recommendations, no targets, no "should."

Don't enter this phase until classification is complete and unknowns are resolved (or explicitly accepted as caveats).

Read `references/report.md`. Standard outputs:

### A. Allocation breakdown (`Allocation.csv`, `chart_allocation.png`)

Through-the-fund roll-up across the whole portfolio:
- Asset-category totals: equity / fixed income / cash / real estate / alternatives / crypto
- Within equity: US / intl developed / intl EM
- Within fixed income: by issuer/manager (no judgment about which is "better")
- By account / account type
- By owner

### B. Concentration map (`Concentration.md`, `chart_concentration.png`)

Concentration takes several forms — the report breaks them into distinct subsections so the user can tell at a glance which kind they're looking at. Use thresholds from config and **state each threshold inline** in the subsection (e.g., "Above threshold below means more than 5% of investable held in a single stock.").

Subsections (in this order):

- **Largest positions (any kind)** — top line items by gross value, including funds, stocks, properties, cash. A fund flagged here is not single-name risk — it's a large position. Use a `Kind` column to label each row as ETF / Mutual fund / Stock / Real estate / Cash.
- **Single-stock concentration (direct holdings only)** — filter to direct equity holdings (section == `equity`). 5%-of-investable threshold.
- **Single-fund concentration within an asset category** — one fund holding >50% of a category. The fund may be diversified, but the category depends on a single manager.
- **Employer / wrapper credit exposure** — money inside NQDC / profit-units / similar wrappers is structurally an unsecured creditor claim on the employer. Surface as `employer × wrapper × $ × % × flag`. Separately, list direct holdings of the employer's stock — but only when the **ticker's actual issuer matches the employer**, not when the wrapper inherits the employer tag. Use word-boundary token matching on the employer name to avoid false positives (e.g., "America" matching "American Water Works").
- **Property concentration** — each investment property as an undiversified single-asset exposure.

**Not in this section:**
- **Sector breakdown** — lives in the asset-mix section (Section 2 of the report). Sector is a compositional view, not a concentration cut: showing all sectors as a table is the same KIND of breakdown as asset class and geography. Section 2's observation line flags any sector above the 25%-of-equity threshold.
- **Geographic breakdown** — same reason; lives in Section 2.

**"Above threshold" is a fact, not a problem.** Never say "you should reduce X." Say "X sits at Y% of Z, above the configured threshold of W%."

### C. Tax-location audit (`TaxLocation.md`, `chart_tax_location_matrix.png`)

A matrix: asset class (rows) × wrapper type (columns), filled with $ values. Surface where each asset class lives. Annotate with descriptive facts:

- "$X of growth-oriented equity is held in NQDC wrappers"
- "$Y of high-yield bonds is held in taxable accounts"
- "$Z of tax-exempt income is generated"

No "should." Just facts.

**Report rendering (Section 5):** Embed the **heatmap inline + the observations block only**. Do NOT embed the matrix table — it's a direct duplicate of the heatmap. The full matrix lives in `.analysis/TaxLocation.md` for drill-down (cite it in the section's caption).

### D. Fee analysis (`Fees.csv`)

Per-fund expense ratio, holding $, annual fee $, and **share of total fees**. The report's fee table is descriptive without a chart — a fee bar chart in isolation hides notional context (holding size), so the table replaces it. Compute weighted-average ER and call out the single biggest contributor in commentary.

### E. ~~Income & yield map~~ — REMOVED

We don't actually compute income (yield × MV with proper character handling). A table showing "holding value by distribution character" is misleading — it implies income data that isn't there. Do not add an income section to the consolidated report. If estimated income becomes useful later, build it as a proper yield model first.

### F. Anomaly surface (`Anomalies.md`)

Surface the things that look unusual *as observations*, not problems:

- Idle cash positions above a threshold (e.g., > 5% of any account, > 2% of investable)
- Funds with substantially identical exposure held alongside each other (duplicate funds)
- Dust positions (single holdings < $X, useful for the user to see)
- Holdings with missing cost basis
- Account-level reconciliation mismatches vs the household sheet
- Anything tagged `FOLLOW_UP` in the user's spreadsheet config

**Excluded from the consolidated report:** Potential TLH (tax-loss harvesting) pairs. TLH is a tactical action recommendation in disguise — surfacing "swap A for B" in a descriptive report crosses into prescription. Keep it in the raw `Anomalies.md` for drill-down, but do not embed in `Investment Analysis Report.md`.

### G. Consolidated Report (`Investment Analysis Report.md`) — primary artifact

The **single user-facing artifact** is a structured Markdown report **organized around the questions a holder typically asks**, in **top-down narrative order**: aggregate → composition → specifics → risk → context (tax, fees, anomalies).

Section order:

1. **How much do I have, and where does it sit?** — aggregate total + two side-by-side pies (asset category + account)
2. **What's my real asset mix once I look through every fund?** — compositional view: asset-class table + equity geography + fixed-income split + **sector breakdown through-the-fund** (with threshold flag)
3. **What do I actually own?** — specific holdings: top-N ledger with clean names + `Kind` column (ETF / Mutual fund / Stock / etc.)
4. **Where am I concentrated?** — risk-only subsections: largest positions (any kind), single-stock (direct only), single-fund-in-category, employer/wrapper credit exposure, property concentration. **Sector belongs in Section 2, not here** — sector is a compositional view, not a concentration cut.
5. **Where do things sit, tax-wise?** — wrapper × asset-class heatmap + observations only (NOT the matrix table — it's a direct duplicate of the heatmap; matrix lives in `.analysis/TaxLocation.md`)
6. **What's it costing me to hold this?** — fee table with holding-$, ER, annual $, share-of-total
7. **Is anything in the data unusual?** — anomalies (no TLH pairs, no income — see "Removed" notes below)
8. **What changed since last refresh?** — conditional, only on refresh runs

Followed by an Appendix listing companion files and a closing **"Next Step — Build a Financial Plan?"** section.

#### Design principles (apply to every section)

**1. No duplicates between charts and tables.** Every visual and tabular element should convey *different* information. If a chart and a table show the same data in different forms (e.g., the tax-location heatmap and its underlying matrix table), drop one. Drop the redundant element from the *main report*; keep it in `.analysis/` for drill-down.

**2. Top-down narrative.** Section ordering follows aggregate → composition → specifics → risk → context. Don't reverse the flow. Specifically: composition (asset mix) goes *before* specific holdings (the ledger), because the reader's mental model starts with "what's the shape" and then drills into "what are the actual tickers."

**3. Plain language over jargon.** Pick the word a non-finance reader would use. Documented renames:

| ❌ Avoid (jargon) | ✅ Use (plain) |
|---|---|
| Sleeve | **Asset category** |
| Wrapper | **Account type** (with tooltip explaining "tax container — taxable / qualified retirement / Roth / NQDC / etc.") |

"Sleeve" survives only in internal Python variable names (`SLEEVE_MAP`, `sleeve_label`); never in report copy, chart titles, or column headers.

**4. Threshold flags defined inline.** Never show an "Above threshold" column without stating what the threshold is in the same subsection (e.g., "Above threshold below means **more than 5.0% of investable** held in a single stock").

**5. Clean ticker descriptions** via the `name` field in `fund_asset_class_map.yaml` / `issuer` field in `stock_sector_map.yaml`. Fallback for unmapped tickers: regex-clean the raw description (split CamelCase, ALLCAPS→Capital+lower, digit boundaries, re-acronym US/UK/EU after title-casing).

**6. Refer to positions by their resolved issuer**, not by the wrapper they live in. A stock held inside an NQDC wrapper is the issuer's stock, not the employer's stock — unless the issuer actually IS the employer (use word-boundary token matching to avoid false positives like "America" matching "American Water Works").

**7. Charts inline only when they add information.** Default inline set: the **asset-category pie + account pie** (Section 1, side-by-side) and the **tax-location heatmap** (Section 5). Other charts (asset-class bars, concentration heat, fee bar, income breakdown) get generated but are NOT embedded inline — they would duplicate the section's table. They live in `.analysis/` for browsing.

**8. Short observation block** after each section's data — descriptive only ("largest asset category is X at Y%", "weighted-average ER is X bps"). No "should", no comparisons to a target.

Topics that are fair game in observation blocks: notable concentrations, where assets are located, idle / duplicated / dust patterns, anything genuinely surprising in the data.

Topics that are NOT fair game: what the user should do about anything, comparisons to a "target" allocation, recommendations of any kind.

### H. Charts

Default chart set (PNG, cream background, muted palette, same aesthetic as `expenses`):

1. **Asset category allocation pie** (`chart_allocation_pie.png`) — embedded inline in Section 1
2. **Account pie** (`chart_account_pie.png`) — embedded inline in Section 1, colored by each account's dominant asset category for visual consistency with chart #1
3. **Tax-location matrix heatmap** (`chart_tax_location_matrix.png`) — embedded inline in Section 5
4. **Asset class breakdown bar** (`chart_asset_class_bars.png`) — generated, not embedded (Section 2 table covers it)
5. **Concentration heat map** (`chart_concentration_heat.png`) — generated, not embedded
6. **Fee load bar** (`chart_fees_bar.png`) — generated, not embedded (Section 6 table covers it)
7. **Income breakdown** (`chart_income_breakdown.png`) — generated, not embedded (income section removed from report)
8. **Sankey: accounts → wrappers → asset classes** (`chart_sankey.html`) — interactive HTML, referenced from Appendix only

Run via `python scripts/generate_charts.py <work_folder>`.

---

## Output

### Folder layout

Keep the user's source folder clean. At the root of the input folder, only deliverables + the user's own files should live:

```
<user-folder>/
├── <statement files>           ← user's own statements (PDFs/CSVs)
├── Investment Analysis Report.md   ← primary deliverable
├── Investment Positions.csv        ← user-facing flat ledger
├── investment_analysis_config.yaml ← config (re-read on refresh)
└── .analysis/                  ← all intermediates and drill-down
    ├── raw_positions.csv
    ├── positions.csv
    ├── positions_classified.csv
    ├── statements_meta.json
    ├── Allocation.csv
    ├── Concentration.md
    ├── TaxLocation.md
    ├── Fees.csv
    ├── Anomalies.md
    ├── consolidation_summary.md
    ├── _analyze_summary.json
    ├── chart_*.png             ← all chart files
    └── chart_sankey.html
```

The `.analysis/` subfolder is created automatically by the scripts. Refresh runs read from and write to it without disturbing the deliverables at the root.

**Why this layout:** the deliverables (Report, Positions ledger, Config) are what the user opens. Hiding 20+ intermediate files behind a `.` subfolder keeps the source folder browsable, while keeping everything co-located so refresh runs work without configuration. The `.` prefix matches `.git`, `.venv`, etc. — universally understood as "tooling state, not user content."

**Auto-open:** when `generate_report.py` finishes, it opens `Investment Analysis Report.md` in the user's default Markdown viewer (`open` on macOS, `xdg-open` on Linux, `start` on Windows). Pass `--no-open` to suppress.

**Legacy migration:** if a prior run wrote intermediates to the folder root (older layout), `generate_report.py` migrates them into `.analysis/` on first invocation. Idempotent — safe to run repeatedly.

### Primary artifact (static report)

The primary deliverable is **`Investment Analysis Report.md`** at the root of the user's working folder — a structured, section-numbered Markdown report with inline tables, inline charts (referenced as `.analysis/chart_X.png`), and short per-section commentary. Companion CSVs and MDs in `.analysis/` provide drill-down material referenced from the report's Appendix.

### For interactive slice-and-dice

The skill **does not** ship a bespoke interactive dashboard. An earlier attempt (Streamlit, then ported to Dash) consistently fought the user — chart click events, cross-filter state, browser caching, and Dash/Streamlit callback wiring all proved too brittle relative to the value delivered.

The right answer for true BI-style exploration is **PowerBI Desktop, Tableau Public, or similar** pointed at `Investment Positions.csv` in the user's source folder. These tools are mature, polished, and handle the cross-filter UX better than any bespoke Python dashboard I'd build in a few iterations. The static report covers the standard descriptive questions; interactive exploration goes to a dedicated BI tool.

If asked to build a dashboard, push back politely and recommend the BI-tool path instead. The lesson from the prior attempt: don't reinvent BI on top of a notebook framework.

In your chat-side wrap-up, give the user a tight summary:

- Total investable + total household net worth (with the split clearly labeled)
- Asset-category breakdown
- Top 3–5 concentrations against threshold (as facts)
- Number of anomalies / follow-ups flagged
- Pointer to `Investment Analysis Report.md`

Save all artifacts in the user's working folder. Provide `computer://` links so they can open them.

**End with the financial-plan transition** — both in `Investment Analysis Report.md`'s closing section and in your chat-side wrap-up:

> *"Would you like to start building a financial plan?"*

Frame it as the natural next step: this analysis describes **what is**; a financial plan turns that into **what to do** by adding spending, goals, horizon, and risk tolerance. Do **not** offer recommendations directly — even if the user pushes, route back to "that needs the planning layer with your goals + spending."

If the user explicitly says "no, I just want to drill into the current state" — that's fine, take the open-ended drill-down route. The financial-plan offer is the default close, not a forced one.

---

## Common pitfalls

**1. Double-counting nested wrappers.** A self-directed brokerage (PCRA, BrokerageLink) inside a 401(k) issues its own statement. Both the parent plan statement and the child PCRA statement show the same dollars. Match by exact value + parent reference; mark the child as nested. Test: the parent's "remaining in core fund" total + child's total should sum to the parent's grand total.

**2. Silently classifying unknown funds as "diversified."** Looks complete; actually wrong. Always surface unknowns. The asset class assignment for the user's largest holdings shouldn't be a guess.

**3. NQDC and rabbi-trust assets.** Non-qualified deferred comp wrappers (NQDC, EDCP, etc.) hold investments in accounts that are technically the *employer's* general assets, not the employee's. From a portfolio perspective they look like regular brokerage; from a credit perspective they're unsecured exposure to the employer. Surface the wrapper type, but don't conflate it with firm-failure risk in the holdings themselves (a PIMCO mutual fund held in a Schwab brokerage account is NOT employer credit risk, even if the employer is PIMCO).

**4. Pension fragments.** Users often have small pension balances scattered across former employers. Each one individually is noise; in aggregate they can be meaningful. Always aggregate and surface the total, not just the line items.

**5. Single-stock long tails.** Taxable brokerage accounts often contain accumulated dust — 20+ single-name positions of $50–$500 each from DRIP, employer transfers, or direct indexing residue. These don't affect allocation materially but DO inflate the row count and clutter analysis. Surface as "long tail" anomaly with the count and total $.

**6. Real estate methodology drift.** If the user reports "net equity" as MV − Mortgage on a balance sheet but you analyze it as liquidation-net (with cap-gains haircut), the numbers won't match the user's mental model. Always honor the config-specified methodology and surface it explicitly.

**7. Spreadsheet vs PDF as canonical source.** When both exist, treat the spreadsheet as canonical for *account-level totals* and the PDFs as canonical for *line-item composition*. Reconcile the two; flag mismatches as a data-freshness issue (one is usually older).

**8. Treating concentrated alt positions as "alternatives."** M Units, partnership profit units, LTIPs, restricted stock, and similar concentrated comp vehicles are NOT diversified alts. Classify them as `alt_concentrated` with the issuer tagged. Concentration analysis must surface them alongside direct equity holdings of the same issuer, not as a separate "alts" bucket.

**9. Forgetting the unvested layer.** LTIPs, RSUs, and similar unvested awards are not the user's money today but represent meaningful economic exposure. Surface both views: "vested only" and "vested + unvested." Never include unvested awards in a default investable total without labeling.

---

## Files in this skill

- `SKILL.md` — this file
- `references/interview.md` — Phase 1: interview script + opening questions
- `references/ingest.md` — Phase 2: per-source extraction patterns (PDF, CSV, spreadsheet)
- `references/consolidate.md` — Phase 3: account type inference, nesting dedup, owner attribution
- `references/classify.md` — Phase 4: through-the-fund mapping, unknown fund handling
- `references/report.md` — Phase 5: artifact specs + chart definitions
- `references/data/fund_asset_class_map.yaml` — curated ticker → asset class registry
- `references/data/account_type_taxonomy.yaml` — canonical account types + inference heuristics
- `references/data/distribution_character.yaml` — qualified vs ordinary vs muni vs return-of-capital rules
- `references/data/thresholds.yaml` — default concentration thresholds
- `references/data/re_methodology.md` — real estate carrying vs liquidation-net computation
- `scripts/extract_positions.py` — PDF/CSV/spreadsheet ingestion + per-statement reconciliation
- `scripts/consolidate.py` — dedup, account type inference, owner attribution, household reconciliation
- `scripts/classify_funds.py` — through-the-fund mapping, unknown fund flagging, web_lookup orchestration
- `scripts/lookup_fund.py` — auto-resolve unknown tickers via Yahoo/Morningstar fact sheets + Claude parsing (enabled by `classify.unknown_fund_behavior: web_lookup`)
- `scripts/analyze.py` — concentration, tax-location, fees, income, anomalies
- `scripts/generate_charts.py` — chart pack (matplotlib + optional plotly for sankey)
- `scripts/generate_report.py` — write all artifact files
- `assets/example_config.yaml` — example `investment_analysis_config.yaml` (generic, no PII)
- `evals/` — synthetic statements + expected outputs
