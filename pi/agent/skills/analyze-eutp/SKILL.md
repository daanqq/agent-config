---
name: analyze-eutp
description: Analyze an ESOFT EUTP issue against the codebase, read-only. Use for analysis or planning requests that contain an EUTP ticket URL or ID.
---

# Analyze EUTP

Unless the user explicitly requests implementation, keep the work read-only.

Get the issue context with the [`fetch-eutp` skill](../fetch-eutp/SKILL.md) and follow its rules for
credentials, linked issues, and attachments. Analyze only that issue's
description and metadata.

Completion criterion: the target issue and relevant accessible attachments
have been analyzed without unrequested related-issue fetches.

If the user requests implementation, first decide whether repository isolation is needed.
Use the `eutp-worktree` skill only when the user requests a worktree, the original
checkout contains pre-existing or unrelated changes, multiple repositories need
independent changes, or the task explicitly requires isolation. If the original
checkout is clean and only one repository is affected, implement in the original
checkout on the task branch.

If work for the same ticket was already transferred from a worktree, inspect the
original checkout and continue there on its established task branch. Do not create
another worktree merely because the checkout contains the already-transferred
changes.
