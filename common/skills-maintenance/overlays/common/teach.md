# `teach` semantic overlay

## Preserve

- Keep the upstream content of `mattpocock-skills` `skills/productivity/teach`: the workspace files, lessons, reference pages, assets as reusable components, mission and learning records.
- Keep the local delivery rule in the "Assets" section of `SKILL.md`: components in `./assets/` are sources, handed-out lessons and reference pages embed copies made by `scripts/inline_assets.py`, embedded copies are never edited by hand, and a page is checked by opening that file on its own.
- Keep `scripts/inline_assets.py`: it turns `../assets/` links into `data-asset` blocks and refreshes existing blocks on every run.

## Replace or omit from upstream

- Replace "link to it; never inline code a future lesson would duplicate" with the embedding rule: viewers such as the T3 Code file viewer open one HTML file without its siblings, so linked assets do not load.
- "Every lesson links" the shared stylesheet becomes "every lesson embeds" it.

## Acceptance

A new lesson opened as a single file shows its styles and working quizzes, and changing a component updates every page after one script run.
