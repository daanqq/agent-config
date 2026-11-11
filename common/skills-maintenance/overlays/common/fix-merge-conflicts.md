# `fix-merge-conflicts` semantic overlay

## Preserve

- Keep `agents/openai.yaml` with `policy.allow_implicit_invocation: false`: Codex ignores `disable-model-invocation` and reads only this policy.
- Keep `disable-model-invocation: true`; this workflow should run only by explicit user invocation.
- Preserve the upstream conflict-resolution workflow otherwise.

## Acceptance

The skill remains hidden from automatic discovery and reports resolved files, notable choices, and build/test outcomes.
