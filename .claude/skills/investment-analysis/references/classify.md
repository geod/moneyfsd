# Classify

Phase 4: map every holding in `positions.csv` to an asset-class breakdown, sector (for equity), and distribution character. This is the through-the-fund layer — turning "I own 100 shares of VTI" into "this is $X of US equity, weighted ~28% technology, generating qualified-dividend income."

This phase is **deterministic for known funds, interactive for unknowns**. Never silently fabricate a classification for a fund whose composition you can't verify — that's how the entire analysis becomes wrong while looking complete.

## Inputs and outputs

**Inputs:**
- `positions.csv` from consolidate
- `references/data/fund_asset_class_map.yaml` — the curated ticker registry
- `references/data/stock_sector_map.yaml` — ticker → sector for individual equities
- `references/data/distribution_character.yaml` — rules for inferring tax character
- The user's local `investment_analysis_config.yaml` `fund_overrides` block

**Outputs:**
- `positions_classified.csv` — `positions.csv` enriched with asset-class weights, sector, expense ratio, income character
- `classification_unknowns.md` — list of any holdings the skill couldn't classify, surfaced for one-shot user review
- Updates to the user's local config: any resolved unknowns are written into `fund_overrides` so the next refresh skips the prompt

## Step 1: Fund / security lookup

For each row in `positions.csv`, resolve in priority order:

**Priority 1: User override (`fund_overrides` in local config).**

```yaml
fund_overrides:
  PIMIX: { us_bonds: 0.75, intl_bonds: 0.20, cash: 0.05 }
  CUSTOM_FUND_XYZ: { us_equity: 0.60, intl_dev_equity: 0.40 }
```

User-supplied breakdown wins over the registry. This handles funds the registry doesn't cover and lets the user correct registry mistakes.

**Priority 2: Curated registry (`references/data/fund_asset_class_map.yaml`).**

Direct ticker match. The registry covers the major ETFs (Vanguard / iShares / Schwab / Fidelity index funds), the common active bond funds (PIMIX, DODIX, etc.), and the most-encountered target-date funds.

**Priority 3: Symbol-with-suffix variants.** Tickers sometimes appear with class-share suffixes (e.g., `VFIAX` for the same exposure as `VOO`). Maintain a synonym table so both lookup paths resolve to the same canonical entry.

```yaml
synonyms:
  VFIAX: VOO          # Vanguard 500 admiral shares → S&P 500 exposure
  VTSAX: VTI          # Vanguard Total Stock admiral → Total Market exposure
  FZROX: VTI          # Fidelity Zero Total Market → equivalent exposure
```

**Priority 4: CUSIP fallback.** Some statements use CUSIPs (especially mutual funds in retirement plans). Maintain a CUSIP → canonical-ticker map for the common ones.

**Priority 5: Unknown.** No match in overrides, registry, synonyms, or CUSIP map. The fund goes to the unknowns list. See "Unknown fund handling" below.

## Step 2: Apply asset-class weights

For each classified position:

```python
position_value = row.market_value_net   # or _gross depending on analysis context
asset_class_weights = registry[row.ticker].asset_classes

for asset_class, weight in asset_class_weights.items():
    contribution = position_value * weight
    emit_classified_row(
        position=row,
        asset_class=asset_class,
        weighted_value=contribution,
    )
```

A single position with multi-class weights (like the PIMCO 2050 TDF) generates *multiple* output rows — one per asset class. This makes downstream allocation analysis trivial: just `groupby('asset_class').sum('weighted_value')`.

Preserve the original row's metadata (account, owner, wrapper) on each output row so the analysis can still slice by wrapper.

## Step 3: Individual stock handling

For positions where the ticker is a single common stock (not a fund), look up sector in `stock_sector_map.yaml`:

```yaml
# US large-cap, by sector
AAPL: { sector: technology, region: us, market_cap: large }
MSFT: { sector: technology, region: us, market_cap: large }
NVDA: { sector: technology, region: us, market_cap: large }
JPM:  { sector: financials, region: us, market_cap: large }
JNJ:  { sector: healthcare, region: us, market_cap: large }
XOM:  { sector: energy, region: us, market_cap: large }
BRKB: { sector: financials, region: us, market_cap: large, note: "diversified conglomerate" }
```

Asset-class is `us_equity` (or `intl_dev_equity` / `intl_em_equity` per the `region` field). The sector tag feeds concentration analysis ("how much technology exposure do I have?") in the report phase.

For unknown individual stocks: rather than registry expansion (every public company would explode the registry), do a one-shot web lookup or ask the user. Persist results to the user's local `stock_overrides` block.

## Step 4: Concentrated alts

Positions with `account_type` in `{nqdc, alt_concentrated, ltip, rsu_award, espp, private_equity}` are not classified by ticker registry. They get a special asset class:

