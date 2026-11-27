# Skill maintenance

`check.py` validates the schema-2 shared inventory for `common`, `pi`, and
`antigravity`. It never fetches or updates a repository. The manifest remains the
source of truth for the named repository locks, provenance (`local`,
`exact`, or `overlay`), and installed hashes.

The physical inventories are `common/skills`, `pi/agent/skills`, and
`antigravity/skills`.
Client links may point only relatively to the matching `common/skills/<name>`;
they are aliases, not client-owned inventory. Hashes cover path, kind, content,
and Git's executable bit, not group-write permissions that Git does not retain.
This keeps checkouts and Git archives verifiable across different umasks.
Overlay paths are relative to this maintenance directory (for
example `overlays/common/blast-radius.md`).

```bash
python3 common/skills-maintenance/check.py
python3 common/skills-maintenance/check.py --scope pi
python3 common/skills-maintenance/check.py --check-sources
python3 common/skills-maintenance/check.py --refresh-installed-hashes
```

Refreshing is transactional: unknown entries, collisions, broken links,
frontmatter, source, overlay, or other structural errors prevent writing the
manifest. Only installed-hash drift in the selected scope is refreshable.

## Reconciling upstream skills

1. Run `python3 common/skills-maintenance/check.py` first and classify any existing drift before editing.
2. Refresh each unique upstream repository via `librarian` and record the inspected commit. Do not guess an upstream for `local` skills.
3. For `exact` skills, compare the full directory against the old and new locked source and sync only if no local customization would be lost. For `overlay` skills, read the semantic overlay and reconstruct the skill from the new upstream while preserving client adaptations, tool names, permission boundaries, and licenses.
4. A repository revision is shared across scopes: reconcile every skill pointing to that repository together and update its semantic overlay when accepted behavior changes.
5. Refresh hashes only for accepted edits (`check.py --refresh-installed-hashes --skill <scope>/<name>` or `--scope <scope>`), then verify with `check.py --check-sources` and `git diff --check`.
