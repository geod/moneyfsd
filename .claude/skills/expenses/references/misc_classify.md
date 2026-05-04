# Misc classification (LLM-driven)

Replaces the old "manually walk through Misc rows with the user" workflow. After the regex-based first pass, Claude reads the Misc cluster table, classifies each merchant stem against the taxonomy using its training knowledge, and persists the decisions as YAML overrides. The user reviews exceptions, not defaults.

## When this runs

Phase 4 (Cleanup), immediately after `consolidate.py` finishes the regex pass. Triggered by re-running with `--export-misc`:

```bash
python3 scripts/consolidate.py --config expenses_config.yaml --export-misc
```

This writes `misc_clusters.csv` next to `Lifestyle Expenses.csv`. Schema:

| stem | total | count | sample_descriptions |
|---|---|---|---|
| Normalized merchant name (4 tokens, IDs stripped) | Sum of Misc amounts for this stem | Number of rows | Up to 3 unique full descriptions, joined by `\|\|` |

## What Claude does — three tiers

Read `misc_clusters.csv`, then triage each stem through three tiers in order. **Stop at the first tier that resolves the stem.**

### Tier 1: Training-knowledge classification (free, instant)

Use your training knowledge to recognize well-known merchants ("Alaska Airlines" → Travel/Airlines, "European Wax Center" → Personal Care, etc.). If confident, propose category + subcategory + a stable `description_contains` matcher and move on.

### Tier 2: Web search (only when needed, batched in parallel)

Run web search **only if all four conditions hold**:

1. Stem is **brand-like** — has a distinctive proper noun, NOT a person's name and NOT a bare generic word
2. Stem total ≥ **$200** (cheap, but skip the long tail — for very large budgets, also consider 0.05% × period total as a higher floor)
3. Tier 1 was uncertain
4. Description does **NOT** start with a payment-processor prefix (see skip-list below)

**Always batch** — issue all qualifying searches in a single tool-call block in parallel. Wall clock is ~5–10 seconds for 10 searches batched, vs. 50+ seconds serial.

Build smarter queries by enriching with user-context hints when available:
- Residence region (from property tax / utilities patterns in the data)
- Recent travel destinations (from clustered Travel)
- Transaction location codes already in the description (CA, TX, NY, country names)

**Interpret search results:**
- ✅ Single dominant business match → classify with `(web-resolved)` in the override comment
- ❌ Ambiguous (multiple unrelated businesses share the name) → escalate to user with top 1–2 candidates: *"`Bb* Concord Collective` could be a coworking space (NH) or a wine bar (Boston). Which?"*

### Payment-processor prefixes: strip, then search

`consolidate.py` ships a `PROCESSOR_PREFIXES` table and exposes `strip_processor_prefix()` and `detect_processor()`. Each row in the output CSV already has a `Processor` column populated when one of the known prefixes was detected. The cluster stems in `misc_clusters.csv` are also pre-stripped.

When you build a tier-2 web search query, **always call `strip_processor_prefix()` first.** Stripping turns `Pyl*Optimum Property` into `Optimum Property`, which is a real search the merchant can be identified from.

The current prefix table covers Stripe (`Sa*`, `Sp*`, `Bb*`), Square (`Sq*`), Toast POS (`Tst*`), PayPal (`Pp*`, `Pay*`), Squarespace (`Sqsp*`), PayLeap (`Pyl*`), Active Network (`Act*`), Quest Diagnostics (`Qdi*`), Life Time Fitness (`Ltf*`), NIC USA (`Nic*`), Teleflora (`Tlf*`), Snackpass (`Snack*`), medical billing (`Med*`), SpotOn (`Spo*`), Amazon (`Amz*`, `Amzn*`), Worldpay (`Wf *`), Apple (`Apl*`, `Itu*`), Google (`Ggl*`), Etsy (`Etsy*`), eBay (`Eb*`), WePay (`Wpy*`), Patreon (`Patreon*`), and a few smaller processors.

### Genuinely ambiguous prefixes — still skip tier 2

Two prefixes name multiple merchants and shouldn't be auto-searched even after stripping:

| Prefix | Why ambiguous |
|---|---|
| `Cpp*` | Variously CCBill, Stripe with old descriptors, niche processors |
| `Ms*` | Could be Microsoft, Mastercard merchant, MGM Hospitality, others |

Stripped descriptions starting with these still go to tier 3 (user input).

### Tier 3: User input (the rest)

Surface to the user with a brief reason:

- **Zelle / Venmo to a person's name** — relationship is not knowable from data
- **Generic descriptions** — bare "Charge", "Advanced", "Chase", "Travel Reservation"
- **Foreign-language strings** with no English brand recognition (after tier 2 didn't help)
- **Tier-2 ambiguous results** — pass the top 1–2 search candidates as choices

**Tiny tail (< $200 total)** — leave in Misc unless the user says "keep going."

## Duplicate-rule detection (before writing each override)

Before appending a new override to the YAML, check existing overrides for substring overlap:

- If an existing rule's `description_contains` is a **substring** of the new one (e.g., existing `"Harry's Bar"` vs new `"Harry's Bar, James"`) → **skip the new rule**, log: *"Skipped duplicate: 'Harry's Bar, James' is already covered by existing rule 'Harry's Bar'."*
- If the new rule's `description_contains` is a **substring** of an existing one (rare; new rule is broader) → flag for review rather than auto-apply

This keeps the YAML clean across multiple cleanup cycles. Without the check, refresh-after-refresh accumulates redundant rules.

### Category constraints

Use the existing taxonomy in `assets/default_taxonomy.yaml`. Don't invent new categories without surfacing the proposal first. Subcategories should match what's already used elsewhere in the user's data (check the live `Lifestyle Expenses.csv`).

### Match-string design

The `description_contains` value is a substring matched case-insensitively against transaction descriptions. **Pick a stable substring**, not the full description:

- ✅ `"Alaska Airlines"` (matches "Alaska Airlines Inc.", "ALASKA AIRLINES PURCHASE")
- ❌ `"Alaska Airlines Inc."` (too specific, brittle)
- ❌ `"Alaska"` (too broad — could match a product name "Alaska Crab Legs")
- ✅ `"Lax Smartparking"` (specific to LAX parking)
- ✅ `"Quest Diagnostics"` (matches both "Qdi*Quest Diagnostics" and "Quest Diagnostics")

Avoid match strings shorter than ~6 characters or that are common English words.

### What needs user input (don't guess)

- **Zelle / Venmo to a person's name** ("Zelle Payment To Efren") — could be home help, contractor, family, friend. Flag.
- **Generic Apple Card descriptions** — bare "Charge", "Advanced", "Travel Reservation" — too vague to classify with confidence.
- **Foreign-language merchant strings** with no English brand recognition — could be travel, food, anything.
- **Ambiguous merchant names** that could fit multiple categories without context.

## Output format

Append a block of overrides to the user's `expenses_config.yaml`, marked with a comment so the user can find what was auto-added. Tier-1 (training) and tier-2 (web-resolved) entries can share the block; mark tier-2 entries with `(web-resolved)` in the description for the audit trail:

```yaml
  # --- Auto-classified by Claude on YYYY-MM-DD (Misc cleanup pass) ---
  # Tier 1 — training knowledge
  - { description: "Alaska Airlines", match: { description_contains: "Alaska Airlines" }, category: Travel, subcategory: Airlines }
  - { description: "Quest Diagnostics", match: { description_contains: "Quest Diagnostics" }, category: Health, subcategory: Medical }
  # Tier 2 — web-resolved
  - { description: "SAS Plelandis (Super U supermarket, France) (web-resolved)", match: { description_contains: "Plelandis" }, category: Food & Dining, subcategory: Groceries }
  - { description: "BGC MyClubHub (Boys & Girls Club portal) (web-resolved)", match: { description_contains: "Bgc Myclubhub" }, category: Kids, subcategory: Kids }
```

Each entry's `description:` field is the human-readable label that ends up in `DECISIONS.md`. Keep it short and specific. Always run duplicate-rule detection before adding (see above).

## After applying

1. Re-run `consolidate.py` (without `--export-misc` this time, or just discard the new `misc_clusters.csv`)
2. Show the user the post-fix breakdown: new category totals, change in Misc share, what was reclassified
3. Surface the "needs user input" rows as a separate, short list — these are the ones the user actually needs to think about

## Two iteration paths from here

- **User confirms / corrects** the auto-classifications — apply edits, re-consolidate
- **User answers the "needs input" questions** — add as user-specific overrides (Zelle payees keyed to recipient names, etc.)

The cycle terminates when Misc is < 5% of total or the user is satisfied with the long tail.

## When to fall back to the old manual-walkthrough flow

- Claude isn't confident on > 50% of stems (suggests a domain it doesn't know well)
- The user has explicitly disabled auto-classify (e.g. wants to learn the taxonomy themselves)
- The Misc bucket is already < 5% (not worth automating)
