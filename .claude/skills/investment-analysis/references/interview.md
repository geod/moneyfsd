# Interview

The interview's job is to learn just enough to set up the analysis correctly. Don't ask everything upfront — five questions max. The classify and report phases catch whatever the interview misses.

This skill is **descriptive only**. The interview should set expectations accordingly: the output describes the current state, never tells the user what to do. If the user asks for recommendations during the interview, redirect — see the "Out of scope" section below.

## The five opening questions

Ask these via `AskUserQuestion` (or just inline if conversation is flowing). Adapt phrasing to context.

### 1. Account-type coverage

> "Sure — let's get you a clear picture of what you own, where it sits across accounts, how your asset mix actually breaks down through every fund, where your concentrations are, and where anything looks off. The output is a single consolidated position ledger plus an analysis pack (allocation, concentration, tax-location, fees, anomalies). It's strictly descriptive — what *is*, not what to *do*.
>
> Quick note on privacy: your statement files stay on your local disk and the analysis is written next to them — nothing gets uploaded to a server. Security descriptions and holding values flow through Claude during analysis (that's how I read them); per Anthropic's published policy, API conversations aren't used to train models by default, but if you're on a specific plan or want to verify, check Anthropic's privacy policy directly.
>
> To start, grab statements from every *type* of account where you have material assets:
> - Retirement plans — current and former employers (401(k), 403(b), 457, etc.)
> - Pensions — defined benefit, cash balance, traditional pensions
> - IRAs — traditional, Roth, rollover, SEP, SIMPLE
> - Direct brokerage / taxable accounts
> - Employer compensation wrappers — deferred comp, RSUs, options, restricted stock, partnership / profit units
> - Health Savings Account (HSA)
> - Education accounts (529, Coverdell)
> - Cash savings (separate from operational checking)
> - Crypto / digital assets
> - Real estate held as investment (rentals, raw land, syndications)
> - Private investments (PE, venture, angel, real estate partnerships)
>
> I'll accept what I can get — **CSVs and Excel exports are preferred (cleaner, more accurate), but PDF statements are okay too** (I'll extract them; expect a bit more cleanup). If you already maintain a balance-sheet spreadsheet that lists every account's total, drop that in alongside the statements — I'll use it as a consistency check.
>
> Drop everything in one folder and tell me the path. I'll inventory the folder and figure out which file is what."

**Why the hook:** Lead with the user's *outcome* (consolidated view, allocation, concentration, anomalies). Set the descriptive-only expectation explicitly in the opening — saves having to redirect later when the user inevitably asks "so what should I buy?"

**Why the privacy note:** People hesitate to share financial holdings with an LLM. Address upfront, honestly:
- Files stay local — true; the script reads them in place and writes output next to them.
- Security/holding text flows through the API — also true, worth saying.
- Training claim — phrase as Anthropic's stated policy, not as your personal guarantee. Point users at the policy.

**Why coverage checklist:** Its purpose is to nudge memory for account *categories* the user might forget — small old-employer 401(k)s, a spouse's pension, a forgotten HSA from a prior job, cash sitting in a savings account separate from checking. Do NOT list specific institutions ("Schwab, Fidelity, Vanguard…") — the user already knows what they bank with, and naming custodians biases the conversation and adds noise.

**Format stance:** Be explicit upfront that PDFs are accepted. Many users only have PDF statements (especially for retirement plans and pensions, which often don't offer CSV export). If you only mention CSVs, users assume PDFs aren't supported. The PDF path is more error-prone, so nudge toward CSV / Excel when feasible — but never block on it.

**Why mention a balance-sheet spreadsheet:** Many users with material assets maintain their own consolidated tracker. That spreadsheet is usually MORE current than the statements (which are quarterly), and it surfaces accounts the user might forget to grab a statement for. Treating the spreadsheet as a parallel input lets the skill cross-check: line-item composition from the statements, account-level totals from the spreadsheet. Mismatches indicate data-freshness drift worth flagging.

**Do NOT expose source-format quirks to the user.** Things like "Schwab statements bury cost basis in a footnote on page 3" or "Fidelity uses CUSIPs not tickers for some line items" or "NQDC plans nest a PCRA statement inside the qualified plan summary" are agent-only knowledge. They live inside `scripts/extract_positions.py` and `references/ingest.md`. Surfacing them in interview options leaks implementation detail and clutters the user's decision.

After the user drops the folder, inventory it and read filenames + first-page text to detect custodians and account types. Only ask about ambiguities you can't resolve from the files.

### 2. Household structure & owner attribution

> "Who's in the household, and whose accounts are whose? I need this for ownership attribution on every position."

Probe (compactly) for:

- **Members** — primary, spouse, partner; any minor children with 529s in their name.
- **Joint accounts** — which ones, what's the attribution rule (50/50 default, but couples sometimes split differently).
- **Trust structures** — if any accounts are owned by a revocable trust, irrevocable trust, or LLC, ask the user to flag them; the analysis can still proceed but the wrapper type matters.
- **Other people on the statements** — sometimes a deceased relative's account is in transition; sometimes a parent is on a custodial account. Ask the user to point these out so they don't get treated as primary household assets.

**Why:** Drives the `Owner` field on every position. Joint accounts get joint attribution and are split per the user's specified rule. This isn't a place to assume — get it right once and the rest of the analysis just works.

### 3. What's not on the statements

Statements show *what's in the account* but routinely omit several things that materially affect analysis. Ask in one compact block:

> "A few things that don't usually show up on statements that I need direct input on (skip anything that doesn't apply):
>
> 1. For any 401(k) / 403(b): what's the **Roth vs Traditional split** inside it? (Most plans don't break this out on the statement.) If you don't know off the top of your head, the workplace login usually shows it in 30 seconds.
> 2. For any **deferred compensation** plan (NQDC, EDCP, etc.): when do distributions start, and is it a lump sum or installments? This affects how the wrapper gets characterized.
> 3. For any **restricted comp** (RSUs, LTIPs, options, profit units): roughly what's vested today vs not, and what are the vest dates for the unvested layer?
> 4. For the **HSA**: is the balance invested, or sitting in a cash sweep?
> 5. For any **investment real estate**: rough cost basis and accumulated depreciation per property, if you've got them handy. (Don't dig deep — a ballpark is fine.)
> 6. Anything else that's an asset but doesn't have a statement — held-direct crypto, a private business stake, an angel position?"

