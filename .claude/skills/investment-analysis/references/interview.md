# Interview

The interview's job is to learn just enough to set up the analysis correctly — without making the user defend account-by-account knowledge before they've shifted into "pull files from portals" energy.

This skill is **descriptive only**. Set that expectation in Stage 1. If the user asks for recommendations during any stage, redirect — see "Out of scope" near the end.

---

## Flow at a glance

Three stages, sequenced to match the user's actual energy level — not the agent's preferred ordering:

| Stage | What happens | Time |
|---|---|---|
| **1. Opener** | Privacy + outcome note + structured coverage checklist | ~30 sec |
| **2. Drop** | User dumps whatever statements they have right now; agent extracts and infers silently | a few minutes (user-paced) |
| **3. Gap reconciliation** | Agent surfaces deltas between checklist and statements + asks the few questions statements can't answer | 1–3 targeted questions |

The point: prime memory cheaply *before* the user goes statement-hunting, then do the interview-style work on the *gap* (what they ticked but didn't drop, what statements can't tell us). Don't make the user answer 15 questions before they see any value.

---

## Stage 1 — Opener (before any files are touched)

### Open with the outcome hook + privacy note

> "Sure — let's get you a clear picture of what you own, where it sits, how your asset mix actually breaks down through every fund, where your concentrations are, and where anything looks off. The output is a consolidated position ledger plus an analysis pack (allocation, concentration, tax-location, fees, anomalies). Strictly descriptive — what *is*, not what to *do*.
>
> Quick note on privacy: your statement files stay on your local disk and the analysis is written next to them — nothing gets uploaded to a server. Security descriptions and holding values flow through Claude during analysis (that's how I read them); per Anthropic's published policy, API conversations aren't used to train models by default, but if you want stricter assurance, check Anthropic's privacy policy directly.
>
> Before you go statement-hunting, take 30 seconds to tick everything you have — even if you don't have the statement handy. I'll figure out what to do with each one."

### The coverage checklist (structured multi-select)

Use `AskUserQuestion` with **three multi-selects in one call**. Grouping reduces decision fatigue and keeps the user on a single screen:

**Question 1 — "Retirement & pensions"** (multiSelect = true)
- Current employer plan (401(k), 403(b), 457)
- Former employer plan (left behind, not rolled over)
- IRAs — Traditional, Roth, Rollover, SEP, SIMPLE
- Pension — DB, cash balance, or traditional

**Question 2 — "Direct & tax-advantaged"** (multiSelect = true)
- Taxable brokerage (direct holdings, not inside a retirement plan)
- HSA (Health Savings Account)
- 529 / Coverdell (any child or beneficiary)
- Cash savings (separate from operational checking)

**Question 3 — "Other holdings"** (multiSelect = true)
- Restricted comp (RSUs, LTIPs, options, NQDC, partnership / profit units)
- Crypto / digital assets
- Investment real estate (rentals, syndications, land)
- Private investments (PE, angel, venture, real-estate partnerships)

### What the checklist gives you

The ticked set becomes the **expected inventory**. Stage 2 produces the **actual inventory** (from statements). Stage 3 reconciles the two — that's where the questions happen.

### What NOT to do at this stage

- **Don't ask household structure yet.** Defer to Stage 3 — by then, statements have told you who's named on which account, and you can ask a much narrower question.
- **Don't ask about Roth/Trad split, vesting, NQDC schedule, HSA cash-vs-invested.** All deferred to Stage 3 — and only for the relevant ticked categories.
- **Don't ask "what's your goal for this analysis?"** Add as an optional follow-up only if the user volunteers context.
- **Don't enumerate institutions.** Never say "Schwab? Fidelity? Vanguard?" — categories only. The user knows what they bank with; naming custodians biases the conversation.
- **Don't expose source-format quirks.** Things like "Schwab statements bury cost basis in footnotes" are agent-only knowledge. Never surfaced to the user.

### Why the checklist before the dump

| If you put the checklist after | …the user has already shifted into "I'm done dropping files" mode. They'll click through the list. The 529 they forgot stays forgotten. |
| If you skip the checklist entirely | …you only know about accounts the user remembered to drop a statement for. The exact failure mode that motivated this rework. |
| Putting it first | …primes memory while the user is still in "active recall" mode, and gives the agent an *expected inventory* to reconcile against. |

---

## Stage 2 — Drop & silent inference

### Tell the user what to drop, where

> "Now drop everything you have into one folder and tell me the path. **CSV / Excel exports are preferred** (cleaner extraction), but **PDF statements are fine too** — I'll handle them. If you keep a balance-sheet spreadsheet that lists every account's total, drop that in too; I'll use it as a consistency check.
>
> Just drop what you can find right now. If something's a pain to grab, leave it — we'll deal with it in a minute."

That last line matters. It removes the implicit pressure to gather everything before continuing. The gap-reconciliation stage handles missing statements gracefully (value-only manual entry, skip-for-now, etc.).

### What the agent does silently

Once the user names the folder:

1. **Inventory** — list files, check extensions, peek at first-page text for custodian/account-type detection.
2. **Run `extract_positions.py`** — produces `.analysis/raw_positions.csv` + `.analysis/statements_meta.json`.
3. **Infer where possible**, without asking:
   - Custodian from headers ("Charles Schwab & Co.", "Fidelity Investments", …)
   - Account type from structural cues (account-number patterns, plan names, statement type strings)
   - Employer from plan names (e.g., "ACME 401(K) PLAN" → employer alias)
   - Owner from "Primary Holder" / "Joint Holder" / "TTEE" / "FBO" markers
4. **Don't prompt for ambiguities yet.** Capture them as `pending_questions` for Stage 3.

### What's allowed to fail at this stage

- A statement that doesn't reconcile against its own header total → flag, surface in Stage 3, *don't block*.
- An ambiguous account type → flag, surface in Stage 3.
- An unknown custodian → flag, surface in Stage 3.

The principle: Stage 2 is mechanical. All judgment calls happen in Stage 3, where they can be batched into a small number of targeted questions.

---

## Stage 3 — Gap reconciliation

### Compute the diff

After Stage 2 finishes, the agent holds two lists:

- **Ticked categories** from Stage 1 (the user's expected inventory)
- **Inferred categories** from Stage 2 (what statements actually showed)

Three buckets emerge:

| Bucket | Meaning | What to do |
|---|---|---|
| **Ticked AND found** | Both checklist and statements agree | Silent — already mapped |
| **Ticked but NOT found** | User has the account but didn't drop a statement | Ask once — see below |
| **Found but NOT ticked** | Statement exists for something the user didn't tick | Confirm — usually means user forgot to tick, occasionally means a misclassified statement |

### Question template for "ticked but not found"

Ask in **one batched message**, not one-per-account:

> "I see you ticked these but I didn't find a statement:
>
> 1. **HSA** — got it?
>    - Drop a statement now (I'll re-read)
>    - Just a current balance — say `value: $X` and I'll add it
>    - Skip for now
>
> 2. **529 / Coverdell** — same options
>
> 3. **Crypto** — same options
>
> Pick one per item and we move on."

Use `AskUserQuestion` with one question per ticked-but-missing category, each with the same 3 options. Capping at 4 questions per call is fine — if there are more than 4 missing categories, batch the most important ones first and surface the rest in a follow-up.

### Statement-only questions (asked only for relevant ticked categories)

Some things never appear on statements. Ask these in Stage 3, **only if the user ticked the relevant category**, in one compact block:

- **Any 401(k) / 403(b)** → Roth-vs-Traditional split inside it? (Default: 100% Traditional, flag for follow-up.)
- **Any NQDC / deferred comp** → When do distributions start? Lump or installments? (Default: unknown, flag.)
- **Any restricted comp** → What's vested today vs not, and when do the unvested layers vest? (Default: assume all listed values vested.)
- **HSA** → Invested, or sitting in cash sweep? (Default: cash sweep, flag.)
- **Investment real estate** → Per-property: market value, mortgage balance, methodology choice (carrying vs liquidation_net), use flag (primary / investment / vacation). (Default: carrying, investment.)
- **Primary residence (if real estate ticked)** → Include in investable analysis, or exclude (default)?

**Apply defaults silently for anything the user doesn't answer.** Never make the user defend not knowing. "I'll mark that as unknown and proceed" is the right response.

### Household structure (also at Stage 3)

Now that statements have surfaced who's named on which account, the household question is narrower:

> "Statements show accounts for [name 1] and [name 2]. Same household? Any joint accounts I should split (50/50 by default), or any trust/LLC-owned accounts I should flag?"

Don't ask this in Stage 1 — by Stage 3 you have actual data to anchor the question.

### Setup summary at the end of Stage 3

Once all gap questions are answered (or defaulted), write back a one-paragraph confirmation:

> "Got it. I'll consolidate positions across [N] accounts:
> - [taxable brokerage], owner = [name]
> - [401(k)], [name], 80% Traditional / 20% Roth as you said
> - [NQDC], [name], distributions at separation, form TBD
> - [HSA], [name], invested (per your note)
> - [529 × 2], beneficiaries kid_a & kid_b, age-based glidepaths
> - [Real estate]: 2 rentals (carrying), primary residence excluded
> - Spouse's accounts out of scope this run, per your call
>
> Position-level detail from the statements; balance-sheet spreadsheet used as a cross-check. Output is descriptive only — no recommendations.
>
> Confirm or correct anything before I run the full analysis."

Wait for confirmation. Cheap to get wrong here; expensive to get wrong after the report runs.

---

## Refresh flow (return user)

Trigger: working folder already contains `investment_analysis_config.yaml` and a prior `positions.csv` (or equivalent).

**Skip Stages 1–3 in their full form. Use a narrower refresh-aware opener instead:**

> "I see you ran this before — your config tracks [N] accounts, [M] manual annotations, and [K] properties. Position ledger is from [date].
>
> Two questions before I refresh:
>
> 1. **Drop any fresh statements in the same folder.** I'll re-read everything and surface deltas vs last time.
> 2. **Anything new since last refresh?** [Show the coverage checklist as a 3-multiselect, but with already-tracked categories pre-marked as `✓ already tracked` — the user only sees the *un-ticked* ones as live options.]"

The pre-marked checklist is critical. Today's 529-miss happened because the refresh flow just asked "anything changed?" — and the user wouldn't say "yes my 529 changed" if nothing about it changed. The user *would* say "oh right, I never added the 529" if shown a checklist with un-ticked categories visibly highlighted.

After the user replies:
1. Re-run extraction + consolidation against the new statements.
2. Apply any newly-ticked categories via the same Stage 3 gap reconciliation (ticked-but-not-dropped → drop / value-only / skip).
3. Surface deltas in the report's "What changed since last refresh?" section.
4. Stop.

---

## Out of scope — when the user asks for recommendations

The user will, inevitably, ask "so what should I do?" mid-interview or mid-analysis. Stock response:

> "Recommendations need financial planning context — your spending, goals, horizon, FI status — that lives in a separate skill. This one describes the current state. Once a `financial-planning` skill exists, it'd take this analysis as input alongside those planning inputs and produce target allocations / rebalancing moves. For now, I can tell you what you own and how it's structured, but I can't tell you what to change without that context."

Don't make recommendations "just to be helpful." It violates scope and creates inconsistent advice across sessions.

---

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

---

## Common interview gotchas

**1. The user already has a spreadsheet more current than their statements.** Honor it — use spreadsheet for account-level totals, statements for line-item composition. Reconcile and surface mismatches as data-freshness flags, not errors.

**2. The user has 5 small pensions across former employers.** Aggregate them; surface the total. Apply DB-pension default (bond-equivalent income stream) silently. Only surface for one-shot review if aggregate is > 1% of investable.

**3. The user mentions a "deferred comp" plan that's structurally a rabbi trust.** Positions inside behave like brokerage; the *wrapper* is unsecured exposure to the employer. Tag the wrapper accordingly. Do NOT extend "employer credit risk" to the holdings inside (a mutual fund inside an NQDC is not employer risk just because the wrapper is).

**4. The user mentions "M Units" / "profit units" / "partner units" / similar.** Concentrated alt comp vehicles, typically illiquid, distributions taxed as ordinary income. Classify as `alt_concentrated` with the issuer tagged.

**5. The user is vague about vesting.** Default to listing it but flag for confirmation. Never silently include unvested awards in default investable totals. "Vested only" vs "vested + unvested" is a key downstream surfacing in the report.

**6. The user has accounts owned by a trust or LLC.** Still investable from the household's perspective; the wrapper type matters for tax characterization. Capture in config and proceed.

**7. The user has restricted stock from a prior employer (post-IPO lockup, ESPP holding, etc.).** Concentrated single-stock positions. Surface as such; don't bury inside general equity.

**8. The user ticks a category in Stage 1 but then says "actually skip that for now" in Stage 3.** Honor it. Record in config as `pending_categories: [hsa, 529]` so the next refresh visibly surfaces them again — quiet nag, not a block.

---

## What this interview does NOT do

- Does not ask the user to characterize risk tolerance, retirement age, or financial goals. Planning skill inputs, not this one.
- Does not propose any target allocation.
- Does not ask "what bothers you about the current portfolio?" or "what would you change?" Those invite recommendation-mode.
- Does not ask the user to predict their behavior ("are you a long-term investor?"). Behavior is implied by what's actually in the portfolio.
