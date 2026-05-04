# Interview

The interview's job is to learn just enough to set up the consolidation correctly. Don't ask everything upfront — five questions max. The cleanup loop catches whatever the interview misses.

## The five opening questions

Ask these via `AskUserQuestion` (or just inline if conversation is flowing). Adapt phrasing to context.

### 1. Account-type coverage

> "Sure — let's get you a clear picture of where your money is actually going, surface any anomalies, and call out the biggest opportunities to optimize. Output is one consolidated, categorized ledger you can keep refreshing.
>
> Quick note on privacy: your statement files stay on your local disk and the consolidated output is written next to them — nothing gets uploaded to a server. Transaction descriptions and amounts do flow through Claude during analysis (that's how I read them); per Anthropic's published policy, API conversations aren't used to train models by default, but if you're on a specific plan or want to verify, check Anthropic's privacy policy directly.
>
> To start, grab exports from every *type* of account where you have material spending:
> - All personal credit cards
> - All checking accounts
> - Any joint cards or accounts
> - Any business / work cards (so we can exclude reimbursables)
>
> I'll accept what I can get — **CSVs are preferred (cleaner, more accurate), but PDF statements are okay too** (I'll extract them; expect a bit more cleanup). You can mix formats per account.
>
> Drop everything in one folder and tell me the path. I'll inventory the folder and figure out which file is what."

**Why the hook:** Lead with the user's *outcome* (clear picture / anomalies / optimization opportunities), not the mechanics. People want to know the value before doing setup work.

**Why the privacy note:** People hesitate to share financial data with an LLM. Address it upfront, honestly:
- Files stay local — true; the script reads them in place and writes output next to them.
- Transaction text flows through the API — also true, and worth saying explicitly. Don't pretend the API call doesn't happen.
- Training claim — phrase as Anthropic's stated policy, not as your personal guarantee. Don't promise on Anthropic's behalf; point users at the policy.

**Why coverage checklist:** Its purpose is to nudge the user to remember accounts they'd otherwise miss (a forgotten card hides spend; a forgotten joint account skews the person split). Do NOT list specific institutions ("Apple Card, Chase, Amex…") — the user already knows what they bank with, and naming them adds noise.

**Format stance:** Be explicit upfront that PDFs are accepted. Many users only have PDF statements (especially for older months or banks without good CSV export). If you only mention CSVs, users assume PDFs aren't supported and either give up or spend hours converting. The PDF path is more error-prone, so still nudge toward CSV when feasible — but never block on it.

**Do NOT expose source-format quirks to the user.** Things like "Apple Card has a quirky Type column" or "Chase has AUTOMATIC PAYMENT rows that look like payments but aren't" are agent-only knowledge — they live inside `scripts/consolidate.py` and `references/consolidate.md`. Surfacing them in interview options ("I have a built-in handler for X") leaks implementation detail and clutters the user's decision.

After the user drops the folder, inventory it and read filenames + CSV headers to detect institutions. Only ask about ambiguities you can't resolve from the files.

### 2. Time period

> "What time window do you care about? Most useful is the **last 12 months** — gives you a true annual run-rate. Other common picks: YTD (year to date), last calendar year, last quarter."

**Why:** Drives the date filter. Last 12 months is the default because annualization is what matters for budgeting. *Don't say "TTM" to the user* — most people don't know the acronym; just say "last 12 months".

### 3. People

> "Who's in the household? I'll attribute spending per person where the data lets me. (Joint cards usually have a cardholder column we can use.)"

**Why:** Drives the `Source` field. "Alex AmEx" vs "Partner AmEx" vs "Joint Chase" determines how the person split shows up in analyses.

### 4. Property gate (NEW — ask before exclusions)

> "Other than your primary residence, do you own any other property? (Vacation home, rental, inherited, etc.)"

If **no** → skip to Question 5 (Exclusions). All housing-type spend lands in `Housing`.

If **yes** → inventory each property *and* drag out the routing signals before consolidation. Don't ask vaguely ("any other property?"); ask the specific things you'll grep for.

**For each holiday / second home**, ask in this order:
1. Where is it? (Town + state — gets you property tax county and utility provider region)
2. Mortgage servicer (e.g., Rocket, Wells, Chase) — and the *account number* if they remember it. Two mortgages from the same servicer can only be distinguished by the account number embedded in the description (e.g., `Rocket Mortgage Mtg Pymts 1234567890` vs `... 9876543210`).
3. Utility provider names (water, electric, internet, waste). One example often pulls in the others — once you have the water utility you can usually predict the waste hauler and ISP for that region.
4. HOA / community / building name if applicable.
5. Recurring service providers (caretaker, pool, snow, lawn).

Add a **Holiday Home category** with subcategories Mortgage / Property Tax / Utilities / Maintenance / Insurance. Write each routing signal as an override matched on the most specific stable substring you have.