Apply defaults silently for anything the user doesn't answer. Defaults:

- Roth/Traditional split → 100% Traditional (most common; flag for follow-up)
- NQDC schedule → unknown (flag for follow-up — affects wrapper risk characterization)
- Vesting status → all listed values assumed vested unless user indicated otherwise
- HSA composition → cash sweep (most conservative; flag for follow-up)
- RE cost basis → unknown; use carrying methodology by default

**Never make the user defend not knowing.** "I'll mark that as unknown and proceed" is the right response, not a follow-up question.

**Why this matters:** Several of these are inputs that affect downstream classification and the tax-location audit. Getting them now is cheap; backfilling them later means re-running classification.

### 4. Property gate

> "Other than your primary residence, do you own any investment real estate? Rentals, raw land, syndications, fractional / DST positions?"

If **no** → skip to Question 5.

If **yes** → for each property, drag out:

1. Address or alias (the user names it however they want, e.g. `rental_property_1` or "the Brooklyn place" — the skill uses the alias, never stores the actual address)
2. Approximate current market value
3. Mortgage balance, if any
4. **Methodology choice:** carrying (MV − Mortgage) vs liquidation_net (MV − Mortgage − ~6% selling costs − cap-gains estimate − depreciation recapture). Carrying is the default; liquidation_net is for "what could I actually deploy if I sold tomorrow." The two answer different questions; pick once and stay consistent across runs.
5. Use flag — primary, investment, or vacation/second home. Primary residence is typically excluded from the *investable* portfolio analysis (it's a lifestyle asset) but included in net-worth views.

**Why:** Real estate is the largest single thing not on a brokerage statement. Without these answers, the analysis under-states the household balance sheet. Without the methodology choice, the analysis's numbers won't match the user's mental model (their balance sheet usually shows carrying values; treating them as liquidation values silently shifts headline figures by 15–30%).

**For the primary residence**, ask whether the user wants it in the analysis at all. Two valid postures:

- **Exclude from investable** (default) — house is a place to live, not a portfolio asset. Show its equity separately in net-worth view, but it doesn't show up in allocation analysis.
- **Include in real estate sleeve** — house is part of net worth and gets aggregated with investment property for real-estate exposure %.

Document the choice; surface it in the setup summary.

### 5. Existing config & refresh detection

Auto-check first: does the user's working folder contain `investment_analysis_config.yaml` and a prior `positions.csv` (or equivalent)?

If yes → this is a **refresh**, not a new setup. Don't run the interview. Offer:

> "I see you ran this before — your config has [N] accounts with manual annotations from last time, and there's a position ledger from [date]. Drop your fresh statements in the same folder and I'll re-run with the same rules. Anything changed since the last refresh I should know about — new account, distribution started, RE valuation update, vest event — or just refresh as-is?"

If no → ask:

> "Have you done this kind of consolidation before, or is this the first pass?"

If first pass, proceed with the full interview. If they have a prior file (maybe from a different tool), ask for the location so the skill can import it as a starting point rather than starting empty.

## Optional follow-ups (only if needed)

Ask only when interview answers leave genuine ambiguity:

- **"What's the goal of this analysis?"** — quarterly check-in, prep for an advisor meeting, estate planning, divorce, tax planning. Doesn't change what gets extracted, but tells you which analyses to surface first in the report.
- **"Any pending major changes?"** — separation event, big inheritance coming through, planned property sale. These don't go in the analysis but warrant flagging "the data shown is current as of X — Y change pending."
- **"Tax-treatment overrides?"** — if the user wants to apply a haircut to deferred-comp gross MV to show "net asset" values (e.g., 40% for ordinary-income tax at distribution), capture the rate and which accounts it applies to. Surface in config as `tax_haircut` per account.

## Out of scope — when the user asks for recommendations

The user will, inevitably, ask "so what should I do?" mid-interview or mid-analysis. Have a stock response ready:

> "Recommendations need financial planning context — your spending, goals, horizon, FI status — that lives in a separate skill. This one describes the current state. Once a `financial-planning` skill exists, it'd take this analysis as input alongside those planning inputs and produce target allocations / rebalancing moves. For now, I can tell you what you own and how it's structured, but I can't tell you what to change without that context."

Don't make recommendations *anyway* "just to be helpful." It violates the skill's scope and creates inconsistent advice across sessions.

## Setup summary

After the interview, write back a one-paragraph summary like:

> "Got it. I'll consolidate positions across [N] accounts:
> - [taxable brokerage], owner = primary
> - [qualified 401(k)], primary, with the self-directed brokerage sleeve nested inside
> - [NQDC plan], primary, distributions starting [year]
> - [traditional IRA] × 2, primary
> - [3 small pension accounts], primary
> - [3 pension accounts], spouse
> - [HSA], primary, currently in cash sweep
> - [Crypto holdings] (manual entry, BTC only)
> - [Real estate]: 1 primary residence (excluded from investable, included in net worth), 2 rentals (carrying methodology)
> - 40% tax haircut applied to NQDC + LTIPs per your call
>
> Position-level detail from the statements; account-level totals reconciled against your balance-sheet spreadsheet. Output is descriptive only — no recommendations.
>
> Confirm or correct anything before I run it."

Wait for confirmation. This catches misunderstandings cheaply (a 30-second re-statement vs. half an hour of misclassified output).

## Output of this phase

The analysis config that drives `scripts/extract_positions.py` and downstream scripts. See `assets/example_config.yaml` for the full template (PII-free).

Minimal shape:

```yaml
household:
  members:
    - { name: primary }
    - { name: spouse }

accounts:
  - file_match: "<pattern>"
    type: <wrapper_type>     # taxable, qualified_401k, nqdc, etc.
    owner: <member_name>
    # plus type-specific fields: roth_traditional_split, distribution_schedule,
    # nested_inside, tax_haircut, beneficiary, etc.

employers:
  employer_a: { name: "<user-provided>", is_current: true }
  # never write real employer names in the template — only in the user's local config

manual_holdings:
  - { account: <alias>, type: <type>, owner: <member>, value: 0, ... }

real_estate:
  - name: <alias>
    market_value: 0
    mortgage: 0
    methodology: carrying        # or: liquidation_net
    use: primary                 # or: investment, vacation

fund_overrides: {}               # only populated as classification surfaces unknowns

concentration_thresholds:
  single_name: 0.05
  single_sector: 0.25
  single_issuer: 0.25
  # (see assets/example_config.yaml for the full set)

exclusions: [cars, 529]
```

## Common interview gotchas

**1. The user already has a spreadsheet that's more current than the statements.** Honor it — read it in, use it for account-level totals, use the statements for line-item composition. Reconcile and surface mismatches as a data-freshness flag, not an error.

**2. The user has 5 small pensions across former employers.** Each one individually feels like noise. Aggregate them; surface the total. Don't ask the user to characterize each — apply DB-pension default (treat as bond-equivalent income stream) silently and surface for one-shot review only if the totals are material (> 1% of investable).

**3. The user has a "deferred comp" wrapper that's structurally a rabbi trust.** From a portfolio perspective the positions inside behave like normal brokerage; from a credit perspective the *wrapper* is unsecured exposure to the employer. Tag the wrapper accordingly. Do NOT extend "employer credit risk" to the *holdings* inside (a regular mutual fund held inside an NQDC is not employer risk just because the wrapper is).

**4. The user mentions "M Units" / "profit units" / "partner units" / similar.** These are concentrated alt comp vehicles, typically illiquid (or thinly auctioned), with distributions taxed as ordinary income. Classify as `alt_concentrated` with the issuer tagged. Don't try to fit them into a standard asset class.

**5. The user is vague about whether something is vested.** Default to listing it but flag for confirmation. Never silently include unvested awards in default investable totals. The "vested only" vs "vested + unvested" framing is a key downstream surfacing in the report phase.

**6. The user has accounts owned by a trust or LLC.** These are still investable from the household's perspective, but the wrapper type matters for tax characterization and (eventually) estate planning. Capture the wrapper in config and proceed.

**7. The user has restricted stock from a prior employer (post-IPO lockup, ESPP holding, etc.).** These are concentrated single-stock positions. Surface them as such; don't bury inside the general equity sleeve.

## What this interview does NOT do

- It does not ask the user to characterize their risk tolerance, retirement age, or financial goals. Those are inputs to a planning skill, not this one.
- It does not propose any target allocation.
- It does not ask "what bothers you about the current portfolio?" or "what would you change?" Those framings invite recommendation-mode; this skill stays in description-mode.
- It does not ask the user to predict their own behavior ("are you a long-term investor?"). Behavior is implied by what's actually in the portfolio; the analysis surfaces it descriptively.
