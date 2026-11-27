# Hooks, checks, and pre-commit

## Verification commands

```bash
make check
python3 common/skills-maintenance/check.py --check-sources
python3 scripts/install.py --backup-existing
```

When editing Pi extensions or `pi/agent/scripts/install-dependencies.mjs`, run
`make dep-dev && make check-extensions-dev` to execute per-extension test suites
(`firecrawl-search`, `background-terminals`) that rely on `devDependencies`.

`--check-sources` reads locked Git revisions from `~/.cache/checkouts/`. It does
not fetch. Missing source caches are reported, not silently reconstructed.

Exact upstream copies retain their original formatting. `.gitattributes` permits
upstream trailing whitespace only in the DnD and Vercel skill trees; source
checks still require their complete contents to match the locked commits.

## Pre-commit hook

Enable this checkout's pre-commit hook explicitly:

```bash
git config --local core.hooksPath .githooks
```

If another hooks path or active pre-commit already exists, reconcile it before
changing the setting. The hook runs `make check` against a private snapshot of
the Git index, not the working tree. It does not stash, modify the original
index, install links, or refresh skill hashes. Unstaged fixes cannot hide a
broken staged snapshot; unrelated unstaged files remain untouched. Stage the
intended code, manifest entries, and links together before committing.

## Native Go hook

`make install-hooks` builds and atomically replaces the binary under
`~/.local/libexec/agent-config/` using only the Go standard library (offline);
a failed build retains the installed version. Run `make install-hooks` after
editing the source file, or Antigravity/T3 will keep running the old binary.
Tests build their own temporary binary.

- **`grep-literal-glob`** (`common/hooks/grep-literal-glob.go`): Bash/shell `PreToolUse` guard.
  Single-quotes unquoted globs in grep `--include`/`--exclude` through `updatedInput`
  (a partly quoted glob is blocked instead), blocks test/typecheck/lint commands
  piped straight into `grep`, `rg`, or `head` without `pipefail` or a `PIPESTATUS`
  read (pointing to `prove-it-works/scripts/run-check.py`), and blocks `rm` with
  an unquoted glob over shared `run-check-*` log directories.

## Skill maintenance checks

```bash
python3 common/skills-maintenance/check.py
python3 common/skills-maintenance/check.py --scope pi
python3 common/skills-maintenance/check.py --scope antigravity
```

Use the shared `update-skills` skill for upstream reconciliation. The global
source lock is shared; client-specific behavior is preserved in scoped overlays.
Refresh hashes only after classifying accepted changes, never to hide unrelated
drift. See [common/skills-maintenance/README.md](../common/skills-maintenance/README.md).
