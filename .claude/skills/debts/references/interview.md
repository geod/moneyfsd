# Interview

Same 3-stage shape as `investments`, lighter where the failure modes are different.

This skill is **descriptive only**. Set that expectation in Stage 1. If the user asks for debt-strategy recommendations, redirect — see "Out of scope."

---

## Flow at a glance

| Stage | What happens | Time |
|---|---|---|
| **1. Opener** | Privacy + outcome note + structured coverage checklist | ~30 sec |
| **2. Drop** | User dumps loan statements; agent parses silently | a few minutes |
| **3. Gap reconciliation** | Agent surfaces deltas + asks the few things statements can't tell us | 1–3 targeted questions |

---

## Stage 1 — Opener (before any files are touched)

### Open with the outcome hook + privacy note

> "Sure — let's get you a clear picture of what you owe, what it's costing you, and when each loan pays off at the current pace. The output is a consolidated debt ledger plus an analysis pack (total debt, weighted-avg rate, variable-rate exposure, payoff timeline, anomalies). Strictly descriptive — what *is*, not what to *do*. If you want refinance / payoff-strategy advice, that comes from a separate planning step.
>
> **One thing this skill doesn't capture: mortgages.** Your home value and mortgage live together in the `investments` skill (under its `real_estate:` block) — that's where home equity is computed and where the asset/mortgage pairing belongs. This skill is for everything else you owe: credit cards, auto, student, personal loans, BNPL, etc.
>
> Quick note on privacy: your statement files stay on your local disk and the analysis is written next to them — nothing gets uploaded to a server. Loan details and balances flow through Claude during analysis (that's how I read them); per Anthropic's published policy, API conversations aren't used for training by default. Check the policy directly if you want stricter assurance.
>
> Before you go statement-hunting, take 30 seconds to tick everything you have."

### The coverage checklist (structured multi-select)

Use `AskUserQuestion` with **two multi-selects in one call**, ordered **most-common to least-common** within each group. Starting with high-incidence categories nudges recall before "anything weird?" framing. Long-tail items (tax debt, family loans) live in the conversational follow-up instead of cluttering the checklist.

**Question 1 — "Most common debts"** (multiSelect = true) — ranked by US household incidence:
- Credit cards carrying a balance month-to-month (most universal household debt)
- Auto loan(s)
- Student loans (federal or private)
- Personal loan / line of credit

**Question 2 — "Other types of debt"** (multiSelect = true) — neutral framing, still ordered by commonality:
- Buy-now-pay-later (Affirm, Klarna, Afterpay)
- 401(k) loan (against your retirement balance)
- Medical debt / collections
- Family / informal loans

**Long-tail items captured conversationally after the checklist** (not in the multi-select):
- IRS / state tax payment plan
- HELOC used for non-home-improvement (note: home-improvement HELOC goes in `investments` with the property)
- Anything not listed above

**Note in the opener — mortgages don't belong here:**
> *"One thing this skill doesn't capture: mortgages. Your home value and mortgage live together in the `investments` skill (under `real_estate:`) — that's where 'home equity' is computed. This skill is for the other stuff."*

This callout is non-negotiable. Without it, users tick "Mortgage / HELOC" expecting it to be tracked here, then later get confused about why their net-worth view requires two skills.

**Why the rename + reorder:** The earlier draft labeled Q2 "Easily-forgotten debt" and led with 401(k) loans — both signals "weird stuff is coming." Result: users mentally bucket Q2 as "probably doesn't apply to me." Neutral framing + commonality ordering treats both checklists as routine coverage. Don't lead with the unusual.

### What the checklist gives you

Ticked set = **expected debt inventory**. Stage 2 produces the **actual** inventory from statements. Stage 3 reconciles the two.

### What NOT to ask in Stage 1

- **Don't ask revolving-vs-paid intent.** Defer to Stage 3 — by then you have actual balances to anchor the question.
- **Don't ask ARM reset dates or rate-type details.** Defer to Stage 3 if relevant.
- **Don't ask co-signer attribution.** Statements show borrower order; ask only on ambiguity.
- **Don't enumerate lenders.** ("Wells? Chase? Rocket?") Categories only.
- **Don't expose source-format quirks.** Agent-only knowledge — lives in `references/ingest.md`.

### Why the checklist before the dump

Same reasoning as `investments`. People forget specific debts (the 401(k) loan, the lingering medical bill, the BNPL installment they set up months ago). The checklist primes recall *before* they go statement-hunting.

---

## Stage 2 — Drop & silent inference

### Tell the user what to drop, where

> "Now drop loan statements into one folder and tell me the path. Mortgage, auto, student, credit-card billing statements — anything you have. **CSV / Excel exports are preferred** (cleaner extraction), but **PDF statements are fine** — I'll handle them.
>
> Just drop what you can find right now. If something doesn't have a statement (family loan, BNPL, 401(k) loan), leave it — we'll capture it in the next step."

### What the agent does silently

1. **Inventory** — list files, detect lender from headers, classify by loan type.
2. **Run `extract_loans.py`** — produces `.analysis/raw_loans.csv` + `.analysis/statements_meta.json`.
3. **Infer where possible**:
   - Lender from statement headers
   - Loan type from structural cues (mortgage = "Mortgage Statement", auto = vehicle ID present, student = federal-servicer header)
   - Borrower / co-borrower from named-party section
   - Rate type from "Variable APR" / "Adjustable Rate" markers
4. **Don't prompt for ambiguities yet.** Capture for Stage 3.

### What's allowed to fail in Stage 2

- A statement parser doesn't find a field → flag, don't block. Stage 3 either asks or applies a default.
- A statement that mentions an ARM reset without a date → flag for Stage 3.
- An unrecognized lender format → fall back to "manual entry" prompt for that loan in Stage 3.

---

## Stage 3 — Gap reconciliation

### Compute the diff

| Bucket | What to do |
|---|---|
| Ticked AND found | Silent — already mapped |
| **Ticked but NOT found** | Ask once: drop now / value-only manual entry / skip |
| Found but NOT ticked | Confirm |

### Question template for "ticked but not found"

**Present items in the same order as the Stage 1 multi-select (most-common first)** — credit cards before personal loans before BNPL, etc. Don't order by what's mentally easiest for the agent. The user's energy went into the Stage 1 ranking; respect it.

> "I see you ticked these but didn't drop a statement:
>
> 1. **Credit card (revolving)** — got it?
>    - Drop the statement (I'll re-read)
>    - Just balance + rate + min payment — I'll add it manually
>    - Skip for now
>
> 2. **Personal loan** — same options
>
> 3. **BNPL** — same options
>
> Pick one per item."

Use `AskUserQuestion`, one question per ticked-but-missing category, each with the 3 options. If > 4 items missing, batch the top 4 and follow up.

### Value-only manual entry — when the user picks "I'll add it manually"

If the user doesn't have statements at all (the "I don't have the PDFs on me" case), the conversation pivots to value-only entry across ALL ticked categories. Present the fields **in the same commonality order**:

1. 💳 Credit cards — issuer, balance, APR, min payment, whose card, joint?
2. 🚗 Auto loan(s) — whose, lender nickname, balance, APR, monthly payment, fixed/variable
3. 🎓 Student loans — whose, federal/private (or servicer name), balance, APR, monthly payment, repayment plan
4. Personal loan / BNPL — same shape
5. 401(k) loan — whose, balance, rate, monthly payment, term
6. Medical / family / tax — case-by-case

For any field the user doesn't know: apply a sensible default + set `payment_estimated: true` in the config so the downstream report visually flags it (~$X with a footnote). Don't pester.

### Statement-only questions (only for relevant ticked categories)

Asked in one compact block after the missing-statement reconciliation:

- **Credit cards with non-zero balance** → "Is this revolving (carrying month-to-month) or just the most recent statement before you pay it off?" Default: revolving if balance > 0.
- **Mortgages** → "Is this fixed-rate or ARM? If ARM, when's the next reset?" Default: fixed.
- **Promotional 0% balances (BNPL or balance transfers)** → "When does the promo end?" Default: assume current rate continues indefinitely.
- **Family loans (if ticked)** → "Balance, rate (if any), and informal repayment expectation?" Default: 0% rate, indefinite term, marked informal.
- **Joint debt with co-borrower** → "Is this joint with your spouse, or single-owner?" Default: single owner = first borrower named on the statement.

### Setup summary at the end of Stage 3

> "Got it. I'll consolidate debts across [N] loans:
> - Primary mortgage with [lender], 30-year fixed at [rate]%, [years] left
> - HELOC with [lender], variable rate currently [rate]%, marked home-improvement use (deductible interest)
> - 2 auto loans (yours + spouse's), both fixed
> - Federal student loans serviced by [servicer]
> - 3 credit cards carrying balances — treating as revolving
> - 401(k) loan, $X, rate [rate]% (you provided)
> - Informal family loan, $X, no rate, no schedule
>
> Output is descriptive only — no recommendations on refinance or payoff order.
>
> Confirm or correct anything before I run the analysis."

Wait for confirmation.

---

## Refresh flow (return user)

Trigger: working folder already contains `debts_config.yaml` and a prior `Debt Ledger.csv`.

> "I see you ran this before — your config tracks [N] loans: [type breakdown]. Ledger is from [date].
>
> Two questions:
>
> 1. **Drop fresh statements in the same folder.** I'll re-read and surface deltas vs last time.
> 2. **Anything new since last refresh?** [Show the 2-group coverage checklist with already-tracked categories pre-marked `✓ already tracked`.]"

After response:
1. Re-run extraction + consolidation against new statements.
2. Apply newly-ticked categories via Stage 3 pattern (drop / manual entry / skip).
3. Surface deltas in the report's "What changed?" section (balance moved, rate reset, loan paid off, new loan added).
4. Refresh charts.
5. Stop.

---

## Out of scope — when the user asks for recommendations

Stock response:

> "Refinance / payoff strategy / consolidation calls need cashflow context, your goals, your tolerance for paying interest vs liquidity. That lives in a separate planning skill. This one describes the current debt picture. Once a `debt-payoff` skill exists, it'll take this ledger plus your cashflow to surface payoff strategies. For now, I can tell you what you owe and at what rate, but I can't tell you what to do about it without that context."

Don't make recommendations "just to be helpful." Same scope discipline as `investments`.

---

## Output of this phase

The analysis config that drives `scripts/extract_loans.py` and downstream scripts. See `assets/example_config.yaml` for the full template.

Minimal shape:

```yaml
household:
  members:
    - { name: primary }
    - { name: spouse }

accounts:
  - file_match: "mortgage*.pdf"
    type: mortgage
    owner: primary
    secured_by: primary_residence
    rate_type: fixed

manual_entries:
  - { loan_id: family_loan_mom, type: family, owner: primary, balance: 12000, rate: 0.0, status: informal }
  - { loan_id: 401k_loan, type: 401k_loan, owner: primary, balance: 18000, rate: 0.065, term_months_remaining: 36 }

thresholds:
  high_rate_revolving_apr: 0.18
  arm_reset_horizon_months: 12
  near_payoff_months: 6
  pmi_ltv_threshold: 0.78
```

---

## Common interview gotchas

**1. The user pays off credit cards in full each month but their statement still shows a balance.** Most card statements show the *statement balance* (what was charged during the cycle) regardless of whether the user paid it off after. Ask the revolving-vs-paid question explicitly; default to assuming non-zero balance = revolving but let the user override.

**2. The user has a mortgage with a recently-completed refinance.** Old statement still on file shows the prior loan. Use the most recent statement date as canonical; flag the old one as superseded if both are dropped.

**3. The user has both joint and individual cards with the same issuer.** Same lender doesn't mean same loan — dedupe by account number + balance + rate triplet, not by lender alone.

**4. The user mentions a "loan" that's actually a lease (auto lease, equipment lease).** Leases aren't debt in the financial sense — they're operating-expense commitments. Capture as out-of-scope and suggest they live in the future `expenses` or `cashflow` skill.

**5. The user has a HELOC in draw vs in repayment.** During draw, it behaves like revolving (interest-only on the drawn balance). After conversion, it amortizes. Statement should disclose phase; if not, ask.

**6. Buy-now-pay-later (BNPL) installments are reported per-purchase.** A user with Affirm might have 4 active installment plans. Each is a separate row, even though they're with the same lender, because each has its own balance, term, and promo end date.

**7. Student loan IDR / forbearance / interest-accrual paused.** Federal income-driven repayment can show $0 payment but balance accruing interest, OR $0 payment with no interest accrual (during certain administrative pauses). Capture both: balance + scheduled payment + current accrual status (note).

**8. Tax debt is a payment plan, not a loan in the traditional sense.** IRS / state payment plans have specific terms — IRS interest = federal short-term rate + 3%, recalibrated quarterly. Capture as `type: tax`, treat the current rate as variable, surface in anomalies if rate > 7%.

---

## What this interview does NOT do

- Does not ask the user to characterize their refinance tolerance or payoff goals — planning-skill inputs.
- Does not propose any debt strategy.
- Does not ask "which debt is bothering you most?" — invites recommendation-mode.
- Does not ask the user to predict cashflow ("can you afford an extra payment?"). That's the future `cashflow` skill's job.
