# Consolidate

Phase 3: take the raw positions from ingest, infer account types, dedup nested wrappers, attribute to owners, fold in manual holdings, reconcile against the household balance sheet (if provided), and emit the final position ledger.

This phase is **mechanical with judgment at the edges**. The judgment lives in heuristics + confidence scores, with the user filling in only the genuinely ambiguous cases.

## Order of operations

1. **Account type inference** — assign a wrapper type to each account (taxable / qualified_401k / nqdc / etc.)
2. **Nested wrapper detection & dedup** — find PCRA-in-401(k) and similar nesting; mark child as nested; replace parent line with child detail
3. **Owner attribution** — apply `accounts[].owner` from config; default to primary if absent
4. **Manual holdings injection** — pull in `manual_holdings` from config (M Units, LTIPs, crypto, real estate, anything without a statement)
5. **Real estate methodology** — apply `carrying` or `liquidation_net` per config; compute haircuts for liquidation_net
6. **Household reconciliation** — if user provided a balance-sheet spreadsheet, reconcile each account total
7. **Emit `positions.csv`** — the final consolidated ledger

## Step 1: Account type inference

Apply heuristics in order. First match wins. Confidence is implicit: explicit config override > strong heuristic match > weak heuristic > default.

### Heuristics (in priority order)

**Priority 1: Explicit config match.** If `accounts[].file_match` (glob pattern) matches the source filename, use the configured `type`. This is the user's manual override.

**Priority 2: Header text signals.** Look for explicit phrases in the first page of the statement:

| Signal text | Inferred type |
|---|---|
| "Roth IRA", "Roth Individual Retirement Account" | `roth_ira` |
| "Traditional IRA", "Rollover IRA" | `traditional_ira` |
| "Health Savings Account", "HSA" | `hsa` |
| "529 College Savings", "529 Plan" | `529` |
| "Roth 401(k)" | `roth_401k` |
| "401(k) Savings and Retirement Plan", "401(k) Profit Sharing" | `qualified_401k` |
| "403(b) Tax-Sheltered", "403(b)(7)" | `qualified_403b` |
| "457(b) Deferred Compensation Plan" | `qualified_457` (government NQDC) |
| "Executive Deferred Compensation", "Nonqualified Deferred Compensation", "NQDC" | `nqdc` |
| "Defined Benefit Pension", "Cash Balance Plan" | `pension_db` / `pension_cb` |
| "Pension Plan", no DB/CB qualifier | `pension_unknown` (ask user) |
| "Restricted Stock Unit", "RSU" | `rsu_award` |
| "Long-Term Incentive Plan", "LTIP" | `ltip` |
| "Employee Stock Purchase Plan", "ESPP" | `espp` |
| "Personal Choice Retirement Account", "PCRA" | (see Priority 4 — nesting detection) |
| "BrokerageLink" | (see Priority 4 — nesting detection) |
| No retirement signals, just "Brokerage Account" | `taxable_brokerage` |

**Priority 3: Trustee vs custodian suffix.** For statements that mention a Trust Bank:

- `... Trust Bank TTEE` → `qualified_*` (some flavor of qualified plan)
- `... Trust Bank CUST` → `nqdc`

This is a reliable structural cue — TTEE means the trust holds for the participant's benefit (qualified plan rules); CUST means the trust is tracking on behalf of the employer (NQDC rules).

**Priority 4: Nesting detection.** If a statement looks like a brokerage statement but the title or in-account label says "PCRA" / "BrokerageLink" / "self-directed", mark it as `pending_nesting_resolution` and proceed to Step 2. Its actual type will be derived from whatever parent it nests into.

**Priority 5: Account-number patterns.** Some custodians use number ranges that hint at account type. Use only as a tie-breaker, not a primary signal — these patterns drift.

**Priority 6: Default.** If nothing else matched, default to `unknown` and surface to user. Do not silently default to `taxable_brokerage` — that's the most common type but wrong-defaulting can hide real qualified balances.

### Surfacing inference results

After inference, present a compact table to the user for confirmation:

