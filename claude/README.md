# .claude

My Claude Code configuration: instructions, settings, skills, hooks and statusline.

## Dependencies

- `git`, `jq`, `curl`, `python3`
- [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI): API key in `~/.claude/secrets/cliproxy-api-key`, management settings in `~/.pi/agent/secrets/cliproxy-management.json` (statusline quota)
- Optional: `glab` (GitLab MR skills), `herdr` (session hook), `pngquant`, `optipng` (`optimize-images`)

## Install

```sh
git clone git@github.com:daanqq/.claude.git ~/.claude
```

If `~/.claude` already exists, initialize git there and pull instead:

```sh
cd ~/.claude
git init
git remote add origin git@github.com:daanqq/.claude.git
git fetch origin
git checkout -f -b main --track origin/main
```

Machine-specific overrides go to `settings.local.json` (ignored).
