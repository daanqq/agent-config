# Agent configuration platform

One repository for Pi, Claude Code, and portable Agent Skills. The clients keep
their usual HOME paths; `links.json` connects selected configuration files and
skill directories to this checkout.

## Layout

- `common/skills/`: portable skills with closed relative dependencies.
- `common/skills-maintenance/`: one source lock, scoped inventory, checker, and semantic overlays.
- `pi/`: Pi configuration, extensions, prompts, and client-specific skills.
- `claude/`: Claude Code configuration, hooks, themes, local plugin source, and client-specific skills.
- `scripts/install.py`: selective links, private backups, and conservative restore.

Client skill directories contain repository-relative links to the shared
skills. HOME receives individual shared skill links in `.agents/skills/` too;
existing installer-owned skills such as Plannotator are not replaced.

`retro` stays client-specific even though its text matches: it depends on the
client-specific `writing-for-agents` skill. `mr-echat` remains a Pi extension;
the Claude skill is retained only in the Claude configuration.

## Prepare and check

Requirements: Git, Python 3.10+, and the clients' existing dependencies. Node.js
and npm are needed for Pi extensions. No new dependencies were introduced.

```bash
cd ~/agent-config
make check
python3 common/skills-maintenance/check.py --check-sources
python3 scripts/install.py --backup-existing
```

The last command is a **dry run**. `--backup-existing` lets it plan replacing
occupied paths; no HOME paths are changed without `--apply`.

`--check-sources` reads locked Git revisions from `~/.cache/checkouts/`. It does
not fetch. Missing source caches are reported, not silently reconstructed.

Exact upstream copies retain their original formatting. `.gitattributes`
permits upstream trailing whitespace only in the DnD and Vercel skill trees;
source checks still require their complete contents to match the locked commits.

## Connect HOME

This checkout is prepared separately; the original clients are not switched
automatically. Review the dry run and stop Pi and Claude Code before connecting
to avoid concurrent settings writes. Install the existing locked extension
dependencies in the new checkout first:

```bash
make dep
python3 scripts/install.py --backup-existing --apply
```

Dependencies are not copied from the old clients, and `make dep` needs network
access. Afterwards start new client sessions, or reload Pi's resources.

Existing files and skill directories are moved, not deleted, into a private run
directory under `~/.local/state/agent-config/backups/`. The installer prints its
restore journal path. Correct links are left unchanged on repeated runs.

For an isolated HOME, use `--home /absolute/path/to/existing/home`. The same
manifest is used; unknown files and runtime directories are left alone.

## Restore

```bash
python3 scripts/install.py --restore <printed-run-directory>
python3 scripts/install.py --restore <printed-run-directory> --apply
```

Restore is also a dry run by default. It refuses to overwrite an installed link
that another process replaced or changed. Backups and their journal remain
available after restoration; they are not removed automatically.

## Local data and credentials

The repository does not import authentication files, secrets, sessions, plugin
caches, history, or the old repositories' `.git` directories. The original
checkouts and their uncommitted changes remain available until you explicitly
retire them. No history was rewritten and no remote was configured.

The existing Pi `models.json` contains a literal API key and is deliberately not
linked or copied into this repository. `pi/agent/models.example.json` uses
`${CLIPROXY_API_KEY}` instead. Existing local `~/.pi/agent/models.json` continues
to work; on another machine, copy the example there and configure the variable
privately. The installer does not perform that copy.

Claude's installed-plugin state and Pi's old checkout-specific `.pi/settings.json`
are also excluded. Package/plugin declarations are retained in client settings;
their installers own runtime installation state.

After activation, edit the files in this checkout. A client or third-party
installer may replace a HOME symlink with a regular file. Re-run the installer
in dry-run mode to detect it and reconcile those changes before replacing it.

## Claude quota footer

The quota refresher uses `~/.pi/agent/secrets/cliproxy-management.json` when that
file exists. It must contain `managementUrl` and `managementKey`. If the file is
absent, it reads `CLIPROXY_MANAGEMENT_URL` and `CLIPROXY_MANAGEMENT_KEY` from the
environment inherited by Claude Code. An invalid existing file is reported as
an error; it does not fall back to environment credentials.

The key must be the plaintext CLIProxyAPI management key, not a model API key
or the bcrypt hash in the proxy configuration. Keep it outside this repository.
The management endpoint must be reachable and expose an enabled Claude account.
The scripts require `jq`, `curl`, and `setsid` for background refreshes.

## Skills

```bash
python3 common/skills-maintenance/check.py
python3 common/skills-maintenance/check.py --scope pi
python3 common/skills-maintenance/check.py --scope claude
```

Use the shared `update-skills` skill for upstream reconciliation. The global
source lock is shared; client-specific behavior is preserved in scoped overlays.
Refresh hashes only after classifying accepted changes, never to hide unrelated
drift. See `common/skills-maintenance/README.md`.
