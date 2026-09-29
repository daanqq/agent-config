# `code-review` semantic overlay

## Preserve

- Review an explicitly bounded `branch`, `working-tree`, or combined `all` scope, including staged, unstaged, and untracked content where applicable.
- Freeze commit OIDs and record a shared scope manifest so every reviewer sees identical bounds.
- Do not assume a same-name remote branch is the integration base.
- Keep Standards and Spec as separate axes while respecting the active `AGENTS.md` delegation budget. Explicit invocation may use two reviewers; automatic activation does not increase the budget.
- Continue correctness and Standards review when no spec or issue-tracker integration exists, and report Spec coverage as unavailable.

## Replace or omit from upstream

- Remove the requirement to install Matt Pocock's issue-tracker setup before reviewing.
- Replace mandatory two-subagent orchestration with budget-aware parent/subagent allocation.
- Replace a single three-dot diff assumption with exact commands for each supported scope.

## Acceptance

Every finding must belong to the captured scope, use the actual artifacts, cite the relevant standard or requirement when available, and avoid duplicate reporting across the two axes.
