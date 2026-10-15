# Skill maintenance

`check.py` validates the schema-2 shared inventory for `common`, `pi`, and
`claude`. It never fetches or updates a repository. The manifest remains the
source of truth for the named repository locks, provenance (`local`,
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

## Structural migration preflight (read-only)

`check-migration-plan.py` checks an explicit repository move/removal plan before
any separate manual migration. Unlike the HOME installer's dry run, it checks
repository sources, destinations, complete inventories and Git state. It never
moves/removes files, updates the index, manifest, hashes or links, or fetches
anything. A failure anywhere rejects the whole plan. Exit status is 0 on success,
1 on validation/read errors, and 2 on invalid CLI arguments.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 common/skills-maintenance/check-migration-plan.py \
  --repo /absolute/path/to/agent-config --inventory claude/skills/example
PYTHONDONTWRITEBYTECODE=1 python3 common/skills-maintenance/check-migration-plan.py \
  --repo /absolute/path/to/agent-config --plan /tmp/migration-plan.json
```

The first command prints a snapshot for deliberate plan authoring, not approval
or automatic hash refresh. Store plans outside the repository. Schema version 1
has exactly `version` and a nonempty `operations` array. Each operation contains
exactly these fields:

- Move: `op: "move"`, `source`, `destination`, `expected`.
- Remove: `op: "remove"`, `source`, `expected`, `preserve`.

`expected` is the complete object printed by `--inventory SOURCE`, including the
root (`"."`), empty directories, ignored/untracked files and cache files. A file
entry contains `kind: "file"`, the SHA-256 of its exact bytes in `sha256`, and
`executable` (whether any executable bit is set). A directory entry contains only
`kind: "directory"`. Names inside the object are source-relative POSIX paths.
This deliberately differs from `check.py`'s skill hash, which omits caches and
empty directories. Missing hashes or added files fail; the checker does not
infer expected content from the current tree while validating a plan.

For example (replace `expected` objects with the complete inventory output):

```json
{
  "version": 1,
  "operations": [
    {
      "op": "move",
      "source": "old/example",
      "destination": "common/skills/example",
      "expected": {
        ".": {"kind": "directory"},
        "SKILL.md": {"kind": "file", "sha256": "<64 lowercase hex digits>", "executable": false}
      }
    },
    {
      "op": "remove",
      "source": "duplicate/SKILL.md",
      "expected": {
        ".": {"kind": "file", "sha256": "<64 lowercase hex digits>", "executable": false}
      },
      "preserve": {".": "retained/example/SKILL.md"}
    }
  ]
}
```

`preserve` maps **every removed file**, including clean tracked files, to one
explicit existing repository-relative file. Bytes and executable state must
match exactly. The selected copy must remain untouched by the plan: it cannot
be another removed source, moved source, destination, or overlap any of those.
Directory removals map each file's relative name; empty directories need no
copy. No semantic equivalence, ownership, implicit backup, or preservation in
Git history is assumed. A replacement is a remove plus a move to exactly the
removed source path; the removed content still needs retained copies. Move
chains, swaps, and other source/destination ancestor overlaps are rejected.

Paths must be normalized relative paths below the repository root. Repository
root/metadata paths, traversal, all symlinks (including internal aliases and
symlink ancestors), special files, nested Git metadata, duplicates and ancestor
collisions are rejected conservatively. Destinations must be absent and have no
tracked data, except for the explicit replacement case. Sources must exist with
supported types; missing tracked source files, Git conflicts and submodules
fail. Modified/untracked source content is allowed only with the exact declared
snapshot. A distinct staged version that differs from the worktree is rejected,
since the snapshot cannot preserve that extra version. Successful output reports
tracked/untracked file counts and Git status for each source. Unrelated dirty
paths are not a blocker.

This is a point-in-time preflight, not an executor, transaction, lock, or safety
guarantee against concurrent changes. Stop concurrent edits to affected paths,
review the plan, rerun immediately before any separate migration, and stop if
the tree changes. It does not check semantic references, manifest updates, or
whether the eventual manual migration implements the declared plan. Run the
normal maintenance and installer checks separately afterwards.
