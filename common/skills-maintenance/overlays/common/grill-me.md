# `grill-me` semantic overlay

## Preserve

- Keep `disable-model-invocation: true` in `SKILL.md` frontmatter and `policy.allow_implicit_invocation: false` in `agents/openai.yaml`.
- Inline the `grilling` design-tree interview workflow directly in `grill-me/SKILL.md` (the standalone `grilling` skill was removed).

## Acceptance

Explicit invocation runs the full design-tree interview workflow directly from `grill-me/SKILL.md` without depending on a separate `grilling` skill.