**For each rental / investment property**, drag out:
1. Building / coop / community name *as it appears in payments* (e.g., the property management firm's billing descriptor).
2. Property manager and how they bill (ACH descriptor, Web ID).
3. Mortgage servicer + account number.
4. Tenant names you receive Zelle / wire payments from (so the inflows can be excluded too if the user wants a true rental P&L view later).
5. Recurring contractors and their Zelle / Venmo names.
6. Landlord insurance vendor (e.g., Lemonade-NY, Foremost).

Add **explicit exclusion rules** keyed by signal. Use `kind:` field to distinguish the *type* of exclusion (see exclusion sub-types in `assets/example_config.yaml`):
- `rental_operating` — real operating costs (HOA, repairs, mortgage interest)
- `rental_escrow` — round-trips through escrow (deposits collected, deposits returned) — these are **NOT P&L items** and shouldn't be confused with operating expense
- `family_transfer` — Zelles to relatives, even if they share a surname

Don't rely on a generic "rental" exclude — be specific or you'll miss things. Get the property routing nailed in the interview; running the consolidation with bad signals means re-classifying half the rows during cleanup.

**Disambiguation gotcha:** if the user has multiple loans from the same servicer (e.g., two mortgages on different properties, or a mortgage + HELOC), the only thing that distinguishes them is the account number embedded in the description. Always ask which servicer-and-account belongs to which property — don't assume the bigger payment is the primary residence. The skill's `detect_multiple_loan_streams` warning fires after consolidation to catch missed attributions, but better to get them right upfront.

**Why this gate matters:** A user who has a holiday home, a rental, and a primary residence has THREE distinct buckets. Treating them all as Housing pollutes the lifestyle picture; treating any of them as a generic exclude misses real lifestyle costs (e.g. holiday home property tax IS a lifestyle expense). Without this gate, you re-discover the property structure mid-analysis and have to retro-fit (which is what happened in the original session that triggered this rule).

### 5. Exclusions

> "Anything else to keep out of personal spending? Common ones to flag:
> - Business / work expenses on a personal card (will be reimbursed)
> - Investment transfers (brokerage funding, 401k, 529 contributions)
> - **Income tax payments** (IRS, state income, FICA self-employment) — always exclude
> - Credit-card payments from checking (already counted on the card side — would double-count)
> - Bank-to-bank internal transfers (between your own accounts)"

**Why income vs property tax matters:** Income tax is *always* outside lifestyle. Property tax depends on which property: primary-residence property tax is lifestyle (same as utilities), rental property tax is rental P&L, holiday-home property tax is your separate Holiday Home bucket if you have one. The previous "tax payments" exclusion conflated these and tripped users with multiple properties. Resolve this in question 4 (property gate) and only ask income-tax-specific things here.

### 5. Existing taxonomy

> "Do you already have a category structure you like? Or want me to use a default one (Housing / Food & Dining / Travel / Kids / etc.)?"

**Why:** If they're returning to the workflow with a previously-tagged file, we should preserve their categories rather than overwriting.

## Optional follow-ups (only if needed)

Ask only when the interview answers leave genuine ambiguity:

- **"Where did the file come from?"** — bank export vs. Mint/Copilot/YNAB export vs. manual spreadsheet. Format affects parsing.
- **"Is this a recurring exercise?"** — if yes, prioritize persisting cleanup rules. If one-off, more permissive.
- **"What's the goal?"** — budgeting, divorce/estate prep, tax prep. Affects which analyses to surface.

## Setup summary

After the interview, write back a one-paragraph summary like:

> "Got it. I'll pull spending from your Apple Card (Alex + Partner cardholders), Chase Sapphire (Alex), and joint checking. Last 12 months window. Excluding card-payoff rows from checking, the rental property's mortgage and management, and any work travel charged on the Apple Card. Using the default category taxonomy. Ready to consolidate — confirm or correct anything before I run it?"

Wait for confirmation. This catches misunderstandings cheaply (a 30-second re-statement vs. 20 minutes of misclassified output).

## Output of this phase

The consolidation config (a YAML or dict) that drives `scripts/consolidate.py`. See `assets/example_config.yaml`.

```yaml
sources:
  - name: Alex AmEx
    file: apple-ccard/Apple Card Transactions Apr 2025 - Apr 2026.csv
    type: apple_card
    cardholder_column: Purchased By
    cardholder_map:
      "Alex Doe": Alex AmEx
      "Jordan Doe": Partner AmEx
  - name: Alex ChaseCard
    file: Chase Transactions Mar 2025 - Apr 2026.csv
    type: chase_card
    cardholder: Alex
  - name: Joint Checking
    file: Checking Transactions.csv
    type: generic_checking
    exclude_categories: [Credit Card Payments, Investment, Income, Taxes, Rental Property]

people:
  - Alex
  - Partner

time_window: TTM
period_end: 2026-04-26

exclusions:
  - description: "Work trip — employer-reimbursable hotel/flight"
    match: { date: ["07/10/2025", "07/11/2025"], description_contains: ["hotel okura", "haneda"] }
  - description: "Rental property landlord insurance (lives in rental P&L)"
    match: { description_contains: ["landlord insurance"] }

taxonomy: default  # or path to user's taxonomy YAML
```
