# Consolidate (Phase 3)

Take raw loans + manual_entries → consolidated `loans_consolidated.csv` ready for classification.

## Operations

### 1. Apply config overrides

For each `accounts:` entry in `debts_config.yaml`, match against parsed statements by `file_match` glob. Apply the config's fields as overrides:
- `loan_id`, `owner`, `secured_by`, `rate_type`, `co_signer`, `notes` → override parsed values
- `revolving` flag → if false on a credit_card, mark as `paid_in_full` and exclude from headline debt

### 2. Inject manual entries

For each entry in `manual_entries:`, build a row with the manual values. Source: `config:manual_entries`.

### 3. Owner attribution

- Each loan has a single `owner` unless explicitly joint
- Joint loans get `owner: joint` + a `joint_share` per the household's split rule (default 50/50 — primary's share = 0.5, spouse's share = 0.5)
- The future `balance-sheet` skill consumes `joint_share` to attribute to each member

### 4. Dedup

Statement transfers (e.g., student loans moved between federal servicers) can produce duplicate rows. Dedup rules:
- **Exact match on `loan_id`** → keep the row with the most recent `statement_date`
- **Match on `lender + balance + rate` triplet across owners** → only when joint debt; merge into a single joint row
- **Match on `lender + account_number_suffix`** → same loan, different statement period; keep latest

### 5. Household reconciliation (optional)

If the user dropped a balance-sheet spreadsheet alongside their statements, reconcile each consolidated loan's balance against the spreadsheet's account-level total. Flag mismatches as data-freshness drift in `consolidation_summary.md`.

### 6. 401(k) loan cross-skill check

If `investments` skill output (`Investment Positions.csv`) exists in the same household-tracking workflow, look for 401(k) loan rows there and emit a warning if the user has also added a `401k_loan` manual entry here — likely double-counting.

## Output

`<work_folder>/.analysis/loans_consolidated.csv` — one row per loan, ready for classification.

`<work_folder>/.analysis/consolidation_summary.md` — human-readable summary:
- Total loans, total debt
- Manual entries injected
- Joint loans deduped
- Reconciliation mismatches (if any)
