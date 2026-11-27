# Agent configuration platform

One repository for Pi, Claude Code, and portable Agent Skills. The clients keep
their usual HOME paths; `links.json` connects selected configuration files and
skill directories to this checkout.

## Layout

- `common/skills/`: portable skills with closed relative dependencies.
- `common/skills-maintenance/`: one source lock, scoped inventory, checker, and semantic overlays.
- `pi/`: Pi configuration, extensions, prompts, and client-specific skills.
- `claude/`: Claude Code configuration, hooks, themes, local plugin source, and client-specific skills.
- `codex/`: portable base template (`config.base.toml`), curl timeout config (`codex/curl/.curlrc`), and shell shim helper (`codex/shell/bash-env.sh` linked to `~/.config/codex-shell/bash-env.sh`). Codex shares the Pi global instructions (`~/.codex/AGENTS.md` links to `pi/agent/AGENTS.md`) and sees the shared skills through `~/.agents/skills`; it ignores `disable-model-invocation`, so such skills also carry `agents/openai.yaml` with `allow_implicit_invocation: false` (checked by `tests/test_codex_skill_policy.py`). `config.toml` stays local and is seeded once on a clean machine by `make bootstrap`.
- `t3/`: sanitized portable templates (`settings.base.json`, `keybindings.json`) seeded once by `make bootstrap` when absent.
- `scripts/install.py`: selective links, private backups, and conservative restore.
- `scripts/bootstrap.py`: idempotent post-link bootstrap (template seeding, dynamic T3 Antigravity provider linking, and global Claude MCP registration from `claude/mcp.json`).

Client skill directories contain repository-relative links to the shared
skills. HOME receives individual shared skill links in `.agents/skills/` too;
existing installer-owned skills such as Plannotator are not replaced.

`retro` stays client-specific even though its text matches: it depends on the
client-specific `writing-for-agents` skill. `mr-echat` remains a Pi extension;
the Claude skill stays in `claude/skills` and is linked into `~/.claude/skills`
and `~/.agents/skills`, so Codex can run it too. `task-to-mr` and its
`review-gpt` dependency are linked into `~/.agents/skills` the same way.

## Prepare and check

Requirements: Git, Python 3.10+, Node.js 22.6+ for offline extension tests,
Go for the native Claude hook, and the clients' existing dependencies. npm is
needed to install Pi extension dependencies. The Go hook uses only the standard
library and builds without network access.

```bash
cd ~/agent-config
make check
python3 common/skills-maintenance/check.py --check-sources
python3 scripts/install.py --backup-existing
```

When editing Pi extensions or `pi/agent/scripts/install-dependencies.mjs`,
run `make dep-dev && make check-extensions-dev` to execute per-extension test
suites (`firecrawl-search`, `background-terminals`) that rely on `devDependencies`.

The Bash `PreToolUse` guard runs a native binary at
`~/.local/libexec/agent-config/grep-literal-glob`, not `go run` or Python. It
single-quotes unquoted globs in grep `--include`/`--exclude` through
`updatedInput` (a partly quoted glob is blocked instead), and blocks test,
typecheck or lint commands piped straight into grep, rg or head without pipefail
or a `PIPESTATUS` read in the next command, pointing to
`prove-it-works/scripts/run-check.py`. It also blocks `rm` with an unquoted glob
over `run-check-*` log directories, which parallel sessions share.
`make install-hooks` builds and atomically replaces only this binary; a failed
build retains the installed version. Run it after editing
`claude/hooks/grep-literal-glob.go`. Tests build their own temporary binary.

The `Stop` hook `~/.local/libexec/agent-config/reply-language` is built by the
same `make install-hooks` from `claude/hooks/reply-language.go`. When the last
real user message contains Cyrillic but the final reply has no Cyrillic and more
than 200 letters outside code, inline code, URLs and paths, it returns
`{"decision":"block","reason":...}` asking for a Russian rewrite. It does nothing
when `stop_hook_active` is true, so it fires at most once in a row, and it fails
open on any input or transcript error. Run `make install-hooks` after editing
the source or Claude Code will keep using the installed binary.

