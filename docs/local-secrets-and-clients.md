# Local secrets and client notes

## Local data and credentials

The repository does not import authentication files, secrets, sessions, plugin
caches, history, or old repositories' `.git` directories. Pi's checkout-specific
`.pi/settings.json` is excluded; package declarations stay in client settings
while their installers own runtime state.

## CLIProxyAPI and Tailscale

On another machine, copy `pi/agent/models.example.json` to `~/.pi/agent/models.json`
and set `CLIPROXY_API_KEY` privately. Pi sends that key to CLIProxyAPI in
`X-Api-Key`; the `apiKey` field holds a public placeholder from which Pi's Codex
client reads the account ID. The installer does not perform this copy.

Pi and Codex use CLIProxyAPI through Tailscale at
`https://new.tail354056.ts.net`; connect Tailscale with MagicDNS enabled before
starting them. The SSH tunnel to `http://127.0.0.1:8317` was removed because its
long-lived connection stalled requests for up to 20 seconds, while Tailscale to
the same server stayed stable. Existing private `~/.pi/agent/models.json` files
must be updated separately; changing the example does not update them.

## Client skill layout and Codex policy

- Shared skills live in `common/skills/` and are linked into `~/.agents/skills/`
  plus client directories via repository-relative symlinks.
- `mr-echat` remains a Pi extension; the portable skill lives in `antigravity/skills`
  and is explicitly linked into `~/.agents/skills` alongside `task-to-mr` and
  `review-gpt`, so Codex can run them too.
- Codex shares Pi's global instructions (`~/.codex/AGENTS.md` -> `pi/agent/AGENTS.md`)
  and discovers shared skills through `~/.agents/skills`. Because Codex ignores
  `disable-model-invocation`, such skills also carry `agents/openai.yaml` with
  `allow_implicit_invocation: false` (checked by `tests/test_codex_skill_policy.py`).
  `~/.codex/config.toml` stays local and is seeded once from `codex/config.base.toml`
  by `make bootstrap`.
