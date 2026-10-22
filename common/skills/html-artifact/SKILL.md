---
name: html-artifact
description: Single-file HTML overview of code changes for a team, optionally with a before/after screen recording.
disable-model-invocation: true
---

# HTML artifact

Produce one self-contained HTML file that introduces a team to a change: what problem it solves, what each commit does and why it is done that way. It is an **overview**, not full documentation: a reader finishes it knowing the shape of the change and where to look, then reads the code for the rest. Take the scope (repository, commits or range, output path) from the arguments or the conversation; ask only for what neither gives.

## Steps

1. **Fix the scope.** Name the repository and the exact commits or range. Read code from those revisions (`git show <rev>:<path>`, `git diff`), never from the working tree: it may hold uncommitted edits that are not part of the change. Done when every section maps to one commit, or to one `base..head` range when the change is not committed.
2. **Write the content** as a content JSON for [`build.py`](build.py); its docstring is the schema. Follow the content rules below. Done when every commit in scope has a section and every block has one to three focused code refs.
3. **Add the before/after demo only when the user asks for it**, following [`DEMO.md`](DEMO.md). Done when the clip is synced and trimmed as DEMO.md requires.
4. **Build**: `python3 <skill-dir>/build.py content.json <out.html>`. Write the output outside the repository unless the user names a place. The script fails loudly on an ambiguous or missing ref anchor; fix the anchor, not the script.
5. **Verify the real page**, not the script's output line: render it in headless Chrome (`--headless=new --screenshot`, with `--autoplay-policy=no-user-gesture-required` when there is a video) and look at the screenshots; check that each code preview shows changed lines, the toggle expands it, and the page has no external `src`/`href` resources. Done when the screenshots match the rules below.

## Content rules

- **Open with the problem.** The intro states what was wrong for the user, in their terms, then a short "what now". No ticket numbers, commit hashes, file links or statistics anywhere: they read as clutter.
- **Explain why, in plain language.** Each block says what changed for the user or the team and why it is done this way; the mechanism gets one sentence at most. Prefer two short paragraphs or one list over detail. Leave out anything a reader needs only when changing the code.
- **One section per commit**, in commit order: a human title, a one-line lead saying why the commit is separate, then its blocks. The real commit subject appears small next to "commit N of M" (`subject_strip` removes task tags).
- **Code is secondary.** Each block ends with a code preview: only changed lines with one line of context, clipped with a fade, fully expanded by a toggle. Choose refs that show the decisive lines, not whole files, except for short files.
- **Language**: write the page in the user's language and set `lang` and `labels` accordingly.

## Design system

[`template.html`](template.html) is the single source of the design: AMOLED black background, one accent colour (used only for the "commit N of M" marker), muted greys for secondary text, system sans for prose and monospace for metadata and code, a 720px text column with a sticky sidebar whose first item links to the page title. Change the design there, not in generated pages, and keep it minimal: no cards, shadows, icons or extra colours.
