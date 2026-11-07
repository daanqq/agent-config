# `chrome-devtools` semantic overlay

## Preserve

- Keep the upstream content of `chrome-devtools-mcp` `skills/chrome-devtools` unchanged, including automatic invocation and the `--slim` exclusion.
- Keep the local login rule under "Logging in" in `SKILL.md`: when a page requires a login and the project has no login script, request credentials with the T3 `request_secret` tool (`delivery: "file"`), fill the form from a script that reads the files, never echo the values, and never ask the user to log in by hand.

## Replace or omit from upstream

- Nothing is removed from upstream; the login rule is the only addition.

## Acceptance

After an upstream update the "Logging in" section is still present, and the rest of the skill matches upstream.
