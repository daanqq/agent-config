# `chrome-devtools` semantic overlay

## Preserve

- Keep the upstream content of `chrome-devtools-mcp` `skills/chrome-devtools` unchanged, including automatic invocation and the `--slim` exclusion.
- Keep the local login rule under "Logging in" in `SKILL.md`: when a page requires a login and the project has no login script, request credentials with the T3 `request_secret` tool (`delivery: "file"`), fill the form from a script that reads the files, never echo the values, and never ask the user to log in by hand.
- Keep the local "Taking screenshots" section in `SKILL.md`: before `take_screenshot` of a page that may be in the background, call `select_page` with `bringToFront: true`; after `Page.captureScreenshot timed out`, bring the page to the front instead of repeating the call.

## Replace or omit from upstream

- Nothing is removed from upstream; the login rule and the screenshot rule are the only additions.

## Acceptance

After an upstream update the "Logging in" and "Taking screenshots" sections are still present, and the rest of the skill matches upstream.
