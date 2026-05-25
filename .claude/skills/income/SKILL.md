---
name: income
description: Interview-driven workflow for capturing and analyzing W-2 income. User either drops one or more W-2 PDFs or walks through the boxes interactively, and gets back a short descriptive breakdown — gross, tax stack (federal, state, FICA), pre-tax deductions, take-home — plus internal consistency checks on the W-2. Strictly descriptive — describes what the W-2 says, never recommends withholding changes, contribution rates, or comp moves. Use whenever the user wants to understand their W-2 income at a glance. Trigger on phrases like "what do I earn", "analyze my W-2", "income breakdown", "take-home pay", "effective tax rate", "income analysis", or when the user drops a W-2 PDF. Future versions will add 1099, K-1, investment income, rental, and retirement income — currently W-2 only.
---

# Income

## What this skill does

Walks the user through their W-2 income. They can either drop one or more W-2 PDFs (the skill extracts every box) or walk through the boxes interactively. Output is a short descriptive analysis shown inline in the conversation — no separate report file is written.

## v1 scope

**W-2 employment income only.** Other income types (1099, K-1, investment, rental, retirement, other) are not yet supported. If the user mentions one, acknowledge it'll come later and proceed with the W-2 portion.

If the user explicitly insists on adding a non-W-2 source mid-conversation (e.g., drops a rental income spreadsheet and says "add this"), do a **descriptive-only ingest** rather than refusing twice: read the file, surface a cash view and a tax view, flag every missing input (depreciation schedule, cost basis, etc.), and roll it into the household total as a clearly-labeled out-of-scope addition. The same banned-vocabulary rules apply. Do not invent Schedule E categories that aren't supported by the source data.

## What this skill does NOT do

This is **descriptive only**. Never:

- Recommend withholding changes ("you should adjust your W-4")
- Recommend contribution rates ("max your 401(k)", "increase your HSA")
- Comment on comp structure, RSU/ESPP timing, or tax-bracket optimization
- Project or model anything forward — that's downstream

Those belong in a downstream `financial-planning` skill that takes this skill's output as one of its inputs. If the user asks for recommendations, redirect.

**Banned vocabulary in output:** *you should*, *consider*, *recommend*, *worth*, *would be wise*, *target*, *under-saving*, *over-withheld*, *under-withheld*, *optimize*, *improve*. State facts; don't editorialize. The user (or a downstream skill) decides what's high or low.

## The flow

### 1. Ask

> "Let's look at your W-2 income. Two ways — drop your W-2 PDF(s) in a folder and tell me the path, or walk through the boxes with me (takes a couple of minutes per W-2). Which works?"

Skip the menu if the user has already signalled — e.g., they dropped a file in the conversation, or they said "I'll just tell you the numbers." Also ask up front: *how many W-2s — just yours, or also a partner/spouse?*

### 2. Capture

**Path A — drop W-2 file(s):**

Files may arrive as PDFs (text-based or image-only scans), JPG/PNG photos, or HEIC→PDF exports. **Always parse the file at the attached path directly.** Do not assume any image pasted into the chat is the contents of an attached file path — they may be different documents, and conflating them produces silently wrong analysis.

Parsing pipeline:

1. **List first.** If the user points at a folder, `ls` it and enumerate every file with format + size. Confirm with the user which file corresponds to which person before parsing.
2. **Text extraction.** Try `pypdf` (`PdfReader(...).pages[0].extract_text()`). On macOS, `pdftotext` is not installed by default — don't rely on it. `pdfplumber` is a layout-sensitive fallback.
3. **Image-only PDFs.** If `extract_text()` returns empty or near-empty, the PDF is a scan. Extract the embedded image (`page.images[0].data`) to a temp file and read it as an image — most W-2 PDFs from phone scanners or HEIC exports fall into this bucket.
4. **JPG/PNG/HEIC directly.** Read as image.

Extract these fields per W-2:

- Employee name, employer name, year
- Boxes 1, 2, 3, 4, 5, 6
- Every Box 12 entry (code + amount) — *including* C (GTL imputed), D (401k), Y (NQDC §409A), DD (employer health), and any others present
- Box 13 checkboxes (retirement plan, statutory employee, third-party sick)
- **Box 14** — capture if present (CA SDI, CA VPDI, NJ SDI, NY SDI, etc. are mandatory cash deductions and DO affect take-home)
- Boxes 15–17 (state, state ID, state wages, state tax)

If you can't extract cleanly, fall back to Path B for any uncaptured boxes — don't guess.

**Filename vs Box e mismatch.** If the filename suggests person A (e.g., `w2-alice.pdf`) but Box e on the form names person B, surface the mismatch once and ask which to trust. Don't loop on it. The user is authoritative — once they answer, proceed and don't re-litigate.

**Path B — interview entry:**

Ask for these boxes per W-2. Use `AskUserQuestion` or accept a freeform paste:

| Box | What to ask |
|---|---|
| 1 | Wages, tips, other comp (the federal taxable number) |
| 2 | Federal income tax withheld |
| 3 | Social Security wages |
| 4 | Social Security tax withheld |
| 5 | Medicare wages and tips |
| 6 | Medicare tax withheld |
| 12 | Any codes + amounts. Common: D = 401(k) traditional, AA = Roth 401(k), W = HSA, Y = NQDC §409A current-year deferral, C = GTL > 50K (imputed non-cash, included in Box 1/3/5), DD = employer health cost (informational only) |
| 14 | Ask if there's anything in Box 14. State disability lines (CA SDI, CA VPDI, NJ SDI, NY SDI, HI TDI, etc.) are mandatory and reduce take-home — capture the amount. RSU/ESPP entries here are usually informational only; if mentioned, prompt: *"Is the RSU/ESPP amount already included in Box 1? Most employers include it."* |
| 17 | State income tax withheld (skip if no state tax) |

Skip blank boxes.

### 3. Confirm + analyze

Show the captured values back to the user, run the internal consistency checks, and produce the inline analysis. Everything in the conversation — no files written.

**Internal consistency checks** (run all five; surface any failure rather than silently proceeding):

| # | Check | Tolerance |
|---|---|---|
| 1 | Box 5 ≥ Box 1 | exact |
| 2 | (Box 5 − Box 1) reconciles to the sum of Box 12 deferral codes that reduce Box 1 but not FICA — primarily D (401k traditional), E (403b), G (457b), S (SIMPLE), Y (NQDC §409A current-year deferral). If the gap doesn't reconcile, pre-tax health/FSA likely accounts for the residual (those reduce both Box 1 and Box 5 and so are invisible here — the residual size is itself informative) | small residual OK |
| 3 | Box 3 capped at SS wage base for the year (168,600 in 2024; 176,100 in 2025) | exact |
| 4 | Box 4 = Box 3 × 6.2% | 1.00 |
| 5 | Box 6 = Box 5 × 1.45% + max(0, Box 5 − 200,000) × 0.9% (Additional Medicare for employee withholding) | 1.00 |

If a check fails, surface it to the user before proceeding: *"This W-2 shows X, but the IRS formula says Y. Worth double-checking the document."*

**Display rule for all numeric output.** Do **not** prefix numbers with `$`. The Claude Code markdown renderer interprets `$<digit>` patterns as math-mode tokens and silently strips the leading digits, producing wrong-looking tables (e.g., `,048,350.49` instead of `1,048,350.49`). Use plain digits with thousands separators. If a currency label is needed, add it as a column header or table caption, not inline before each number.

**Inline analysis sections** — produce all of these as compact markdown tables in the response:

1. **Headline** — Gross (Box 5), Total tax withheld (Box 2 + Box 17 + Box 4 + Box 6), Pre-tax cash deductions visible (sum per Net formula below), Net take-home computed. Each with amount and % of gross.
2. **Tax stack** — Federal, State, SS, Medicare each as a row.
3. **Pre-tax / non-cash items** — list every Box 12 entry present and Box 14 SDI/VPDI. For each, mark whether it (a) reduces cash take-home, (b) is informational only, or (c) is imputed non-cash income included in Box 1/3/5. Footnote: pre-tax health premiums and FSA contributions reduce Box 5 silently and are invisible on the W-2.
4. **Take-home run-rate** — Annual net; monthly equivalent; bi-weekly equivalent (26 periods).
5. **Caveats** — anything that didn't reconcile, any boxes the user skipped or the parser couldn't extract, and a one-liner about v1 scope (other income types not yet covered).

**Net formula:**

```
Net cash take-home
  = Box 5
  − Box 2                       (federal income tax)
  − Box 17                      (state income tax)
  − Box 4                       (Social Security)
  − Box 6                       (Medicare incl. Additional 0.9%)
  − Box 14 mandatory disability (CA SDI, CA VPDI, NJ SDI, NY SDI, HI TDI, etc.)
  − sum of Box 12 codes that reduce cash:
      D (401k traditional), E (403b), G (457b), S (SIMPLE),
      AA (Roth 401k), BB (Roth 403b), EE (Roth 457b),
      W (HSA), Y (NQDC §409A current-year deferral)
  − Box 12 C (GTL imputed)      — subtract because it is non-cash income
                                  included in Box 1/3/5 but never received as cash
```

Do NOT subtract Box 12 DD (employer health coverage) — informational only.

Tax character is always `ordinary` for W-2 wages — only mention if the user asks.

## Multiple W-2s

If the user has more than one W-2 (mid-year job change, both partners working, or both):

- Repeat the capture step per W-2
- Roll up the analysis: headline gets per-person rows + household total; tax stack and deductions sum across W-2s
- Surface any inconsistency between W-2s for the same person (e.g., total Box 3 across all W-2s for one person exceeds the SS wage base → excess Social Security withheld, which is a fact worth stating but without prescriptive framing)

## Year alignment

All inputs combined into a single household view must share the same tax year. If the user attaches sources from different years (e.g., 2025 W-2s + 2024 rental statement), flag the mismatch and either ask for the matching year or label the combined view explicitly as "most-recent-available, mixed years" with a clear caveat. Don't silently merge across years.

## What to do when finished

End the conversation cleanly. Don't push the user toward anything. If they explicitly ask "what's next?", mention that the downstream `financial-planning` skill (when it exists) takes income + expenses + investment-analysis as inputs.
