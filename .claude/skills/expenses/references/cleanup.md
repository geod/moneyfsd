# Cleanup (agent-internal: Phase 4)

The iterative fix-and-persist loop. This is the part of the workflow that turns a "first-pass categorization" into something the user trusts and can reuse.

**Don't say "Phase 4" to the user.** They should experience this as "we're cleaning up the labels" — natural language. See `SKILL.md` for the full vocabulary rules and transition prompts.

**This phase only handles data hygiene.** Analyses (drill-downs, trip clustering, person split) belong in `analyze.md`. Spending decisions belong in `actions.md`. Don't blur the boundaries — different mental modes.

## Cleanup ≠ Analysis ≠ Actions (don't conflate)

Three distinct phases, three distinct jobs:

| | Cleanup (Phase 4) | Analysis (Phase 5) | Actions (Phase 6) |
|---|---|---|---|
| What | Mechanical fixes to wrong categories | Pattern discovery on labeled data | Decisions the user could make |
| User's job | Confirm or correct a label | Pull on threads to understand | Commit / snooze / reject each candidate |
| Format | Apply silently or as a batch list | Tables, drill-downs, breakdowns | Observation + dollar impact + question |
| Example | "Employer cafeteria $1,264 → Food/Work Meals" (just do it) | "Travel breaks down: 3 trips, $X each" | "Streaming subs $872/yr — intentional?" |

**Never list cleanup items, analysis observations, and action candidates in the same section.** Past sessions did this and confused users. Each phase has its own surface; don't smear them.

**Termination signal for this phase:** Misc < 5% AND no new flagged rules in the last cycle. Stop, commit, transition to Phase 5.

**After auto-classification, show the diff.** When `consolidate.py` re-runs after Claude appends new overrides to the YAML, it auto-computes a reclassification diff against the previous CSV (saved as `Lifestyle Expenses.prev.csv`). Surface the top 15 rows that moved categories — this builds user trust and lets them spot anything Claude got wrong before committing. The diff happens automatically; just relay it to the user as a markdown table.

## First pass: apply defaults, then surface for review

The user does NOT want to authorize every obvious categorization. Asking "should Alaska Airlines be Travel/Airlines?" wastes their attention. **Default behavior is automated** via `references/misc_classify.md`:

1. Run `consolidate.py --export-misc` — writes `misc_clusters.csv` (top merchant stems by total) alongside the output.
2. Read `misc_classify.md` for the prompt template, then classify the clusters in batch using your training knowledge — write the proposed overrides directly to the user's `expenses_config.yaml` as a single auto-classified block.
3. Re-run `consolidate.py` (no flag this time) to apply.
4. Show the user:
   - The post-fix category breakdown (so they see the impact)
   - A short list of items that genuinely need their input — generic descriptions (Zelle payee names, "Charge", "Chase"), foreign-language merchants, ambiguous stems, anything you couldn't confidently classify.
5. The user adjusts exceptions or corrects any defaults they disagree with — they don't authorize each obvious one.

Stop applying defaults below ~$200 per stem unless the user says "keep going." The long tail stays in Misc and that's *fine*.

**Why apply-first beats recommend-and-wait:** A "recommended categorization" table awaiting per-item confirmation still creates a confirmation step. The user wants to spend attention on exceptions, not defaults. If you get a default wrong, the iterative loop catches it on review — no harm done. But forcing them to read and approve 50 obvious classifications is the harm.

