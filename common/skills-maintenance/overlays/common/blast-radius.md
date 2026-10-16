# `blast-radius` semantic overlay

## Preserve

- Keep automatic model invocation and the shared trigger description.
- Keep the explicit evidence ladder, with level 4 as the boundary for a proven claim.
- Follow repository permissions: read-only reviews use existing checks or task-owned temporary scripts; database access, external writes, and repository edits require the applicable authorization.
- Limit delegation to one genuinely independent slice by default and verify delegated findings in the parent.

## Replace or omit from upstream

- Replace Cursor-only calls to `arena`, `unslop`, and other unavailable skills with direct instructions.
- Replace unconditional demands to create repository scripts with the cheapest proof allowed by the task mode.
- Keep the report focused on behavior delta, safety facts, confirmed and cleared risks, remaining checks, and gaps.

## Acceptance

The skill must find one or two load-bearing safety facts, prove them as directly as the environment allows, and label anything below executable proof as unproven.

For a repeat pass after an identity or async-state finding was fixed, completion requires the established invariant's key scope or state-freshness point, all dependent operations in the affected path, and current evidence or an explicit gap for each. Keep this pass narrow; fixing only the flagged line is not sufficient.
