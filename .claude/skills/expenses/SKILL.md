---
name: expenses
description: Interview-driven workflow for turning a pile of raw credit-card and bank exports into a single consolidated, categorized, person-attributed expense ledger — and then analyzing it. Use this whenever the user wants to understand their household spending, build a personal budget, prepare for a financial review, or audit categories from a previous import. Trigger on phrases like "where is my money going", "consolidate my expenses", "categorize my transactions", "build a budget", "spending breakdown", "lifestyle expenses", "TTM spend", "split spending by person", or whenever the user drops a folder of card/checking CSVs and wants to make sense of them. Also trigger when the user asks to revise an existing expense classification ("move X to category Y", "drop work-trip charges from lifestyle", "split this row into kids vs travel") — the skill's iterative cleanup loop is built for exactly that.
---

# Expenses

## What this skill does

Walks the user from raw expense exports → a single consolidated, categorized, person-attributed expense ledger they can analyze. The skill is **interview-driven**: ask the user about their setup, get them to drop files, run the pipeline, fix mistakes iteratively, and produce useful analyses.

The output is a clean CSV (or DataFrame) with this schema:

| Column | Meaning |
|---|---|
| Date | Transaction date |
| Source | Which account/card the row came from (e.g., "Alex AmEx", "Partner Chase") |
| Description | Merchant or transaction description |
| Category | Top-level category (Food & Dining, Travel, Housing, …) |
| Subcategory | Sub-bucket (Restaurants, Hotels, Mortgage, …) |
| Amount | Positive = outflow. Refunds/credits = negative. |
| Original Category | Audit field — what the source bank called it |

Plus the `Person` attribution is encoded inside `Source` (e.g., "Alex AmEx" vs "Partner AmEx") so analyses can split by person without a separate column.

## When to trigger

Fire this skill when the user wants to do **any** of:

- Understand where their money is going (last 12 months, YTD, last quarter, etc.)
- Consolidate exports from multiple cards/accounts into one view
- Categorize uncategorized transactions (their bank's categories are usually too coarse)
- Split spending by person (couples, household members)
- Drill into a category ("show me everything in Food & Dining")
- Cluster trip-related spend into discrete trips
- Find recurring subscriptions
- Audit and fix mistakes in a previous categorization

If the user is mid-flow and just wants to fix a single misclassification, jump straight to the **Cleanup loop** section.

## The six phases (agent-internal vocabulary — NEVER show to the user)

Phases are scaffolding for *you*. The user should never see "Phase 4 → Phase 5" or be told they're "in Phase 6." Use natural transition prompts instead (see below). The user experiences a smooth journey from "drop your files" to "here are your decisions" without numbered checkpoints.

| # | Phase | Mode | Termination signal |
|---|---|---|---|
| 1 | **Interview** | Discovery | User confirms setup summary |
| 2 | **Consolidate** | Mechanical | All sources ingested + exclusions reported |
| 3 | **Tag** | Mechanical | Every row has `(Category, Subcategory)` |
| 4 | **Cleanup** | Data hygiene | **Misc < 5%** + no new flagged rules |
| 5 | **Analyze** | Pattern discovery | User has pulled the threads they care about |
| 6 | **Actions** | Decision support | User commits to actions or explicitly opts out |

**Hard gates matter (internally):**
- **Gate 4→5** — don't analyze numbers you don't trust. Loop within cleanup until Misc is small and stable.
- **Gate 5→6** — analysis without actions is trivia; actions without analysis is gut-feel.

### User-facing transition prompts

End every phase by hinting at what's next, in plain language. Never name the phase.

| Internal transition | What you say to the user |
|---|---|
| 1 → 2 | *"Got it — pulling [N sources], [time window], excluding [X]. Confirm or correct anything before I run."* |
| 2 → 3 | *(silent — runs inside the script)* |
| 3 → 4 | *"First pass done. Misc is $X (Y%). Auto-classifying the top merchants now…"* |
| 4 → 5 (gate) | *"Cleanup's looking solid — Misc at 2.3%. Want to dig into the patterns now? I can start with a person split + the headline, or jump to a specific question (or skip straight to candidate actions)."* |
| 5 → 6 (gate) | *"Pulled the threads worth pulling. Want me to turn any of these into things you could act on — keep, change, or revisit later? Or call it here?"* |
| 6 → done | *"Saved your decisions. [N] committed, [N] snoozed, [N] left as-is. See you at next refresh."* |

**Banned vocabulary in user-facing copy:** "Phase 4," "Phase 5," "the gate," "termination signal," "phase transition." These are agent terms.

**Allowed and encouraged:** "cleanup," "analysis," "actions," "patterns," "candidates," "next step." These are user-facing concepts.

### Option-menu format (when offering next steps)

When you offer the user a choice of what to do next, use a numbered table with two columns: `#` and `Option` plus a `What it is` description in plain English. Then end with a one-line recommendation.

**Required:**
- **Number the options** (1, 2, 3…). Lets the user reply "1" or "1 then 2" tersely.
- **"What it is" is plain English** — describe the mechanic and the value, not the internal workflow.
- **Every option is a positive action.** No "Stop," "Do nothing," "Cancel" sentinels. The user can always just stop talking; that doesn't need to be a numbered choice.
- **Maximum 4 options.** More than that and the user has to read instead of decide.
- **End with a recommendation,** specific and short: *"My pick: 1 → 2."* Or *"Skip 3 unless tax prep is on your mind."*

**Banned in option menus:**
- Phase numbers (`Phase 6`, `the actions phase`).
- Internal jargon (`gate`, `termination signal`).
- Time estimates as a column unless the user explicitly asked. Most options take "a few minutes" — surfacing it adds noise.

**Example shape:**

> | # | Option | What it is |
> |---|---|---|
> | 1 | **Find optimization candidates** | I pick the 3–5 biggest patterns and frame each as: dollar impact + a question. You decide keep / change / revisit. |
> | 2 | **Subscription audit** | Scan every source for recurring charges. Flag forgotten or duplicated ones. |
> | 3 | **Save & commit** | Write a short README explaining how to refresh next quarter. |
>
> My pick: 1 → 2 → 3.

Detailed instructions for each phase live in `references/` — read the relevant file when you enter that phase.

## Second-visit flow (return user — refresh, not redo)

**Always check first:** does the user's working folder already have an `expenses_config.yaml` + `Lifestyle Expenses.csv` + `DECISIONS.md` from a prior session? If yes → this is a **refresh**, not a new setup. Skip the interview and offer:

> "I see you ran this before — your config has [N] exclusions and [M] overrides from last time. Drop your fresh CSV/PDF exports in the same folder and I'll re-run with the same rules. Want to add or change anything before I run, or just refresh as-is?"

Read `DECISIONS.md` *before* asking any question — every rule there was already confirmed. Don't re-ask:
- "Who's in the household?" — already in config's `people` list.
- "What's your time window?" — already in config's `time_window`.
- "Any rental properties?" — visible from existing `exclusions` rules.
- "Is X a contractor or family?" — visible from existing `overrides`.

The right second-visit conversation is short:
1. Re-run consolidation against the new month's data.
2. Surface any *new* Misc clusters that didn't exist last time.
3. Show the headline number and category roll-up (with a "vs last refresh" delta if the prior CSV is still around).
4. Stop.

---

## Phase 1: Interview

**Goal:** Learn the user's accounts, who's in the household, what time period they care about, and what they want to exclude. Don't read any files yet — answers shape what to read.

Read `references/interview.md` for the full question list. Briefly:

- **Open with an outcome hook + privacy note before the first question.** Lead with what the user *gets* (clear picture of where money is going, anomalies, optimization opportunities) and address the privacy concern up front: files stay on local disk; transaction text does flow through the API for analysis (be honest about that — don't pretend it doesn't); per Anthropic's published policy API conversations aren't used for training by default, but phrase that as Anthropic's policy, not as your guarantee. Point users at the privacy policy if they want stricter assurance. See the exact wording in `references/interview.md`.
- **Account-type coverage:** Prompt the user with a checklist of *types* (all credit cards, all checking, joint accounts, any business/work cards to exclude) — not a list of specific institutions. The point is to nudge them to remember accounts they'd miss; institutions are detected from filenames and headers later. Be explicit that **CSVs are preferred but PDFs are accepted** — many users only have PDF statements, and the skill handles them (auto-installs `pdfplumber` on first PDF source).
- **Time period:** "Last 12 months" is the default (a rolling window from today; finance shorthand "TTM"). Ask if they want a different window. **Always say "Last 12 months" in user-facing copy** — never "TTM".
- **People:** Who's in the household? (Names map to the `Source` field downstream)
- **Exclusions:** Are any cards used for business/work expenses that should be reimbursed and excluded? Any rental properties whose income/expenses live in their own P&L? Investment transfers that would double-count if treated as spend?
- **Existing categorization?** Auto-detect first — if a categorized file (e.g., `Lifestyle Expenses.csv`) is already in the folder, preserve its taxonomy. Only ask if absent.

**Never expose source-format quirks** ("Apple Card has a quirky Type column", "Chase has AUTOMATIC PAYMENT rows", etc.) in user-facing prompts. That detail is agent-only and lives in `references/consolidate.md` and `scripts/consolidate.py`.

Use the `AskUserQuestion` tool when there's genuine ambiguity. Don't over-interrogate — five questions max in the opening round. The cleanup loop catches what the interview misses.

After the interview, write a one-paragraph **setup summary** back to the user and ask for confirmation before processing files. This catches misunderstandings early.

---

## Phase 2: Consolidate

**Goal:** Ingest each source, normalize columns, exclude non-lifestyle rows, produce one combined DataFrame.

Read `references/consolidate.md` for source-specific patterns (Apple Card, Chase, generic bank checking, Capital One, etc.). The reference doc covers:

- Apple Card's quirky `Type` column (Purchase / Credit / Debit / Other / Payment / Installment) — only some are real expenses
- Chase's "AUTOMATIC PAYMENT - THANK YOU" rows that look like Payment but are card payoffs (exclude) vs. merchant refunds also tagged Payment (include with negative amount)
- Generic checking accounts: positive vs. negative sign convention, how to identify card-payoff rows that would double-count
- How to handle joint vs. individual accounts and attribute to people

The output of this phase is a single DataFrame with **uniform columns**:
`Date | Source | Desc | OrigCat | Amount`
(Amount sign convention: **positive = outflow**.)

**Use the bundled script** `scripts/consolidate.py` rather than rewriting per session. It takes a YAML config that the interview phase produces. See `assets/example_config.yaml`.

**Common exclusions** (do these once, document why):

- Credit-card payments from checking → already counted on the card side
- Investment transfers (Schwab, Vanguard, brokerage funding) → not consumption
- Tax payments (IRS, state, property) → separate from lifestyle
- Rental property mortgage / management / insurance → its own P&L
- Reimbursable work trips — hotel, flight on the work card or work travel days

When in doubt, ask the user. **Always** report what was excluded and the dollar amount, so the user can challenge it. A line like "Excluded $4,200 in card-payoff rows from checking to avoid double-counting" tells them what you did and why.

---

## Phase 3: Tag

**Goal:** Apply category and subcategory to every row.

Read `references/taxonomy.md` for the default category list and assignment rules. The default taxonomy:

```
Housing            (Mortgage, Property Tax, Utilities, Home Improvement, Insurance, …)
Food & Dining      (Groceries, Restaurants, Coffee, Food Delivery, Misc)
Travel             (Airlines, Hotels, Car Rental, Lodging/Booking, Ski, Card Travel Credit, …)
Auto & Transport   (Fuel, Tolls, Auto Service, Ride Share, Parking, …)
Kids               (Schools, Camps, Activities, Toys, …)
Health             (Medical, Dental, Pharmacy, …)
Personal Care & Fitness
Shopping & Retail  (Amazon, Big Box, Clothing, Home Goods, Electronics, …)
Subscriptions & Software
Entertainment
Pets
Home Services
Professional Services
Insurance
Charity & Gifts
Fees
Cash               (ATM withdrawals — opaque)
Misc               (everything that didn't match — see Cleanup)
```

**Tagging strategy** (in order of preference, fastest to slowest):

1. **Trust the source bank's category** if it's specific (Apple Card's "Restaurants", "Grocery", "Gas" are surprisingly good). Map to your taxonomy.
2. **Merchant keyword matching** — the bulk of the work. See `references/taxonomy.md` for the keyword tables.
3. **One-off overrides** by (Date, Description, Amount) — for user-confirmed exceptions like "this REI charge was a gift, not personal gear".
4. **Misc** for everything that didn't match — these are the rows the user fixes in Phase 4.

**Persistence is critical.** Every override the user confirms in Phase 4 should be added to the keyword tables or the override list, so the next refresh categorizes correctly without re-asking.

Use the bundled `scripts/consolidate.py` — it has the keyword tables built in. Modify the tables, don't rewrite the script.

---

## Phase 4: Cleanup

**Goal:** Get the labels right. Misc < 5%, recurring rules persisted in YAML so refreshes are stable.

Read `references/cleanup.md` and `references/misc_classify.md`. The pattern:

1. Run `consolidate.py --export-misc` — writes `misc_clusters.csv` (top merchant stems by total).
2. **Apply best-guess defaults silently** (LLM-driven) — write rules to the user's YAML overrides as a single auto-classified block. See `misc_classify.md` for the prompt template.
3. Re-run `consolidate.py` (no flag) to apply.
4. Show the user: post-fix breakdown + items that genuinely need their input (Zelle to a *person's name*, generic Apple Card descriptions like "Charge"/"Advanced", foreign-language merchants, ambiguous one-offs).
5. Loop until Misc < 5% and the user stops flagging issues.

**Don't conflate cleanup with analysis.** Cleanup is mechanical (fix wrong labels). Analysis (Phase 5) is interpretation (what do these labels tell us?). The user's mental mode is different — don't mash them together. Surface excluded-items audit + Misc-needs-input here, not category drill-downs or trip clustering.

**The persistence step matters** because users will refresh their data monthly or quarterly. If their fixes don't survive a refresh, they'll stop trusting the output. Always confirm the persistence path (`expenses_config.yaml` overrides) is updated before declaring a fix complete.

**Termination signal:** Misc < 5% AND no new flagged rules. Then stop, commit, move to Phase 5.

---

## Phase 5: Analyze

**Goal:** Surface patterns the user can't see by eyeballing the CSV. Pure pattern discovery — no recommendations yet.

Don't enter this phase until **Phase 4 termination** is hit (Misc < 5%, no new rules pending).

Read `references/analyze.md` for the standard analyses:

- **Headline summary** by category — what they ran the workflow for
- **Person split** (one bar per household member, derived from the `people:` list in the user's config) — part of the default summary
- **Drill-down** into any category — sorted by amount, top merchants
- **Trip clustering** — group Travel into discrete trips by date proximity + merchant signal
- **Recurring subscriptions** — same merchant, regular cadence
- **Time-period filters** — Last 12 months vs YTD vs by month, YoY compare
- **Anomaly surfacing** — single transactions over $1k, categories that ballooned

**Format every user-facing summary as a markdown table.** Right-align amounts (`|---:|`), include a Share/% column on category rollups, put a one-line headline above the table. The script's `print()` output is monospace text for *you* to parse — translate before showing the user.

**Don't dump every analysis at once.** Run the headline + person split as defaults, then offer threads: "want trip clustering, recurring subs, or a drill into Housing?" Let the user pull on threads.

**Termination signal:** the user stops asking for new threads. Then propose moving to Phase 6.

---

## Phase 6: Actions

**Goal:** Convert patterns from Phase 5 into 3–5 candidate decisions the user can act on, snooze, or reject. This is decision support, not a lecture.

Don't enter this phase until **Phase 5** is winding down (user has seen the patterns and isn't pulling new threads).

Read `references/actions.md`. The shape:

1. Pick 3–5 patterns from Phase 5 that have non-trivial dollar impact (rule of thumb: > 0.5% of total spend) AND a clear potential action.
2. Frame each as **observation + dollar impact + question**, not as advice. Don't tell the user how to live; show them the number and ask if it matches intent.
3. User commits, snoozes, or rejects each. Output is a short action list (or empty).

**Don't lecture.** "You spent $X on Y" is information. "You should spend less on Y" is unwelcome opinion. The user knows their own values; you don't.

**Don't double-classify.** A row that already lives in the right category in Phase 4 doesn't need reclassifying here — actions are about decisions on labeled data, not relabeling.

**Termination signal:** the user has committed, snoozed, or rejected each candidate. Save the action list (or "no changes") and stop.

---

## Common pitfalls

**1. Apple Card's `Type=Payment` rows.** These are card payoffs from checking — exclude them on the card side. But Chase uses `Type=Payment` for *both* card payoffs (exclude) and merchant refunds (include with negative amount). Distinguish via description: "AUTOMATIC PAYMENT - THANK YOU" = payoff; anything else with `Type=Payment` and a negative amount = merchant refund.

**2. Apple Card "Daily Cash Adjustment" rows.** When a purchase is refunded, Apple reverses the cashback as a positive-amount "Daily Cash Adjustment". This affects the *Daily Cash balance*, not the user's expense total — drop these rows.

**3. Apple Card installment plans.** A single big purchase can show up as one parent row plus N monthly installment rows. Including both double-counts. Drop the installment rows and keep the parent purchase.

**4. Sign conventions differ across sources.** Apple Card and Chase use positive=charge, negative=refund. Most checking accounts use negative=outflow. Normalize to **positive = outflow** before combining.

**5. Joint vs. individual accounts.** A joint Chase card with two cardholders needs the cardholder column read for person attribution. Individual cards just inherit the account holder's name. Ask in the interview.

**6. Rental property contamination.** If the user has a rental, its mortgage / property tax / management fees / insurance might be paid from the same card or checking account. These should live in the rental's P&L, not lifestyle. Identify them and exclude.

**7. Work-trip reimbursables.** A hotel charged on a personal card while traveling for work isn't personal consumption — it's a temporary loan to the employer. Confirm with the user and exclude (also: flag for the user to submit for reimbursement).

**8. Refunds and credits.** These should be **negative-amount rows** in the same category as the original purchase. Don't drop the original — net it. This preserves the audit trail. See `scripts/apply_refunds.py`.

---

## Output

End with a **clear summary** that includes:

- Last 12 months total spend
- Category roll-up (top 5–8 categories by amount)
- Person split if applicable
- Excluded amounts and why
- Open questions / Misc rows for the user to confirm

Save the final dataset as **`Lifestyle Expenses.csv`** (or `<custom name>.csv` if the user prefers) in the user's selected folder. Provide a `computer://` link so they can open it.

---

## Files in this skill

- `SKILL.md` — this file
- `references/interview.md` — Phase 1: interview script and the 5 opening questions
- `references/consolidate.md` — Phase 2: per-source ingestion patterns
- `references/taxonomy.md` — Phase 3: default category list and keyword tables
- `references/cleanup.md` — Phase 4: fix-and-persist loop (data hygiene only)
- `references/misc_classify.md` — Phase 4: LLM-driven Misc classification (batch via clusters)
- `references/analyze.md` — Phase 5: standard analyses + how to run them
- `references/actions.md` — Phase 6: convert patterns into candidate decisions
- `scripts/consolidate.py` — config-driven consolidation. `--export-misc` writes a cluster table for the LLM cleanup step. Emits visibility-gap warnings, statement-summary calibration warnings, and structural anomaly checks (loan-payment drift, multiple loan-shaped streams, orphan airfare) on every run. Refresh-delta auto-activates when the previous output exists in the same folder — surfaces new/removed rows and category-level dollar deltas.
- `scripts/analyze.py` — common analyses callable from a prompt. Includes smarter trip clustering that filters home-base merchants (≥5 distinct months) and folds in only one-off non-Travel charges as trip extras.
- `scripts/charts.py` — generate 10 editorial-style PNGs plus a Person → Category → Subcategory Sankey (`chart_11_sankey.html`) from a Lifestyle Expenses CSV. Run as `python charts.py "Lifestyle Expenses.csv" --config expenses_config.yaml` (config flag is optional but lets the chart auto-detect the household's `people:` list). PNG charts use matplotlib (cream background, muted palette, Georgia serif titles, horizontal-only gridlines). Sankey uses plotly (an *optional* dependency — if `plotly` isn't installed, the Sankey step is silently skipped and the PNGs still render). To enable: `pip install plotly`.
- `scripts/apply_refunds.py` — refund/credit netting (idempotent)
- `assets/example_config.yaml` — example interview output → consolidation config (shows `kind:` exclusion sub-types)
- `assets/default_taxonomy.yaml` — default category taxonomy