> "Detected accounts:
>
> | Account | Type | Confidence | Source |
> |---|---|---|---|
> | brokerage_1 | taxable_brokerage | high | "Brokerage Account" header |
> | retirement_1 | qualified_401k | high | "401(k) Savings Plan" header + employer-match line |
> | nested_1 | pcra_qualified | high | Trustee suffix, value matches parent line |
> | deferred_comp_1 | nqdc | high | "Deferred Comp" + CUST suffix |
> | pension_1 | pension_unknown | medium | "Pension Plan" but no DB/CB qualifier |
> | hsa_1 | hsa | high | "Health Savings" header |
>
> Anything wrong? (Reply '1 is roth' to override row 1 to roth_ira, etc.)"

Only ask about the genuinely ambiguous cases. Apply high-confidence inferences silently.

## Step 2: Nested wrapper detection & dedup

This is the single most error-prone consolidation step. The PCRA-in-401(k) trap costs hundreds of thousands of dollars when missed.

### Detection algorithm

1. For each parsed statement, look for a single-line position with description matching: `"self-directed brokerage"`, `"PCRA"`, `"BrokerageLink"`, `"Personal Choice"`, or similar phrases. Note its value `V_parent_line`.
2. For each *other* parsed statement, check if its grand total `V_child_total` matches `V_parent_line` exactly (or within $0.01).
3. If a match is found: the second statement is nested inside the first. Record the relationship.

```python
def detect_nesting(statements):
    relationships = []
    for stmt in statements:
        for line in stmt.positions:
            if is_nesting_indicator(line.description):
                for other_stmt in statements:
                    if other_stmt is stmt:
                        continue
                    if abs(other_stmt.grand_total - line.market_value) < 0.01:
                        relationships.append((other_stmt, stmt, line))
                        break
    return relationships
```

### Dedup transformation

For each detected nesting:

1. Remove the indicator line from the parent statement (`PCRA` line goes away).
2. Add the child statement's positions to the parent's positions list, tagged with `nested_source: <child_filename>`.
3. Mark the child statement as `consumed_into: <parent_filename>` — do not count it as a standalone account.

The parent's grand total stays the same (cash + core funds + sum of nested positions = original total). The child statement contributes line-item detail but not extra dollars.

### Override / manual nesting

If automatic detection fails (e.g., child statement covers a different period than parent), the user can declare the nesting in config:

```yaml
accounts:
  - file_match: "child_pcra*.pdf"
    nested_inside: "parent_401k*.pdf"
```

When this is set, skip the automatic value-match step and force the nesting relationship.

### What if the values don't match exactly?

Cents-level mismatches are fine — different period-end timing, rounding. Up to a few dollars is acceptable.

If the mismatch is larger (hundreds or thousands), the nesting may be real but the statements may be from different period-end dates. Surface to the user:

> "Found a likely nested wrapper but the values don't match exactly: parent statement shows $X for the PCRA line; child statement shows $Y total — off by $Z. These might be from different statement dates. Treat as nested anyway?"

## Step 3: Owner attribution

For each account:

1. If `accounts[].owner` is set in config, use it.
2. Else if the statement header has a clear owner name matching a household member, use that match.
3. Else default to `primary`.

For joint accounts:

```yaml
accounts:
  - file_match: "joint_brokerage*.pdf"
    type: taxable_brokerage
    owner: joint               # explicit joint flag
    joint_attribution:
      - { member: primary, share: 0.5 }
      - { member: spouse, share: 0.5 }
```

If `joint_attribution` is absent on a joint account, default to 50/50 across the household members and surface for confirmation.

For trusts and LLCs:

```yaml
accounts:
  - file_match: "family_trust*.pdf"
    type: taxable_brokerage     # the holdings inside; the wrapper is a trust
    wrapper_structure: revocable_trust    # or: irrevocable_trust, llc
    owner: primary              # whose assets they functionally are
```

The `wrapper_structure` field is informational; it doesn't change asset-class analysis but it does change tax/estate characterization.

## Step 4: Manual holdings injection

Pull every entry from `manual_holdings` in config. Validate:

