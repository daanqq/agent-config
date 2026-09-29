# Skill maintenance

`check.py` validates the schema-2 shared inventory for `common`, `pi`, and
`claude`. It never fetches or updates a repository. The manifest remains the
source of truth for the six named repository locks, provenance (`local`,
`exact`, or `overlay`), and installed hashes.

The physical inventories are `common/skills`, `pi/agent/skills`, and
`claude/skills`.
Client links may point only relatively to the matching `common/skills/<name>`;
they are aliases, not client-owned inventory. Hashes cover path, kind, content,
and Git's executable bit, not group-write permissions that Git does not retain.
This keeps checkouts and Git archives verifiable across different umasks.
Overlay paths are relative to this maintenance directory (for
example `overlays/pi/how.md`).

```bash
python3 common/skills-maintenance/check.py
python3 common/skills-maintenance/check.py --scope pi
python3 common/skills-maintenance/check.py --check-sources
python3 common/skills-maintenance/check.py --refresh-installed-hashes
```

Refreshing is transactional: unknown entries, collisions, broken links,
frontmatter, source, overlay, or other structural errors prevent writing the
manifest. Only installed-hash drift in the selected scope is refreshable.
