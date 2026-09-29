---
name: librarian
description: "Cache and refresh remote git repositories under ~/.cache/checkouts/<host>/<org>/<repo> so future references can reuse a local copy. Use this skill when the user points you to a remote git repository as reference (or suggests you to find some repository by yourself) or you encountered a remote git repo through other means."
---

Use this skill when the user/agent points you to a remote git repository (GitHub/GitLab/Bitbucket URLs, `git@...`, or `owner/repo` shorthand).

The goal is to keep a reusable local checkout that is:
- **stable** (predictable path)
- **up to date** (periodic fetch + fast-forward when safe)
- **efficient** (partial clone with `--filter=blob:none`, no repeated full clones)

## Cache location

Repositories are stored at:

`~/.cache/checkouts/<host>/<org>/<repo>`

Example:

`github.com/mitsuhiko/minijinja` → `~/.cache/checkouts/github.com/mitsuhiko/minijinja`

## Permission boundary

Follow `AGENTS.md` for read-only work and temporary artifacts. In a read-only investigation, reuse an existing checkout without updating it when its current revision is sufficient. If fresh remote content is needed, use an isolated task-owned temporary clone outside working files rather than modifying a pre-existing shared checkout. Report the revision inspected. A request to cache or refresh the repository authorizes the reusable-cache workflow below; a reference URL alone does not authorize updating an existing checkout.

If the user explicitly forbids all writes, use available read-only content or explain the access limitation. Temporary cleanup follows the task-ownership checks in `AGENTS.md`.

## Cache command

Use this command only for an authorized cache creation or refresh. `--path-only` controls output; it does not make the command read-only.

```bash
bash checkout.sh <repo> --path-only
```

Examples:

```bash
bash checkout.sh mitsuhiko/minijinja --path-only
bash checkout.sh github.com/mitsuhiko/minijinja --path-only
bash checkout.sh https://github.com/mitsuhiko/minijinja --path-only
```

The script will:
1. Parse the repo reference into host/org/repo.
2. Clone if missing.
3. Reuse existing checkout if present.
4. Fetch from `origin` when stale (default interval: 300s).
5. Attempt a fast-forward merge if the checkout is clean and has an upstream.

## Update strategy

- Default behavior is **throttled refresh** (every 5 minutes) to avoid unnecessary network calls.
- Force immediate refresh with:

```bash
bash checkout.sh <repo> --force-update --path-only
```

## Recommended workflow

1. Choose read-only inspection, isolated temporary retrieval, or authorized reusable-cache refresh under the permission boundary above.
2. For authorized cache refresh, resolve the repository path via `checkout.sh --path-only`; otherwise inspect the existing or temporary path directly.
3. Use that path and its recorded revision for searching, reading, and analysis. Refresh only when fresh content is needed and updating the cache is authorized.

## If edits are needed

Prefer not to edit directly in the shared cache. Create a separate worktree or copy from the cached checkout for task-specific modifications.

## Notes

- `owner/repo` defaults to `github.com`.