- `account` (alias) is unique
- `type` is one of: `alt_concentrated`, `ltip`, `rsu_award`, `espp`, `crypto`, `private_equity`, `real_estate`, `direct_holding`
- `owner` matches a household member (or `joint`)
- `value` is a number
- For unvested awards, `vested: false` is set and `vest_date` is present

Manual holdings get their own rows in `positions.csv` with no underlying line-item detail (unless the user supplies it). For crypto, if the user provided per-ticker breakdown:

```yaml
- account: crypto_holdings
  type: crypto
  owner: primary
  assets:
    - { ticker: BTC, value: 100000 }
    - { ticker: ETH, value: 50000 }
```

Each `assets[]` entry becomes its own position row.

### Vested vs unvested handling

For `ltip`, `rsu_award`, and other restricted comp:

```yaml
- account: ltip_award_2027
  type: ltip
  owner: primary
  employer: employer_a
  value: 1137000
  tax_haircut: 0.40
  vested: false
  vest_date: 2027-03
```

The skill emits TWO views downstream:

- **Vested only** (`vested: true` or `vested` omitted) — the default investable total
- **Vested + unvested** — surfaces full economic exposure including awards that haven't vested yet

Never silently combine them. Always label which view is being shown.

### Tax haircut application

When `tax_haircut: 0.X` is set on an account (typically NQDC, LTIPs, deferred comp), emit two value columns:

- `market_value_gross` — face value
- `market_value_net` — `market_value_gross * (1 - tax_haircut)`

Default to showing both. Some analyses use gross (concentration), some use net (deployable wealth). Document the choice per output.

## Step 5: Real estate methodology

Apply per-property methodology from config.

### Carrying methodology (default)

```
net_equity = market_value - mortgage_balance
```

Simple and matches most users' balance sheets.

### Liquidation_net methodology

```
selling_costs = market_value * 0.06         # typical agent + closing
gross_proceeds = market_value - selling_costs - mortgage_balance
capital_gain = max(0, market_value - cost_basis - selling_costs)
sec_121_exclusion = 500_000 if use == "primary" and married else 250_000 if use == "primary" else 0
taxable_gain = max(0, capital_gain - sec_121_exclusion)
fed_cap_gains_tax = taxable_gain * 0.20
nii_tax = taxable_gain * 0.038
state_tax = taxable_gain * state_rate     # config: state_marginal_rate
depreciation_recapture = accumulated_depreciation * 0.25   # if use == "investment"

net_equity_liquidation = gross_proceeds - fed_cap_gains_tax - nii_tax - state_tax - depreciation_recapture
```

Surface inputs and result for user review. The intermediate fields (gross_proceeds, taxable_gain, etc.) are useful for transparency.

### Methodology mismatch warning

If the user's spreadsheet shows different RE values than the methodology produces, flag the mismatch:

> "RE valuation method drift: your spreadsheet has [rental_1] at $X net equity (carrying), but config specifies liquidation_net which computes $Y. Either change the methodology or accept the $Z difference."

## Step 6: Household reconciliation

If the user provided a balance-sheet spreadsheet, reconcile each account's consolidated total against the spreadsheet's reported value.

```python
for account in consolidated:
    sheet_value = sheet_lookup(account.alias)
    consol_value = sum(p.market_value for p in account.positions)
    if sheet_value is None:
        continue                              # not on sheet; nothing to check
    diff = abs(sheet_value - consol_value)
    pct = diff / max(sheet_value, consol_value)
    if diff > 1000 and pct > 0.01:           # >$1k AND >1% — material
        emit_reconciliation_warning(account, sheet_value, consol_value)
```

Tolerance is looser here than in ingest (the spreadsheet is typically a different date than the statement; some drift is expected). The goal is to catch material mismatches that signal real data issues.

Common reconciliation patterns:

- **Spreadsheet > statement** — user has been updating the spreadsheet from portal balances (more recent) while statements lag.
- **Statement > spreadsheet** — user added to an account but didn't update the spreadsheet.
- **One side missing entirely** — account exists in spreadsheet but no statement provided (or vice versa).

Surface each material mismatch with a hypothesis ("likely spreadsheet drift since [statement_date]") rather than asking the user to figure out the cause.

## Step 7: Emit `positions.csv`

Final schema:

