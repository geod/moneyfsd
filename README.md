# moneyfsd

**Full self-driving for your personal finances, built on Claude.**

The goal of this project is to take the work that a thoughtful person
does once a year with a spreadsheet — categorize spending, surface
anomalies, audit subscriptions, plan a budget, rebalance investments,
prep taxes, project retirement — and let an AI do it continuously,
on your data, with you in the loop.

`moneyfsd` is built as a set of composable Claude Code skills, one per
financial workflow. **This first release is `expenses`**, a skill that
turns a pile of raw bank and credit-card statements into a single
consolidated, categorized, person-attributed lifestyle ledger.

Planned modules:
- **expenses** *(released)* — categorise & analyse spending
- **investments** — portfolio analysis, allocation drift, rebalancing
- **taxes** — annualised tax position, deductions, estimated payments
- **retirement** — projection, contribution gaps, Roth/traditional split

---

## expenses

Drop a folder of card CSVs and checking-account PDFs in front of
Claude, invoke the skill, and you get:

- A single `Lifestyle Expenses.csv` with every transaction normalised,
  categorized, and tagged by who spent it
- A category taxonomy you can override per-household (Housing, Travel,
  Food, Kids, Holiday Home, Health, Subscriptions, etc.)
- Editorial-style charts (categories, monthly trend, person split,
  cumulative spend, sub-category breakdowns, Sankey)
- Separate excluded buckets for things that aren't lifestyle spend
  (taxes, investment transfers, rental P&L, card payoffs, family
  transfers)

The skill is interview-driven — Claude asks about your sources, your
household, and your edge cases (vacation home? rental property? joint
accounts?), then iterates with you on cleanup until Misc is under 1%
of spend.

### Privacy

**Your data never leaves your machine.** The skill is a set of
instructions and Python scripts that run locally. Claude reads your
CSVs in your existing Claude Code session to help categorize — nothing
is uploaded anywhere else. The skill itself contains no personal data.

### Install

```bash
git clone https://github.com/geod/moneyfsd.git
cp -r moneyfsd/.claude/skills/expenses ~/.claude/skills/
```

Or copy `expenses/` into any project's `.claude/skills/` directory.

### Use

Open Claude Code in a folder with your raw statements and say:

> "Help me consolidate my expenses"

Claude will pick up the skill and walk you through it.

### Requirements

- Python 3.10+
- `pandas`, `pdfplumber`, `pyyaml`, `matplotlib` (required)
- `plotly` (optional, for the Sankey diagram)

### Status

Working well for: Apple Card CSV, Chase Sapphire / Total Checking PDFs,
generic bank CSVs. Other formats may need a new ingester — the skill's
`consolidate.md` reference walks through how to add one.

---

## Roadmap

The next module is `investments`. If you'd like to contribute or have
strong opinions on what should ship next, open an issue.
