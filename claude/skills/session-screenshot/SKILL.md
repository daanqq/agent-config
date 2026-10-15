---
name: session-screenshot
description: Render a real Claude Code session as a PNG screenshot in the user's own theme, statusline, and font. Use when asked for a screenshot, slide image, or visual example of a skill, command, or session run.
---

# Session screenshot

The image is a **real capture**: Claude Code itself renders the session in a headless tmux with the user's config, and `shoot.py` only converts the captured screen to PNG. Never mock up or retouch the terminal; if the real capture cannot show something, say so instead.

Run everything with `python3 <skill-dir>/shoot.py`. Write outputs to a fresh directory outside project files, e.g. `/tmp/session-screenshot-<name>/`.

1. **Pick the source.** For an existing session, run `shoot.py find <skill-or-command>` and choose a run where the invocation reaches a visible result in few steps and few user turns; prefer a finished one. If the user named a session, use it. Tell the user which session you picked and why.
   A **live run** (`shoot.py live --cwd <dir> --prompt <text> --until <regex>`) costs tokens and executes tools under the user's default permission mode. Use it only when the user asks for a fresh run, and only for read-only workflows; never replay commit, push, MR, deploy, or external-write skills; resume their past session instead. `--until` should match the screen state worth showing (e.g. the last tool call to include); the run is then interrupted, and the printed session id goes to step 2. The new session stays in the user's history; mention it.
2. **Capture.** `shoot.py capture <session-id> --out <dir>` resumes a renamed copy of the transcript (the original is never touched), fits the terminal height to the transcript, and prints an index of prompt and tool rows. The default view collapses tool calls into lines like `Ran 2 shell commands`; add `--verbose` when the user wants tool calls and their output expanded, at the cost of a much taller image. A warning about a cut top means `--rows` is too small.
3. **Crop and render.** Choose the row range from the index: start at the prompt that invokes the skill (include the header only when it starts the range), end after the result; include the prompt box and statusline only when the range already reaches them, since rows are never spliced. `shoot.py render <dir> --from N --to M --png <file>` writes the PNG and its HTML. The font defaults to `IosevkaTermSlab Nerd Font Mono`; colours come from the user's Ghostty theme.
4. **Verify.** Open the PNG and check it against `screen.txt`: the crop starts and ends where intended, no line is clipped or ends in `�`, colours match the theme. Done when you have viewed the final PNG.

Report the file paths and sizes, the source session, which parts are collapsed, and anything the image exposes that the user may want hidden before sharing: personal names, internal URLs, costs in the statusline.