```
asset_class: alt_concentrated
issuer: <employer or company name>
liquidity: <vested-liquid | vested-illiquid | unvested>
```

The `issuer` tag is critical — it lets the concentration analysis aggregate all firm-linked exposure: M Units + LTIPs + ESPP + holdings of employer stock + (optionally) EDCP wrapper exposure.

**Never** lump these into "alternatives" as a diversified bucket. They are NOT diversified — they're concentrated bets on one company.

Sub-categories within `alt_concentrated`:

| Sub-type | Example | Treatment |
|---|---|---|
| `concentrated_equity_award` | M Units, profit units, partner capital | Single-issuer equity exposure, illiquid |
| `restricted_stock_award` | RSU, LTIP (unvested) | Single-issuer equity exposure, time-restricted |
| `employer_stock_in_plan` | ESPP, employer stock fund in 401(k) | Single-issuer equity exposure, sometimes liquid |
| `private_equity_direct` | Angel investments, LP positions, syndicated RE deals | Single-issuer or single-fund, highly illiquid |
| `convertible_employer_debt` | Convertible note, deferred bonus | Single-issuer debt/equity hybrid |

## Step 5: Real estate

Positions with `section: real_estate` are already classified — they came in as `asset_class: real_estate` from consolidate. No further work needed in this phase.

Add a `real_estate_subtype` field:
- `primary_residence` (typically excluded from investable)
- `investment_rental`
- `vacation_second_home`
- `raw_land`
- `syndication_or_partnership`

## Step 6: Crypto

Positions with `account_type: crypto` or `section: crypto`:

```yaml
asset_class: crypto
sub_asset: <BTC | ETH | other_major | altcoin>
```

Treat each major coin as its own asset (BTC ≠ ETH ≠ "altcoins"). Don't aggregate into a single "crypto" bucket unless the user has only one coin.