```
account               # logical alias (e.g., "brokerage_1", "retirement_primary")
account_type          # taxable_brokerage / qualified_401k / roth_ira / nqdc / etc.
wrapper_structure     # null / revocable_trust / irrevocable_trust / llc
owner                 # primary / spouse / joint / etc.
joint_share           # null unless joint; e.g., 0.5
employer              # null unless wrapper is employer-linked (NQDC, RSU, LTIP, etc.)
nested_inside         # null unless this row came from a nested PCRA/BrokerageLink
ticker                # security identifier (or "CASH")
description           # security name
section               # cash / equity / mutual_fund / etf / bond / alt / real_estate / crypto
quantity              # shares/units (null for cash, RE, alts)
price                 # per-share (null when N/A)
market_value_gross    # face $ value
market_value_net      # after tax_haircut if applicable; equal to gross if no haircut
cost_basis            # if available
unrealized_gain       # if available
vested                # true / false / null (only relevant for restricted comp)
vest_date             # ISO date (only relevant for vested == false)
est_annual_income     # if statement provided
est_yield             # if statement provided
income_character      # qualified_dividend / ordinary / muni / return_of_capital / mixed / unknown
methodology           # for real estate: carrying / liquidation_net
liquid                # true if convertible to cash within ~5 business days
source_file           # original filename (for audit trail)
notes                 # free-form, used for FOLLOW_UP flags and similar
```

## Output side-effects

In addition to `positions.csv`:

- `consolidation_summary.md` — a markdown file with:
  - Detected accounts and their inferred types (high-confidence ones documented, ambiguous ones noted)
  - Detected nestings (which child collapsed into which parent)
  - Manual holdings injected
  - Reconciliation warnings (if any)
  - Total investable, total net worth, vested-only total — all clearly labeled

- `consolidation_log.csv` — per-action audit trail (which heuristic fired, what value was matched, etc.). Useful for debugging.

## Common failure modes (and what to do)

**1. Two NQDC plans (e.g., a separation grant + an ongoing deferral) look like the same plan.** The plan name might be similar across statements. Distinguish by account number prefix or grant year. Don't dedupe these as nestings.

**2. A "pension" statement is actually a frozen cash balance plan that's been converted to lump-sum eligibility.** Treat carefully — if the user has the option to roll it to an IRA, model as `pension_cb` with `rollable: true`. The asset-class is still bond-like but the wrapper-flexibility differs.

**3. Joint account with unequal contribution.** The user wants something other than 50/50 attribution. Honor the `joint_attribution` config; don't assume.

**4. Account showed up last quarter but isn't in this quarter's statements.** Two possibilities: account was closed, or the user forgot to grab the statement. Surface as an anomaly ("account [X] was present in prior consolidation but no current statement found — closed or missing?"). Don't silently drop.

**5. Brand-new account this quarter that wasn't in config.** Inferred type with default heuristics; surface for confirmation; offer to add to config so refresh is consistent next quarter.

**6. The spreadsheet has accounts not in any statement.** Add as `manual_holdings` with `value` from spreadsheet. Flag for user — they may have intended to grab a statement but forgot.

**7. The user's "Net Asset" column on their spreadsheet doesn't match `market_value_gross - mortgage` for RE.** Either the user is using liquidation_net implicitly (with their own assumptions), or there's a math error in the sheet. Surface and ask.

**8. Tax haircut applied to wrong account.** Default haircut applies to NQDC/LTIPs/RSUs; should NOT apply to qualified retirement accounts (which are already tax-deferred but distribute at then-current ordinary rates, which are unpredictable). Surface if config seems to apply haircut to a qualified account.

**9. Real estate "use" wrong.** If a property's `use: investment` but the user actually lives in it part-time, classification's wrong. Surface based on whether the property generates rental income (which the spreadsheet may indicate).

## What this phase does NOT do

- It does not classify holdings into asset classes (that's `classify.md`).
- It does not run concentration / fee / tax-location analysis (that's `report.md`).
- It does not produce charts.
- It does not write a final commentary.
- It does not make any judgments about whether the consolidated state is "good" or "bad."
- It does not propose any actions.
