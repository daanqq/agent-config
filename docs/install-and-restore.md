# Install, bootstrap, and restore

## Dry run and activation

This checkout is prepared separately; existing clients are not switched
automatically. Review the dry run and stop running clients before connecting
to avoid concurrent settings writes:

```bash
make bootstrap-plan
make bootstrap
```

`python3 scripts/install.py --backup-existing` is a **dry run**. `--backup-existing`
lets it plan replacing occupied paths; no HOME paths are changed without `--apply`.

`make bootstrap` runs:

1. `make install-hooks`: builds and atomically replaces native Go hooks under `~/.local/libexec/agent-config/`.
2. `make dep`: installs consolidated runtime extension dependencies in `pi/agent/extensions` (`npm ci --omit=dev --ignore-scripts`).
3. `make install`: links files and skills from `links.json` into HOME, moving occupied paths into a private backup directory.
4. `scripts/bootstrap.py --backup-existing --apply`: seeds missing `~/.codex/config.toml`, `~/.t3/userdata/{settings,keybindings}.json`, `~/.gemini/antigravity-cli/settings.json`, and `~/.local/share/applications/agent-chrome.desktop`, and links active T3 Antigravity provider instances dynamically. Existing local configs are never overwritten.

## Manifest and `skill_trees`

Skill directories declared in `links.json` under `skill_trees` are expanded
automatically by `scripts/install.py` for every directory containing `SKILL.md`.
A deliberately repository-only skill can be listed in the optional
`uninstalled_skills` object, mapping its repository source path to a nonempty
reason. Stale exclusions and mapped-but-excluded skills are rejected during
preflight.

Existing installer-owned skills (such as Plannotator) are not replaced. Stale
broken symlinks inside target skill directories that point into this repository
are reported in dry-run mode and pruned on `--apply`.

## Extension dependencies

Dependencies are not copied from old clients, and `make dep` needs network
access. The installer also links `pi/agent/extensions/node_modules` into HOME so
the extension loader can resolve runtime dependencies from the linked files.
These directories stay local and untracked; existing HOME dependency directories
are backed up and can be restored like configuration. Installing links before
`make dep` is supported: dependency links remain dangling until npm creates the
directories. Afterwards start new client sessions, or reload Pi's resources.

Use `make dep-dev` when you need per-extension `devDependencies` (`tsc`,
`@effect/tsgo`, Pi types) for local extension development.

## Backups, isolated HOME, and restore

Existing files and skill directories are moved, not deleted, into a private run
directory under `~/.local/state/agent-config/backups/`. The installer prints its
restore journal path. Correct links are left unchanged on repeated runs.

For an isolated HOME, use `--home /absolute/path/to/existing/home`. The same
manifest is used; unknown files and runtime directories are left alone.

```bash
python3 scripts/install.py --restore <printed-run-directory>
python3 scripts/install.py --restore <printed-run-directory> --apply
```

Restore is also a dry run by default. It refuses to overwrite an installed link
that another process replaced or changed. Backups and their journal remain
available after restoration; they are not removed automatically.

After activation, edit the files in this checkout. A client or third-party
installer may replace a HOME symlink with a regular file. Re-run the installer
in dry-run mode to detect it and reconcile those changes before replacing it.
