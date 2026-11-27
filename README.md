# Agent configuration platform

One repository for Pi, Claude Code, Codex, Antigravity/T3, and portable Agent
Skills. Clients keep their usual HOME paths; `links.json` connects selected
configuration files and skill trees to this checkout.

## Layout

- `common/skills/`: portable skills with closed relative dependencies.
- `common/skills-maintenance/`: source lock, scoped inventory, checker, and semantic overlays.
- `pi/`: Pi configuration, extensions, prompts, and client-specific skills.
- `claude/`: Claude Code configuration, hooks, themes, MCP definitions, and client-specific skills.
- `codex/`: base config template (`config.base.toml`), curl timeout config, and shell shim helper.
- `antigravity/`: Antigravity/T3 instructions, hooks, MCP configs, `sph-issues-mcp.mjs` bridge, and CLI helpers.
- `t3/`: portable T3 Code templates (`settings.base.json`, `keybindings.json`).
- `scripts/`: `install.py` (selective links, backups, restore) and `bootstrap.py` (template seeding, T3 Antigravity linking, Claude MCP sync).

## Quick start

Requirements: Git, Python 3.10+, Node.js/npm (Pi extensions and `sph-issues-mcp`), Go (native hooks; stdlib only, offline build).

```bash
cd ~/agent-config
make check
make bootstrap-plan   # dry run (no HOME changes)
make bootstrap        # build hooks, install Pi deps, link HOME, seed missing templates
```

Enable the repository pre-commit hook explicitly:

```bash
git config --local core.hooksPath .githooks
```

## Documentation

- [Install, bootstrap, and restore](docs/install-and-restore.md): dry run, `skill_trees` and `uninstalled_skills`, backups, restore journal, isolated `--home`, and `make dep`/`make dep-dev`.
- [Hooks, checks, and pre-commit](docs/hooks-and-checks.md): Go hooks (`grep-literal-glob`, `reply-language`), `make check`, extension tests, and upstream source checks.
- [Local secrets and client notes](docs/local-secrets-and-clients.md): excluded local state, CLIProxyAPI over Tailscale, Claude quota footer, Codex skill policy, and skill layout notes.
- Client and skill docs: [claude/README.md](claude/README.md), [pi/README.md](pi/README.md), [common/skills-maintenance/README.md](common/skills-maintenance/README.md).
