# `fix-merge-conflicts` semantic overlay

## Preserve

- Keep `disable-model-invocation: true`; this workflow should run only by explicit user invocation.
- Preserve the upstream conflict-resolution workflow otherwise.

## Acceptance

The skill remains hidden from automatic discovery and reports resolved files, notable choices, and build/test outcomes.
