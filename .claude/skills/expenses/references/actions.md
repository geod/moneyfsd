# Actions (agent-internal: Phase 6)

The last phase. Convert patterns surfaced during analysis into 3–5 candidate decisions the user can act on, snooze, or reject. Decision support, not a lecture.

**Don't say "Phase 6" or "we're entering the Actions phase" to the user.** Frame it as "want to turn any of these into things you could act on?" See `SKILL.md` for vocabulary rules.

## When to enter this phase

Only after the analysis pass is winding down — the user has seen the patterns, pulled the threads they cared about, and isn't asking for more drill-downs. If you skip analysis and jump straight to actions, you're proposing decisions on data the user hasn't yet absorbed.

**Force-skip exception:** If the user explicitly says *"skip to actions"* / *"lets move on to takeaways"* / *"just give me the action list"*, run the needed analyses *silently* (subscriptions sweep, trip clustering, top single transactions, recurring-fee scan) to populate candidates, then deliver actions only. Don't show the analyses as deliverables — they're raw material.

## What an action looks like

**Three parts**, in this order:

1. **Observation** — a pattern from Phase 5 with a dollar number attached. Factual.
2. **Dollar impact** — what's at stake, annualized.
3. **Question** — "is that intentional?" / "want to keep, reduce, or stop?"

Do NOT include a recommendation in the action itself. The user knows their values; your job is to surface the number with a question.

### Good action

> **Streaming subscriptions: $872/year across 5 services.** Currently: Netflix, Disney+, Hulu, Apple TV+, HBO Max. Watching all 5 actively, or any candidates to drop?

### Bad action (lecturing)

> ❌ "You should cancel Hulu — you can save $144/year and get the same content on Disney+ Bundle."

The bad version assumes the user wants to optimize, knows the bundle option, and would prefer it. None of those are knowable from spending data alone. Stick to the question; let the user decide.

## How to pick which patterns to surface

Aim for **3–5 candidates** — fewer feels lazy, more is overwhelming.

**Triage rule (rough order):**

1. **Spending that feels surprising** — categories that ballooned vs. expectation, or single transactions > $1k the user might not remember.
2. **Recurring subscriptions** — the user almost always has 1–3 they forgot about.
3. **Sub-categories that hint at lifestyle drift** — e.g. food delivery > restaurants, or coffee > $50/week.
4. **Categories the user already raised concerns about during Phase 5** — they pulled the thread, so they care.
5. **High-leverage one-shots** — annual fees, insurance renewals, anything that's easy to renegotiate.

Skip anything below ~0.5% of total spend unless the user specifically asked about it.

## What to NOT include

- **Things the user has no leverage over** — mortgage P&I, property tax, kids' tuition for an enrolled school. Surface them in Phase 5 if they're large; don't propose action on them in Phase 6.
- **One-off events that won't recur** — wedding, funeral, medical surge. Note in Phase 5 as "non-recurring," exclude from Phase 6.
- **Anything you'd be embarrassed to say out loud** — "should you eat out less?" — no, not your call.

## Output format

A markdown bulleted list, one bullet per action. Each bullet:

- Bold one-line summary with the dollar number
- One- or two-sentence context
- A question, ending with `?`

Do NOT mix actions and analyses in the same list. If something is information-only (no decision), it stays in Phase 5.

## How the user responds

Three responses per action:

- **Commit** — "yes I want to do something about this" → capture the action verbatim or a brief sub-list
- **Snooze** — "not now, ask me next refresh" → save with a `snooze_until` flag
- **Reject** — "intentional, leave it alone" → save with `intentional: true` so future refreshes don't re-surface it

Persist all three states in `DECISIONS.md` so re-runs respect the user's calls.

## Output of this phase

A short action list (or `no changes` if all candidates rejected). Save next to the CSV:

```markdown
# Actions — 2026-04-26

## Committed (3)
- **Cancel Hulu subscription** — $144/year, redundant with Disney+ Bundle
- **Renegotiate auto insurance at renewal** — $2,184/year, haven't shopped in 4 years
- **Cap food delivery at 1×/week** — currently $4,200/year, target $2,000

## Snoozed (1)
- **Streaming bundle audit** — revisit at next quarterly refresh

## Rejected as intentional (1)
- **Holiday Home utilities $116/month** — non-negotiable, comes with the property
```

Stop. Don't loop into more analysis from here unless the user explicitly asks.

## Common pitfalls

- **Over-acting.** Most users come for understanding, not optimization. If the user seems satisfied at the end of Phase 5, don't push them into Phase 6 — ask if they want it.
- **Mixing actions with cleanup.** A miscategorized row is not an action; it's a Phase 4 fix. Don't surface "Should this be Travel or Sports?" as an action — that's labeling, not deciding.
- **Lecturing about lifestyle.** The user's spending reflects their priorities. Your role is to make priorities visible, not adjudicate them.
- **Burying the dollar number.** Every action must lead with a concrete annualized dollar impact. Without that number, it's hand-waving.