**What needs user input (don't apply defaults blindly):**
- **Zelle / Venmo to a *person's name*** (e.g., "Zelle Payment To &lt;FirstName LastName&gt;") — could be a contractor, family member, friend, or babysitter; the name alone tells you nothing about the relationship. Flag.
- **Generic Apple Card descriptions** — bare "Advanced", "Charge", "Chase" are uninformative.
- **Foreign-language merchant strings** with no English brand recognition — could be travel, food, or anything.
- **Specific (Date, Amount) one-offs** with no clear merchant pattern.

**What does NOT need user input — classify these normally:**
- **Zelle / Venmo to a *service-descriptive name*** — "Zelle to Cybercyclecoach", "Zelle to Appliance Repair USA", "Zelle to Home Defenders Pest Control". The description tells you what it is; the Zelle wrapper is irrelevant. Treat the same as any other merchant.

The test: cover up "Zelle Payment To" and ask whether the remaining text would be classifiable on its own. A bare first+last name alone = no signal → flag. A business-shaped string (e.g., "Cybercyclecoach Accounts", "ABC Plumbing LLC") alone = clearly a service → classify.

## The loop

```
[user spots issue]  →  [Claude applies fix]  →  [Claude persists rule]  →  [verify]  →  [next issue]
```

## What the user typically catches

- **Wrong category** — "this REI charge wasn't personal gear, it was a gift to my brother"
- **Wrong subcategory** — "ski stuff should be Travel, not Sports & Hobbies"
- **Wrong person** — "that joint Costco run was actually mine"
- **Should be excluded** — "that hotel was a work trip, my employer reimbursed it"
- **Misc rows** — "this Zelle to Maria is the cleaner, file under Home Services"
- **Split rows** — "this Apple Card line item bundles personal + business — split it"
- **Refunds not netted** — "I got a refund for the 3D-printer purchase"

## The five-step fix-and-persist pattern

When the user flags an issue:

### 1. Identify the rule generally

Don't just fix the one row. Ask: **what rule should fire next time this merchant/pattern shows up?**

- "REI charge was a gift" → is *all* REI spend gifts? Probably not — it was this specific date/amount. Use a (Date, Amount) override.
- "Ski stuff should be Travel" → *all* ski spend is travel. Add ski-specific keywords (snow.com, vail resorts, mammoth mtn, ski rental, ski school, snowboard) to the Travel/Ski subcategory.
- "Maria is the cleaner" → all Zelle payments to Maria are Home Services / Cleaning. Add a Zelle-payee-name rule.

### 2. Apply the fix in the live DataFrame

```python
# Specific override
mask = (df['Date']=='12/04/2025') & df['Description'].str.contains('rei', case=False) & (df['Amount']==415.94)
df.loc[mask, 'Category'] = 'Charity & Gifts'
df.loc[mask, 'Subcategory'] = 'Gifts'

# Pattern fix: all ski-related → Travel/Ski
ski_keywords = ['snow.com','vail resorts','mammoth mtn','ski school','ski rental','snowboard']
ski_mask = df['Description'].fillna('').str.lower().str.contains('|'.join(ski_keywords))
df.loc[ski_mask, 'Category'] = 'Travel'
df.loc[ski_mask, 'Subcategory'] = 'Ski'
```

### 3. Persist the rule in `consolidate.py`

This is the step that's easy to skip and devastating to skip. Open `scripts/consolidate.py`, find the right keyword table, add the new keyword(s).

```python
# In the categorize() function, in the right block:

# Ski gear, lift tickets, rentals, ski school — treat as Travel/Ski
if any(k in d for k in ['snow.com','vail resorts','mammoth mtn','base mountain','black tie ski',
                         'ikon pass','epic pass','ski school','ski rental','snowboard']):
    return ('Travel', 'Ski')
```

For one-off (Date, Amount) overrides, add to the override block at the top of `categorize()`:

```python
# --- User-confirmed one-off overrides ---
# REI purchase 12/04/2025 $415.94 was a gift to brother (not personal gear)
if row['Date']=='12/04/2025' and 'rei' in d and round(float(row['Amount']),2)==415.94:
    return ('Charity & Gifts', 'Gifts')
```

Comment **why** — "user confirmed it was a gift, not personal gear" — so future-you (or future-Claude) understands why this exception exists.

### 4. Save + verify

```python
df.to_csv('Lifestyle Expenses.csv', index=False)
```

Then re-run the consolidation end-to-end and confirm the fixed rows still come out fixed:

```bash
python scripts/consolidate.py --config user_config.yaml
```

Verify by spot-checking the same rows. If they now categorize correctly without the live patch, the persistence worked.

### 5. Tell the user what you did

```
Moved the REI charge ($415.94, 12/04/2025) to Charity & Gifts / Gifts. 
Added a one-off override in consolidate.py — future imports will keep this 
classification.

Also moved 12 ski-related rows ($4,200 total) from Sports & Hobbies to Travel/Ski.
Added 'snow.com', 'vail resorts', 'mammoth mtn', 'ski school', 'ski rental', 
'snowboard' to the Travel/Ski keyword table — these are now standing rules.
```

The user gets to confirm both the fix and the rule. If they say "actually I do want vail resorts as Sports because it's where I rent equipment", you can roll back the rule before it propagates.

## Refunds, returns, and credits

Treat these as **negative-amount rows** in the same Category/Subcategory as the original purchase. Don't drop the original.

This pattern preserves the audit trail (the user can see "I spent $X then got back $Y") while netting correctly to the right total.

The bundled `scripts/apply_refunds.py` is **idempotent**:

1. It drops any existing rows tagged with REFUND/RETURN/CREDIT in `Original Category`
2. Then re-appends the refund list

This means rerunning the script after adding new refunds doesn't duplicate them.

```python
refunds = [
    ('07/20/2025', 'Partner AmEx', 'SUMMER CAMP REFUND (RETURN)',
     'Kids', 'Kids', -140.00, 'Partner AmEx / RETURN'),
    # ... add new refunds here
]
```

## Statement / travel / dispute credits

Card-issued credits (statement credits, travel credits, dispute resolution credits) deserve their own subcategories so they don't pollute regular spending:

- Statement credit → `Fees / Statement Credit` (negative — a card reward)
- Travel credit (e.g., Chase Sapphire $300/yr) → `Travel / Card Travel Credit` (negative — offsets travel)
- Dispute reversal → put back in the original category as a regular charge

This way the user sees their **gross** travel spend AND the credits separately. Netting them away hides important info.

## Misc row triage

After every consolidation, surface the top 20–30 Misc rows by amount:

```python
misc = df[df['Category']=='Misc'].sort_values('Amount', ascending=False).head(30)
for _, r in misc.iterrows():
    print(f"  {r['Date']}  ${r['Amount']:>8,.2f}  [{r['Source']}]  {r['Description'][:70]}")
```

Walk through them with the user. Most will turn into a new keyword table entry; a few will be one-off overrides; a handful will be genuinely unknown ("what's this $1,375 Zelle to Agames Enterprises?"). Document the genuine unknowns in `FOLLOW_UPS.md` so they don't get lost.

## Recovering from over-fitting

Sometimes a keyword you added catches things it shouldn't. Example: adding "kitchen" to Restaurants will catch "Kitchen Aid Mixer" → wrong category.

When this happens:

1. Find the new false matches (`df[df['Subcategory']=='Restaurants' & df['Description'].str.contains('aid mixer')]`)
2. Make the keyword more specific or anchor it (`'kitchen restaurant'` rather than bare `kitchen`)
3. Or move the keyword to a more specific subcategory (`'open kitchen'` matches a restaurant; bare `kitchen` matches both)

Always re-run after a rule change and check the diff:

```python
old = pd.read_csv('Lifestyle Expenses.csv')
new = ... # rerun consolidate
diff = new.merge(old, on=['Date','Description','Amount'], suffixes=('_new','_old'))
changed = diff[diff['Category_new'] != diff['Category_old']]
print(changed)
```

The diff tells you exactly what your rule change moved.

## When to stop

You're done with cleanup when:

- Misc is < 5% of total
- The user has stopped flagging issues
- The category roll-up matches the user's intuition

If Misc stays high after several rounds, the keyword tables need expansion — usually you're missing a domain (e.g., the user has lots of online shopping at boutique retailers your keyword table doesn't know).
