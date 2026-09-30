#!/bin/bash
# Refreshes the Claude subscription quota cache read by statusline-command.sh.
# Mirrors ~/.pi/agent/extensions/cliproxy-quota: every enabled "claude" auth in
# CLIProxyAPI is queried through the management /api-call proxy, so tokens never
# leave cliproxy.

cache_dir="$HOME/.cache/claude-statusline"
cache_file="$cache_dir/quota.json"
lock_dir="$cache_dir/refresh.lock"
settings="$HOME/.pi/agent/secrets/cliproxy-management.json"
usage_url="https://api.anthropic.com/api/oauth/usage"

mkdir -p "$cache_dir"
# A lock older than 2 minutes belongs to a refresh that died.
if [ -d "$lock_dir" ] && [ -n "$(find "$lock_dir" -maxdepth 0 -mmin +2)" ]; then
  rmdir "$lock_dir" 2>/dev/null
fi
mkdir "$lock_dir" 2>/dev/null || exit 0
trap 'rmdir "$lock_dir" 2>/dev/null' EXIT
# Another session may have finished a refresh between our staleness check and the lock.
jq -e '(now * 1000 - .updatedAt) < 60000' "$cache_file" >/dev/null 2>&1 && exit 0

write_cache() {
  local tmp
  tmp=$(mktemp "$cache_dir/quota.XXXXXX") || return
  jq -n --argjson total "$1" --argjson accounts "$2" --argjson errors "$3" --argjson retry "${4:-0}" \
    '{updatedAt: (now * 1000 | floor), retryAt: (if $retry > 0 then (now + $retry) * 1000 | floor else null end),
      totalAccounts: $total, accounts: $accounts, errors: $errors}' >"$tmp" \
    && mv "$tmp" "$cache_file"
}

fail() {
  write_cache 0 '[]' "$(jq -n --arg e "$1" '[$e]')"
  exit 1
}

if [ -e "$settings" ]; then
  url=$(jq -r '.managementUrl // empty' "$settings" 2>/dev/null)
  key=$(jq -r '.managementKey // empty' "$settings" 2>/dev/null)
else
  url=${CLIPROXY_MANAGEMENT_URL:-}
  key=${CLIPROXY_MANAGEMENT_KEY:-}
fi
[ -n "$url" ] && [ -n "$key" ] || fail "Invalid CLIProxyAPI management settings"
base=${url%/}
[[ $base == */v0/management ]] || base="$base/v0/management"

auths=$(curl -sf -m 15 -H "Authorization: Bearer $key" "$base/auth-files" \
  | jq -c '[.files[]? | select(.provider == "claude" and (.disabled | not))
      | {name: (.name // .email // "unknown Claude account"), index: (.auth_index // .authIndex)}]') \
  || fail "Management API is unavailable"
total=$(jq 'length' <<<"$auths")
(( total > 0 )) || fail "No enabled Claude accounts found"

previous=$(jq -c '.accounts // []' "$cache_file" 2>/dev/null || echo '[]')
accounts='[]'
errors='[]'
retry_after=0
while IFS= read -r auth; do
  name=$(jq -r '.name' <<<"$auth")
  index=$(jq -r '.index // empty' <<<"$auth")
  account=
  if [ -z "$index" ]; then
    error="$name: auth_index is missing"
  else
    request=$(jq -nc --arg index "$index" --arg url "$usage_url" '{
      auth_index: $index, method: "GET", url: $url,
      header: {Authorization: "Bearer $TOKEN$", "anthropic-beta": "oauth-2025-04-20", Accept: "application/json"}
    }')
    response=$(curl -sf -m 15 -X POST -H "Authorization: Bearer $key" -H 'Content-Type: application/json' \
      -d "$request" "$base/api-call")
    status=$(jq -r '.status_code // 0' <<<"$response" 2>/dev/null)
    status=${status:-0}
    # The usage endpoint rate-limits aggressively; remember how long to back off.
    if [ "$status" = 429 ]; then
      wait=$(jq -r '(.header // {})["Retry-After"][0] // "300" | tonumber? // 300' <<<"$response")
      (( wait > retry_after )) && retry_after=$wait
    fi
    # resets_at is ISO 8601 in UTC with microseconds, e.g. 2026-09-25T23:29:59.842361+00:00.
    # A window is null while it has no usage yet, which means 100% remaining.
    (( status >= 200 && status < 300 )) && account=$(jq -c --arg name "$name" '
      (.body | if type == "string" then fromjson else . end) as $body
      | def window: if . == null or .utilization == null then null else {
          remaining: ([0, ([100, 100 - .utilization] | min)] | max),
          resetsAt: ((.resets_at // "") | sub("\\.[0-9]+"; "") | sub("\\+00:00$"; "Z") | (try fromdate catch 0) * 1000)
        } end;
      {name: $name, windows: ({"5h": ($body.five_hour | window), "7d": ($body.seven_day | window)}
        | with_entries(select(.value != null)))}' <<<"$response" 2>/dev/null)
    error="$name: quota is unavailable (HTTP $status)"
  fi
  if [ -n "$account" ]; then
    accounts=$(jq -c --argjson a "$account" '. + [$a]' <<<"$accounts")
  else
    errors=$(jq -c --arg e "$error" '. + [$e]' <<<"$errors")
    # Keep the last known windows so a transient failure does not blank the footer.
    accounts=$(jq -c --argjson prev "$previous" --arg name "$name" \
      '. + [$prev[] | select(.name == $name) | . + {stale: true}]' <<<"$accounts")
  fi
done < <(jq -c '.[]' <<<"$auths")

write_cache "$total" "$accounts" "$errors" "$retry_after"