Distribution character: `none` (crypto doesn't generate income unless staking/yielding, which the user should declare separately).

## Step 7: Distribution character

Compute the tax character of each position's income stream. Used downstream by the tax-location audit.

| Holding type | Default character |
|---|---|
| US broad equity ETF (VTI, VOO, SCHB, etc.) | `qualified_dividend` |
| International developed equity ETF | `qualified_dividend` (foreign tax credit eligible) |
| Emerging markets equity ETF | `qualified_dividend` (FTC eligible) |
| US sector ETF | `qualified_dividend` |
| Dividend-focused ETF (SCHD, VIG, VYM) | `qualified_dividend` (mostly) |
| REIT ETF | `mixed` (mostly ordinary, partial qualified, some return-of-capital) |
| Individual REIT | `ordinary` (REIT dividends are mostly non-qualified) |
| MLP | `return_of_capital` (heavy) — flag for special K-1 handling |
| US Treasury / Agg bond ETF | `ordinary` (interest, federal-only-taxable) |
| Municipal bond ETF (VTEB, CMF, MUB) | `muni` (federally tax-exempt) |
| TIPS ETF (SCHP, VTIP) | `ordinary` (taxable inflation accruals) |
| High-yield bond ETF | `ordinary` (interest) |
| EM bond ETF (EMB) | `ordinary` (interest) |
| Multi-sector bond fund (PIMIX, etc.) | `ordinary` (interest) |
| Money market fund | `ordinary` (interest) |
| Bank sweep / cash | `ordinary` (interest) |
| Individual stock (common) | `qualified_dividend` |
| Preferred stock | `qualified_dividend` (usually; verify) |
| Concentrated employer comp (M Units, LTIPs) | `ordinary` (distributions taxed as ordinary income) |
| Crypto | `none` |

Override at the holding level via `distribution_character_overrides` in config when the user knows specifics (e.g., a particular fund has unusual return-of-capital).

## Step 8: Sector tilt — broad-market ETFs

For *concentration analysis* (which lives in report.md), we need to compute implied sector exposure through broad-market ETFs. A user with $1M of VTI and $200k of VGT has direct + implied tech exposure totaling more than the $200k direct.

The registry stores an `implied_sector_weights` field for broad funds:

```yaml
VTI:
  asset_classes: { us_equity: 1.0 }
  implied_sector_weights:
    technology: 0.28
    financials: 0.13
    healthcare: 0.12
    consumer_discretionary: 0.10
    communication_services: 0.08
    industrials: 0.08
    consumer_staples: 0.06
    energy: 0.04
    real_estate: 0.03
    utilities: 0.03
    materials: 0.02
    # (sums to 1.0; refresh annually from public index data)
```

Classify phase does not produce a sector breakdown by itself — it just attaches the implied weights to the row. The report phase walks the classified ledger and computes per-sector exposure across all holdings.

**These weights drift over time.** Refresh annually from public index methodology data (CRSP, MSCI, S&P, FTSE). Stale weights silently bias concentration numbers.

## Unknown fund handling

When a fund has no entry in user overrides, registry, synonyms, or CUSIP map, route to "unknowns" — do not silently apply any default.

### Behavior modes

Configured by `classify.unknown_fund_behavior` in `references/data/thresholds.yaml`:

**Mode A: `prompt_and_persist` (default for interactive sessions)**

1. Collect all unknowns across the whole position set.
2. Surface them as a single one-shot list to the user. Format:
   > "Quick classification check — N unknowns. For each, drop the asset-class breakdown (or say 'lookup' and I'll grab it from a fund factsheet):
   >
   > | Ticker | Description | Account | Value |
   > |---|---|---|---|
   > | UNKNOWN_1 | "Some Active Multi-Sector Bond Inst" | nqdc_1 | $123,456 |
   > | UNKNOWN_2 | "Some Target Date 2045" | qualified_401k_1 | $456,789 |
   > | UNKNOWN_3 | "Some Sector Fund" | brokerage_1 | $34,567 |"
3. User responds with breakdowns; skill writes them into `fund_overrides`.
4. Re-run classification with the new overrides — no more unknowns.

**Mode B: `web_lookup` — IMPLEMENTED**

For each unknown, the skill auto-resolves via `scripts/lookup_fund.py`:

1. **Resolve fake-ticker → real ticker.** When the input is a name fragment (e.g., the 401(k) plan parser truncates fund names to 20 chars), use Yahoo Finance's search API to find the canonical exchange ticker.
2. **Fetch candidate pages** in order: Yahoo Finance holdings → Yahoo Finance quote → Morningstar portfolio → Morningstar quote → ETF.com. Stop at the first page that yields a parseable breakdown.
3. **Parse via Claude** (`claude-haiku-4-5-20251001`). The page text is sent with a structured-output system prompt; Claude returns JSON in the asset-class breakdown schema. The prompt enforces hard rules (weights sum to ~1.0, only known asset-class keys, fold "convertibles" / "preferred" / "other" into the closest match, use current allocation for TDFs not glide-path).
4. **Persist** to `fund_overrides_auto.yaml` at the working-folder root, alongside the user's main config. Each entry carries `_lookup_source` (URL), `_lookup_date` (ISO date), `_confidence` (high/medium/low), `_fund_name`.
5. **Authority chain (high → low)**: user-edited `fund_overrides` in main config → `fund_overrides_auto.yaml` (auto-resolved) → registry (`fund_asset_class_map.yaml`) → synonyms → CUSIP map. User-edited entries ALWAYS win.

**Authentication:** uses the Anthropic SDK if `ANTHROPIC_API_KEY` is set; falls back to invoking `claude -p` as a subprocess (works inside Claude Code sessions where auth is host-managed). If neither path is available, falls back to `prompt_and_persist`.

**Cost:** ~$0.005–0.02 per unknown fund resolved (Haiku 4.5 inputs are ~30k tokens of page text).

**Failure modes:**
- Network unreachable / page returns 4xx → tries next candidate
- Page has no asset allocation content → tries next candidate
- LLM returns `found: false` or weights that don't sum to ~1.0 → tries next candidate
- All sources exhausted → falls through to `prompt_and_persist` (flagged in unknowns file)

**Mode C: `fail_loud`**

For ultra-careful runs (e.g., a final pre-publication analysis). Refuse to produce classified output until every unknown is resolved manually. No defaults, no lookups, no shortcuts.

### What NOT to do

- **Never** silently classify an unknown as `us_equity: 0.60, intl_dev_equity: 0.15, ...` "diversified mix." The analysis then looks complete and is wrong. The user has no way to know they need to fix it.
- **Never** treat unknowns as `cash` to "round out" the totals. Cash misclassification skews tax-location audit and concentration analysis.
- **Never** drop unknowns from the ledger. They have value — that value needs to be SOMEWHERE in the output.

If the user explicitly opts out of classification for a specific holding (e.g., "this is uncategorizable, just call it `unknown`"), allow it — but mark the position's contribution as `asset_class: unknown` and surface in the report's "uncovered" section. The user then sees that $X of the portfolio is uncategorized, which is honest.

## Expense ratio attachment

Every classified position carries an `expense_ratio` field from the registry (or `null` for individual stocks). Used by the fee analysis in report.

For unknowns that get resolved via web lookup, capture the ER from the factsheet at the same time. For user-provided overrides, ask for the ER alongside the asset-class breakdown.

## Index attachment

For ETFs, the registry stores the index they track:

```yaml
VTI: { index: "CRSP US Total Market Index" }
ITOT: { index: "S&P Total Market Index" }
SCHB: { index: "Dow Jones US Broad Stock Market" }
```

This feeds the TLH-pair analysis in the report phase: two ETFs tracking *different* indices in the *same* asset class are not substantially identical and form a legal TLH pair. Same index across two providers (rare) IS substantially identical.

## Common failure modes (and what to do)

**1. Fund changed strategy mid-year.** A fund's asset allocation can shift if it's actively managed. The registry stores a `last_verified` date; if the position date is more than 1 year past `last_verified`, surface as "may need refresh" — don't block, but flag.

**2. Fund liquidated; positions show $0.** Drop with a note. The unrealized-gain history might still be relevant for the report phase.

**3. Ticker collision.** Same letters mean different funds in different markets. Disambiguate using the description text, not just the ticker. (Rare, but exists for some ETFs cross-listed in foreign markets.)

**4. Custodian uses non-standard fund identifier.** Some 401(k) plans label funds by internal code rather than ticker ("Plan Stable Value Fund A" — no ticker at all). User must provide the breakdown manually. Save in `fund_overrides` under the description-as-key.

**5. Stock undergoes M&A / spinoff.** Position appears with one ticker, but the registry has it under the post-event name. Maintain an alias table for known events; surface unknowns if the event is recent.

**6. ADR / foreign listing of US-tradable security.** Treat the underlying as the same asset class as the home country issuer; sector unchanged. Note the wrapper distinction (US dividend on an ADR is qualified; on a foreign listing it depends on treaty).

**7. Closed-end fund (CEF).** Has expense ratio + leverage. Asset class from underlying, but treat the leverage premium/discount as a separate signal (out of scope for default classification; flag if material).

**8. Direct indexing account.** Some users hold the underlying 500+ stocks of an index directly (Wealthfront Direct, Frec, Schwab Personalized Indexing). The classify phase should detect this pattern (many small stock positions with one or two big ETF holdings) and label the basket as a single logical "direct index" position with sector breakdown computed from the underlying. The user can opt to treat each individual stock as a separate position (more granular), or aggregate to a single line (cleaner).

**9. ESG / SRI screened funds.** Same asset class as their unscreened equivalent for through-the-fund purposes; the user may want to track them separately for values reasons. Honor a user preference via config flag.

## What this phase does NOT do

- It does not produce any analysis output (no concentration metrics, no allocation summary). That's `report.md`.
- It does not make tax-location *recommendations*. The income character tag is descriptive; using it to suggest "move this to a different wrapper" is downstream.
- It does not estimate forward returns or yields beyond what the registry/statement provides.
- It does not compute the user's overall risk profile, drawdown estimates, or correlation matrix.
- It does not pass judgment on the user's fund selection ("PIMIX is overpriced" / "VTI is great"). The skill describes what's held; quality assessment of the choices belongs in a different layer.

## Output schema: `positions_classified.csv`

Extends `positions.csv` with new columns:

```
asset_class              # one of: us_equity, intl_dev_equity, intl_em_equity,
                         #         us_bonds, intl_bonds, cash, real_estate,
                         #         alt_concentrated, crypto, unknown
asset_class_weight       # 0.0–1.0 — fraction of position in this asset class
weighted_value_gross     # market_value_gross * asset_class_weight
weighted_value_net       # market_value_net * asset_class_weight
sector                   # for us_equity / intl_dev_equity: technology, financials, etc.
                         # null for non-equity
region                   # us / intl_developed / emerging
sub_asset                # for crypto: BTC / ETH / other_major / altcoin
                         # for alt_concentrated: concentrated_equity_award / ltip / etc.
                         # for real_estate: primary_residence / investment_rental / etc.
issuer                   # for alt_concentrated: the employer/company name
                         # for individual stocks: the company
                         # null otherwise
distribution_character   # qualified_dividend / ordinary / muni / return_of_capital /
                         # mixed / none / unknown
expense_ratio            # annual ER from registry; null if unknown
index                    # for ETFs: the tracked index; used for TLH pair detection
implied_sector_weights   # for broad-market ETFs: dict of sector → weight
classification_source    # user_override / registry / synonym / cusip / web_lookup /
                         # user_resolved / unknown
classification_date      # ISO date when this row was classified
```

One position can produce multiple rows (one per asset class for multi-class funds). Each row preserves the original position's metadata so downstream aggregations by account/owner/wrapper still work.

## Round-trip with user

After classify, surface a brief confirmation:

> "Classified [N] positions across [M] asset classes. [K] funds were unknown — I've added them to your local config so future refreshes skip the prompt. Top three sleeves by value:
>
> - US equity: $X.XM (Y%)
> - Bonds: $X.XM (Y%)
> - Real estate (investment + primary if included): $X.XM (Y%)
>
> Ready to run the report."

Don't bloat this with full analysis — that's `report.md`. Just confirm the classification ran cleanly and tee up the next step.
