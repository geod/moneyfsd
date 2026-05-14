# Evals

Minimal eval fixtures for the `investment-analysis` skill.

The full eval set will grow over time as new statement formats, edge cases, and
custodians get added. This directory ships with one canonical scenario.

## Fixture: `fixture_canonical/`

A synthetic household with:

- **One taxable brokerage account** — broad ETFs (VTI, VEA, VWO), a few individual
  large-cap stocks, idle cash from a recent deposit
- **One qualified 401(k)** with a nested PCRA sleeve — exercises the
  PCRA-in-401(k) dedup
- **One NQDC (executive deferred comp) plan** with a nested PCRA — exercises the
  trustee-vs-custodian distinction
- **One Roth IRA** — small balance, US broad equity only
- **One HSA** — half invested, half cash sweep
- **One 529** — target-date age-based portfolio (excluded from investable per default)
- **A balance-sheet spreadsheet** with all of the above plus manual entries
  for crypto and real estate

All names are generic (`primary`, `spouse`, `employer_a`). No real custodian
identifiers, no real account numbers (all masked), no real addresses.

## Expected outputs

`expected/` holds the expected `positions.csv`, `Allocation.csv`,
`Concentration.md` (key facts only), and similar — for regression testing.

## Running

```bash
cd .claude/skills/investment-analysis
python scripts/extract_positions.py evals/fixture_canonical
python scripts/consolidate.py evals/fixture_canonical --config evals/fixture_canonical/investment_analysis_config.yaml
python scripts/classify_funds.py evals/fixture_canonical --config evals/fixture_canonical/investment_analysis_config.yaml
python scripts/analyze.py evals/fixture_canonical --config evals/fixture_canonical/investment_analysis_config.yaml
python scripts/generate_charts.py evals/fixture_canonical
python scripts/generate_report.py evals/fixture_canonical
```

Then diff the produced artifacts against `evals/fixture_canonical/expected/`.

## Adding new fixtures

When a new custodian / statement format / edge case is added, create:

```
fixture_<name>/
  <synthetic statements>          # PDFs / CSVs — synthetic only, NO PII
  investment_analysis_config.yaml # generic config
  expected/                       # known-good artifacts for regression
```

PII rule: synthetic statements use generic names (`Employer A`, `Person A`,
`123 Main St`) and made-up but realistic account numbers. **Never** use any
real names, employers, or property identifiers in fixtures — even if they're
the developer's own. Per the project's standing memory rule on genericisation.
