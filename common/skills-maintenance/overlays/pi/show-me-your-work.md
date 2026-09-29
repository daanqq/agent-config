# `show-me-your-work` semantic overlay

## Preserve

- Keep one compact append-only TSV decision trail for long-running, delegated, multi-phase, or unattended work.
- Use evidence pointers and concrete result states; log decisions, pivots, blockers, and checkpoints rather than routine actions.
- Keep logs local by default and commit them only when reviewability requires it.
- Preserve safe cell handling in `scripts/log.sh`, the bundled license, and Pi metadata.
- Separate rows from different runs with `start` markers and audit only the current run's ranges against available task evidence without reading unrelated private transcripts.
- Keep corrections append-only: preserve an inaccurate prior row and supersede it with a new row and resolvable evidence.

## Replace or omit from upstream

- Remove hard dependencies on Cursor transcript locations, Cursor-only skills, and mandatory cross-model review.
- Use the active harness's actual transcript/evidence facilities when available; if they are unavailable, audit against the artifacts and session evidence that can be read safely.

## Acceptance

Do not create invented, aspirational, or padded rows. If one already exists, retain it as history and append a correction with resolvable evidence.
