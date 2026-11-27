# `cookie-debugging` semantic overlay

## Preserve

- Keep the upstream `chrome-devtools-mcp` `skills/cookie-debugging` body unchanged.
- Keep `disable-model-invocation: true` in `SKILL.md` frontmatter and `policy.allow_implicit_invocation: false` in `agents/openai.yaml` so `chrome-devtools` acts as the sole automatic router.

## Acceptance

The skill is hidden from automatic discovery in Antigravity, Pi, Claude Code, and Codex, remains reachable via `chrome-devtools` and explicit invocation, and otherwise matches upstream.