The last command is a **dry run**. `--backup-existing` lets it plan replacing
occupied paths; no HOME paths are changed without `--apply`.

`--check-sources` reads locked Git revisions from `~/.cache/checkouts/`. It does
not fetch. Missing source caches are reported, not silently reconstructed.

Exact upstream copies retain their original formatting. `.gitattributes`
permits upstream trailing whitespace only in the DnD and Vercel skill trees;
source checks still require their complete contents to match the locked commits.

## Commit checks

Enable this checkout's pre-commit hook explicitly:

```bash
git config --local core.hooksPath .githooks
```

If another hooks path or active pre-commit already exists, reconcile it before
changing the setting. The hook runs the existing `make check` against a private
snapshot of the Git index, not the working tree. It does not stash, modify the
original index, install links, or refresh skill hashes. Unstaged fixes cannot
hide a broken staged snapshot; unrelated unstaged files remain untouched.
Stage the intended code, manifest entries, and links together before committing.
The coverage check requires an individual HOME mapping in `links.json` for every
physical skill and client skill alias. A deliberately repository-only skill can
be listed in the optional `uninstalled_skills` object, mapping its repository
source path to a nonempty reason. Stale exclusions and mapped-but-excluded skills
are errors; existing manual HOME links do not substitute for installation mappings.

## Connect HOME

This checkout is prepared separately; the original clients are not switched
automatically. Review the dry run and stop Pi and Claude Code before connecting
to avoid concurrent settings writes. Install the existing locked extension
dependencies in the new checkout first:

```bash
make bootstrap-plan
make bootstrap
```

`make dep` installs only the consolidated runtime extension dependencies in
`pi/agent/extensions` (`npm ci --omit=dev --ignore-scripts`). Use `make dep-dev`
when you need per-extension `devDependencies` (`tsc`, `@effect/tsgo`, Pi types)
for local extension development. `make bootstrap` runs `install-hooks`, `dep`,
`install`, and `scripts/bootstrap.py --backup-existing --apply` (seeds missing
`~/.codex/config.toml`, `~/.t3/userdata/{settings,keybindings}.json`, and
`~/.gemini/antigravity-cli/settings.json`, links
active T3 Antigravity provider instances dynamically, and registers missing
global Claude MCP servers from `claude/mcp.json`). Existing local configs are
never overwritten.

Dependencies are not copied from the old clients, and `make dep` needs network
access. The installer also links `pi/agent/extensions/node_modules` into HOME so
the extension loader can resolve runtime dependencies from the linked files.
These directories stay local and untracked; existing HOME dependency directories
are backed up and can be restored like configuration. Installing links before
`make dep` is supported: dependency links remain dangling until npm creates the
directories. Afterwards start new client sessions, or reload Pi's resources.

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

On another machine, copy `pi/agent/models.example.json` to
`~/.pi/agent/models.json` and set `CLIPROXY_API_KEY` privately. Pi sends that
key to CLIProxyAPI in `X-Api-Key`. The `apiKey` field contains a public
placeholder from which Pi's Codex client reads the account ID. The installer
does not perform that copy.

Claude and the Pi example use CLIProxyAPI through Tailscale at
`https://new.tail354056.ts.net`; connect Tailscale with MagicDNS enabled before
starting them. The SSH tunnel to `http://127.0.0.1:8317` was removed: its
long-lived connection stalled requests for up to 20 seconds, while Tailscale to
the same server stayed stable. Existing private `~/.pi/agent/models.json` files must be updated separately;
changing the example does not change them. API keys stay unchanged.

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
Use `https://new.tail354056.ts.net` for `managementUrl` or
`CLIPROXY_MANAGEMENT_URL`, not the separate panel's HTTPS port 18443.
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
