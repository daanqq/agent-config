# `diagnosing-bugs` semantic overlay

## Preserve

- A diagnosis request is read-only unless the user authorizes a fix.
- Start from the exact symptom and nearest owning code, then choose the cheapest check that distinguishes the leading hypothesis from a plausible alternative.
- Runtime reproduction is preferred when safe and available, but source analysis may proceed without it; clearly separate observations, hypotheses, reproduction, and verification.
- Ask only for missing information or access that materially changes the diagnosis. Never request production access as a shortcut.
- Keep secret redaction, targeted instrumentation, comparable performance baselines, and task-owned cleanup requirements.
- Retain `references/difficult-cases.md` for intermittent, competing-cause, performance, and historical regressions.

## Replace or omit from upstream

- Remove the absolute rule that no hypothesis may be formed before a red executable loop exists.
- Remove mandatory user checkpoints, fixed hypothesis counts, and a universal six-phase ceremony.
- Do not require a regression test when no useful existing boundary can exercise the real failure.

## Acceptance

The reported cause must be supported by available evidence, and any missing reproduction or verification must remain explicit.
