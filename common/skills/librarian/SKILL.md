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

Downloading remote repositories into `~/.cache/checkouts/<host>/<org>/<repo>` via `checkout.sh` is pre-authorized for read-only analysis and investigations, so agents can search (`rg`) and inspect files locally without repeated API round-trips. Follow the active project instructions for working repositories. Before concluding from an existing cached checkout that a repository does not do something, refresh it (`checkout.sh`) or check its age (`git log -1 --format=%cs`): if older than 14 days and not refreshed, compare with the remote branch head (`gh api repos/<org>/<repo>/commits/<branch>` on GitHub, `glab api projects/<org>%2F<repo>/repository/commits/<branch>` on GitLab) and report the revision inspected.

If the user explicitly forbids all writes, use available read-only content or explain the access limitation.

## API vs local clone threshold

- **1-2 known files** at the latest revision of a branch: reading directly via host API is fine (`gh api repos/<org>/<repo>/contents/<path>?ref=<branch>` on GitHub, `glab api projects/<org>%2F<repo>/repository/files/<path>/raw?ref=<branch>` on GitLab) after checking `default_branch`.
- **Code search or inspecting more than 2 files**: clone locally into `~/.cache/checkouts` via `checkout.sh` (`--shallow --path-only` when full Git history is not needed; omit `--shallow` when history is required) instead of running a chain of `glab api`/`gh api` calls.

## Cache retention (30-day TTL)

Every `checkout.sh` run updates `.git/librarian-last-used` in the target checkout and automatically prunes other **clean** checkouts (empty `git status --porcelain`) under `~/.cache/checkouts` that have not been used for more than 30 days (`LIBRARIAN_TTL_DAYS=30`; pass `--ttl-days 0` to disable pruning for a single call). Dirty checkouts with local edits or untracked files are never deleted.

## Cache command

Resolve `checkout.sh` relative to this `SKILL.md` as `<skill-dir>`. `--path-only` prints only the checkout path.

```bash
bash <skill-dir>/checkout.sh <repo> --path-only
bash <skill-dir>/checkout.sh <repo> --shallow --path-only
```

Examples:

```bash
bash <skill-dir>/checkout.sh mitsuhiko/minijinja --path-only
bash <skill-dir>/checkout.sh github.com/mitsuhiko/minijinja --path-only
bash <skill-dir>/checkout.sh https://github.com/mitsuhiko/minijinja --path-only
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
bash <skill-dir>/checkout.sh <repo> --force-update --path-only
```

## Recommended workflow

1. Choose read-only inspection, isolated temporary retrieval, or authorized reusable-cache refresh under the permission boundary above.
2. For authorized cache refresh, resolve the repository path via `checkout.sh --path-only`; otherwise inspect the existing or temporary path directly.
3. Use that path and its recorded revision for searching, reading, and analysis. Refresh only when fresh content is needed and updating the cache is authorized.

## If edits are needed

Prefer not to edit directly in the shared cache. Create a separate worktree or copy from the cached checkout for task-specific modifications.

## Notes

- `owner/repo` defaults to `github.com`.
