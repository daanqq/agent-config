# Claude Code

Claude Code configuration: instructions, settings, keybindings, skills, hooks,
statusline, theme, and the local `effort-cycle` and `task-link` plugin sources.

## Dependencies

- `git`, `jq`, `curl`, `python3`
- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI): API key in `~/.claude/secrets/cliproxy-api-key`, management settings in `~/.pi/agent/secrets/cliproxy-management.json` (statusline quota)
- Optional: `glab` (GitLab MR skills), `herdr` (session hook), `pngquant`, `optipng` (`optimize-images`)

## Install

`~/.claude` is not a checkout. `scripts/install.py` links selected files and
skill directories from this directory into `~/.claude` according to
`links.json`; see the repository [README](../README.md) for the dry run,
backups, and restore.

Runtime state, credentials, and the skills installed by the Plannotator plugin
stay in `~/.claude` and are not tracked here.

Claude Code has no user-level local settings file: `settings.local.json` is
read only from a project's `.claude/` directory.
