# Local secrets and client notes

## Local data and credentials

The repository does not import authentication files, secrets, sessions, plugin
caches, history, or old repositories' `.git` directories. Claude's
installed-plugin state and Pi's checkout-specific `.pi/settings.json` are
excluded; package and plugin declarations stay in client settings while their
installers own runtime state.

## CLIProxyAPI and Tailscale

On another machine, copy `pi/agent/models.example.json` to `~/.pi/agent/models.json`
and set `CLIPROXY_API_KEY` privately. Pi sends that key to CLIProxyAPI in
`X-Api-Key`; the `apiKey` field holds a public placeholder from which Pi's Codex
client reads the account ID. The installer does not perform this copy.

Claude and the Pi example use CLIProxyAPI through Tailscale at
`https://new.tail354056.ts.net`; connect Tailscale with MagicDNS enabled before
starting them. The SSH tunnel to `http://127.0.0.1:8317` was removed because its
long-lived connection stalled requests for up to 20 seconds, while Tailscale to
the same server stayed stable. Existing private `~/.pi/agent/models.json` files
must be updated separately; changing the example does not update them.

## Claude quota footer

The quota refresher uses `~/.pi/agent/secrets/cliproxy-management.json` when that
file exists. It must contain `managementUrl` and `managementKey`. If the file is
absent, it reads `CLIPROXY_MANAGEMENT_URL` and `CLIPROXY_MANAGEMENT_KEY` from the
environment inherited by Claude Code. An invalid existing file is reported as an
error and does not fall back to environment credentials.

The key must be the plaintext CLIProxyAPI management key, not a model API key or
the bcrypt hash from proxy config. Keep it outside this repository. Use
`https://new.tail354056.ts.net` for `managementUrl` or `CLIPROXY_MANAGEMENT_URL`,
not the separate panel's HTTPS port `18443`. The management endpoint must be
reachable and expose an enabled Claude account. Background refreshes require
`jq`, `curl`, and `setsid`.

## Client skill layout and Codex policy

- Shared skills live in `common/skills/` and are linked into `~/.agents/skills/`
  plus client directories via repository-relative symlinks.
- `mr-echat` remains a Pi extension; the Claude skill stays in `claude/skills`
  and is explicitly linked into `~/.agents/skills` alongside `task-to-mr` and
  `review-gpt`, so Codex can run them too.
- Codex shares Pi's global instructions (`~/.codex/AGENTS.md` -> `pi/agent/AGENTS.md`)
  and discovers shared skills through `~/.agents/skills`. Because Codex ignores
  `disable-model-invocation`, such skills also carry `agents/openai.yaml` with
  `allow_implicit_invocation: false` (checked by `tests/test_codex_skill_policy.py`).
  `~/.codex/config.toml` stays local and is seeded once from `codex/config.base.toml`
  by `make bootstrap`.
