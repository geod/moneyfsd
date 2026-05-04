<h1 align="center">moneyfsd</h1>

<p align="center"><b>Full self-driving for your money.</b></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-C4623E?style=for-the-badge" alt="MIT License"></a>
  <a href="https://docs.claude.com/claude-code"><img src="https://img.shields.io/badge/Claude%20Code-Skill-264653?style=for-the-badge" alt="Claude Code Skill"></a>
  <a href="#-modules"><img src="https://img.shields.io/badge/modules-1%20live%20·%203%20coming-8A8278?style=for-the-badge" alt="Modules"></a>
  <a href="#privacy"><img src="https://img.shields.io/badge/100%25-local--first-264653?style=for-the-badge" alt="Local-first"></a>
</p>

<p align="center">
  <a href="#expenses">How it works</a>
  &nbsp;·&nbsp;
  <a href="#quickstart">Quickstart</a>
  &nbsp;·&nbsp;
  <a href="#privacy">Privacy</a>
  &nbsp;·&nbsp;
  <a href="#-modules">Modules</a>
</p>

---

The work a thoughtful CFO does for a household — categorise spending,
audit subscriptions, plan budgets, rebalance portfolios, prep taxes,
project retirement — done continuously by AI, on your own raw data,
with you in the loop.

`moneyfsd` ships this as a set of composable Claude Code skills, one
per financial workflow.

## 📦 Modules

| Module | Status | What it does |
| --- | --- | --- |
| **expenses** | ![live](https://img.shields.io/badge/live-2D9A6B?style=flat-square) | Categorise & analyse spending |
| **investments** | ![in development](https://img.shields.io/badge/in%20development-E2A150?style=flat-square) | Portfolio drift, allocation, rebalancing |
| **taxes** | ![planned](https://img.shields.io/badge/planned-8A8278?style=flat-square) | Annualised position, deductions, estimates |
| **retirement** | ![planned](https://img.shields.io/badge/planned-8A8278?style=flat-square) | Projection, contribution gaps, Roth split |

---

## expenses

Point Claude at a folder of credit-card and bank statements. You get a
clean ledger and a set of editorial charts that answer *where did the
money actually go* — without the manual slog.

<p align="center">
  <img src="docs/screenshots/chart_2_monthly.png" width="780" alt="Monthly spending by category">
</p>

> **Local-first.** Your statements stay on your machine. The skill is
> local Python plus instructions Claude follows in your own session —
> no uploads, no third-party servers, no Plaid.

### What's different

- [x] **Better automatic categorisation.** Traditional tools rely on
  keyword matching and leave a long tail in *Misc*. moneyfsd uses
  Claude's semantic understanding of merchants and context, backed by
  web search when a name is unfamiliar. Typical first pass: <1% of
  transactions untagged.
- [x] **Ingestion that copes with reality.** PDFs and CSVs from
  multiple banks and credit-card issuers — including statement formats
  with quirks that break naive parsers.
- [x] **Deep analysis.** AI associates spend that rule-based tools
  miss — for example pulling together every charge tied to a trip
  (flights, hotels, rideshares, eating out) whether they hit before,
  during, or after.
- [x] **Validation & anomaly hunting.** Cross-checks parsed totals
  against each statement's own summary, then surfaces loan-payment
  drift, orphan flights without hotels, drifting subscriptions, and
  duplicate income streams.
- [x] **Incremental month-over-month.** Your overrides, exclusions and
  household structure are saved to `expenses_config.yaml` so re-runs
  are cheap — not a fresh categorisation slog every month.
- [x] **Property-aware.** Vacation homes get their own category;
  rental properties get their own income-and-expenses sheet
  (`Rental P&L.csv`) kept clean of personal lifestyle spend.
- [x] **Commentary, not just a spreadsheet.** Claude tells you what
  stands out, what changed since last month, and where to look next.

<p align="center">
  <img src="docs/screenshots/chart_1_categories.png" width="780" alt="Spending by category">
  <br><br>
  <img src="docs/screenshots/chart_5_housing_sub.png" width="780" alt="Housing breakdown by subcategory">
  <br><br>
  <img src="docs/screenshots/chart_11_sankey.png" width="780" alt="Sankey: person to category to subcategory flows">
  <br>
  <sub><i>Sankey: every dollar traced from person → category → subcategory.
  Also rendered as an interactive HTML for click-and-zoom exploration.</i></sub>
</p>

> You stay in the loop. Claude works interview-style — asking about
> your household and edge cases (vacation home? rental property? joint
> accounts?) — then iterates the cleanup with you until the numbers
> feel right.

### Quickstart

```bash
# 1. Install the skill
git clone https://github.com/geod/moneyfsd.git
cp -r moneyfsd/.claude/skills/expenses ~/.claude/skills/

# 2. Put your checking account and credit card statements in a folder
# CSVs and PDFs both fine
# 12 months is ideal to get a full yearly cycle
cd ~/Documents/2026-finances/

# 3. Open Claude Code and ask
claude "Help me understand my expenses"
```

### Requirements

Python 3.10+, with `pandas`, `pdfplumber`, `pyyaml`, `matplotlib`.
Optional: `plotly` for the Sankey diagram.

### Privacy

`moneyfsd` does not connect to your bank. There is no Plaid, no
account linking, no cloud sync. You export your own statements (the
way you would for a spreadsheet), drop them in a folder, and Claude
reads them locally in your Code session. The skill itself contains
no personal data — what's in this repo is what's distributed.

---

<sub>Screenshots above are rendered from a synthetic dataset
(`docs/generate_screenshots.py`) — no real personal data is included
in this repo.</sub>
