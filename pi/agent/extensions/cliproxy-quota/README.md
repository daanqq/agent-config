# CLIProxyAPI quota footer

Shows the combined remaining Codex quota for enabled accounts exposed by the
CLIProxyAPI Management API while the selected Pi model uses provider
`cliproxy` or `openai-codex`. The latter can be configured as an override that
routes through CLIProxyAPI. The extension obtains each account's current token through
`/v0/management/api-call`; it does not read OAuth files directly.

The two subscriptions are assumed to have equal capacity, so the pool
percentage is the arithmetic mean of their remaining percentages. Individual
reset times are available through:

```text
/cliproxy:quota
/statuses
```

The footer is cleared immediately when another provider is selected. Quota is
refreshed once per minute only while a CLIProxyAPI-backed model is active. Refreshes are
deduplicated across Pi processes through a shared cache at
`~/.cache/pi/cliproxy-quota/quota.json` and an atomic lock. Thus ten Pi sessions
sharing a home directory issue one refresh, not ten. The cache contains quota
results only and never contains the management key. If the lock is busy,
sessions use the last cached result; during the first refresh they wait briefly
for the cache instead of starting duplicate requests.

The extension does not track which subscription served an individual request.
This avoids running journal queries after provider responses when routing is
not session-affine.

The footer pairs each window percentage with its nearest reset time and the
expected increase when that reset restores the affected subscription quota,
for example `89%/1h3m+4% 98%/6d20h+2%`. When every configured subscription is
available, the subscription count is omitted. Partial availability is shown as
`2/3` before the quota values. The increase assumes no additional usage before
the reset and equal subscription capacity.

Configuration:

```sh
export CLIPROXY_MANAGEMENT_URL="http://127.0.0.1:8317"
export CLIPROXY_MANAGEMENT_KEY=""
```

`CLIPROXY_MANAGEMENT_KEY` must contain the original plaintext management key,
not the bcrypt hash stored in CLIProxyAPI's `config.yaml`.

Persistent management settings are read from `~/.pi/agent/secrets/cliproxy-management.json`
with string fields `managementUrl` and `managementKey`. Keep this file mode `0600`.
When present, this file takes precedence over the environment. Without the file,
the extension uses `CLIPROXY_MANAGEMENT_URL` and `CLIPROXY_MANAGEMENT_KEY`.
Both a local CLIProxyAPI service and an SSH tunnel to a remote service must
expose the API on `127.0.0.1:8317`. Enable only one of them on a machine.
