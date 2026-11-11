# `improve-react` semantic overlay

## Preserve

- Keep `agents/openai.yaml` with `policy.allow_implicit_invocation: false`: Codex ignores `disable-model-invocation` and reads only this policy.
- Keep `disable-model-invocation: true`; a whole-codebase React audit is an explicit workflow, not an automatic response to every React task.
- Track upstream audit rules and planning guidance, including rule-description updates.
- Replace references to an installed `react-doctor` skill or `/doctor` command with direct `npx react-doctor@latest` usage or a separate focused implementation workflow.

## Acceptance

The skill remains read-only on source code, produces a prioritized audit and implementation plans, and does not turn a focused regression request into a repository-wide survey.
