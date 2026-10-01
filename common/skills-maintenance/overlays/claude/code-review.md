# `code-review` semantic overlay

## Preserve

- Review an explicitly bounded `branch`, `working-tree`, or combined `all` scope, including staged, unstaged, and untracked content where applicable.
- Freeze commit OIDs and record a shared scope manifest so every reviewer sees identical bounds.
- Do not assume a same-name remote branch is the integration base.
- Keep Correctness, Standards, and Spec as separate axes while respecting the active project delegation limit. Explicit invocation may use three reviewers; automatic activation does not increase the limit.
- Continue Correctness and Standards review when no spec or issue-tracker integration exists, and report Spec coverage as unavailable.

## Replace or omit from upstream

- Remove the requirement to install Matt Pocock's issue-tracker setup before reviewing.
- Replace mandatory two-subagent orchestration with budget-aware parent/subagent allocation.
- Replace a single three-dot diff assumption with exact commands for each supported scope.

## Add beyond upstream

Adapted from the Claude Code built-in `/code-review`:

- A Correctness axis with line-scan, removed-behavior, and TS/React pitfall angles; deep caller tracing defers to `blast-radius`.
- A finding contract requiring axis-specific evidence: failure scenario, quoted rule or smell with concrete cost, or quoted spec line.
- `CLAUDE.md` / `AGENTS.md` files governing the changed paths as standards sources, flagged only with an exact quoted rule.
- `Reinvented Helper` and `Shallow Fix` in the smell baseline.
- A parent verification pass with CONFIRMED / PLAUSIBLE / REFUTED verdicts, then per-axis dedup, severity order, and a cap of 15.

## Acceptance

Every finding must belong to the captured scope, use the actual artifacts, cite the relevant standard or requirement when available, and avoid duplicate reporting across axes.
