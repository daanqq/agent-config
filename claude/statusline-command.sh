#!/bin/bash
# Mirrors the pi footer (~/.pi/agent/extensions/00-ui-footer.ts): line 1 is
# project (branch) on the left and model + effort on the right, line 2 is
# session token/cache/cost/context stats.

input=$(cat)
# Russian locale would print the cost with a decimal comma.
export LC_NUMERIC=C

# Unit separator instead of tab: read collapses adjacent tabs, shifting empty fields.
IFS=$'\x1f' read -r dir model effort thinking cache_expires cost cw_size cur_in cur_cr cur_cc transcript < <(
  jq -r '[
    (.workspace.current_dir // .cwd // ""),
    # Short aliases like MODEL_ALIASES in the pi footer; the id may carry a "[1m]" suffix.
    ({
      "claude-opus-5-5": "opus5.5",
      "claude-sonnet-5": "sonnet5",
      "claude-fable-5-1": "fable5.1",
      "claude-haiku-4-5": "haiku4.5"
    }[(.model.id // "") | sub("\\[.*\\]$"; "") | sub("-[0-9]{8}$"; "")] // .model.display_name // "no-model"),
    (.effort.level // ""),
    (if .thinking.enabled == false then "off" else "on" end),
    # "none" before the first response, "cold" when the last one reported no cache tokens.
    (if .prompt_cache == null then "none" else (.prompt_cache.expires_at // "cold") end),
    (.cost.total_cost_usd // 0),
    (.context_window.context_window_size // 0),
    (.context_window.current_usage.input_tokens // 0),
    (.context_window.current_usage.cache_read_input_tokens // 0),
    (.context_window.current_usage.cache_creation_input_tokens // 0),
    (.transcript_path // "")
  ] | map(tostring) | join("\u001f")' <<<"$input"
)
[ -n "$dir" ] || dir=$(pwd)

# Same theme tokens as the /effort picker (low warning, medium success, high
# permission), read from the active custom theme so the footer follows it.
# xhigh uses autoAccept instead of the pale autoAccept-shimmer, max uses
# effortUltra instead of the animated rainbow.
case "$effort" in
  low) token=warning ;;
  medium) token=success ;;
  high) token=permission ;;
  xhigh) token=autoAccept ;;
  max) token=effortUltra ;;
  *) token=claude ;;
esac
[ "$thinking" = off ] && token=inactive
theme_file="$HOME/.claude/themes/$(jq -r '.theme // "" | sub("^custom:"; "")' "$HOME/.claude/settings.json" 2>/dev/null).json"
hex=$(jq -r --arg t "$token" '.overrides[$t] // empty' "$theme_file" 2>/dev/null)
[[ $hex =~ ^#[0-9a-fA-F]{6}$ ]] || hex="#007acc"
rgb="$((16#${hex:1:2}));$((16#${hex:3:2}));$((16#${hex:5:2}))"
color=$'\033[38;2;'"$rgb"'m'
reset=$'\033[0m'

fmt_tokens() {
  awk -v n="$1" 'BEGIN {
    if (n < 1000) printf "%d", n
    else if (n < 10000) printf "%.1fk", n / 1000
    else if (n < 1000000) printf "%dk", int(n / 1000 + 0.5)
    else if (n < 10000000) printf "%.1fM", n / 1000000
    else printf "%dM", int(n / 1000000 + 0.5)
  }'
}

project=$dir
[[ $project == "$HOME"* ]] && project="~${project#"$HOME"}"
branch=$(git -C "$dir" branch --show-current 2>/dev/null)
if [ -z "$branch" ] && git -C "$dir" rev-parse --git-dir >/dev/null 2>&1; then
  branch=detached
fi
left="$project${branch:+ ($branch)}"

if [ -z "$effort" ]; then
  right=$model
elif [ "$thinking" = off ]; then
  right="$model thinking off"
else
  right="$model $effort"
fi

# Time until the prompt cache TTL runs out; refreshInterval keeps it ticking while idle.
case "$cache_expires" in
  none) ;;
  cold) right="$right · cache cold" ;;
  *)
    cache_left=$(( ${cache_expires%.*} - $(date +%s) ))
    if (( cache_left <= 0 )); then
      right="$right · cache cold"
    elif (( cache_left < 60 )); then
      right="$right · cache <1m"
    else
      right="$right · cache $(( cache_left / 60 ))m"
    fi
    ;;
esac

# Claude Code sets COLUMNS for the script; keep a margin for its own padding.
width=$(( ${COLUMNS:-80} - 4 ))
two_columns() {
  local gap=$(( width - ${#1} - ${#2} ))
  (( gap < 2 )) && gap=2
  [ -n "$2" ] || gap=0
  printf '%s%s%*s%s%s\n' "$color" "$1" "$gap" "" "$2" "$reset"
}
two_columns "$left" "$right"

# Session totals are not in the statusLine JSON, so sum them from the transcript.
# One API message spans several transcript lines, hence the dedupe by message id.
# Input counts cache writes too: Anthropic reports new prompt tokens there, while
# OpenAI (and so the pi footer) reports them as plain input.
total_in=0 total_out=0
if [ -f "$transcript" ]; then
  read -r total_in total_out < <(
    jq -r 'select(.type == "assistant" and .message.usage)
      | [.message.id, (.message.usage.input_tokens // 0) + (.message.usage.cache_creation_input_tokens // 0), .message.usage.output_tokens // 0] | @tsv' "$transcript" \
      | sort -u -k1,1 | awk '{ i += $2; o += $3 } END { print i + 0, o + 0 }'
  )
fi

stats=()
(( total_in > 0 )) && stats+=("↑$(fmt_tokens "$total_in")")
(( total_out > 0 )) && stats+=("↓$(fmt_tokens "$total_out")")
prompt_tokens=$(( cur_in + cur_cr + cur_cc ))
if (( cur_cr + cur_cc > 0 )); then
  stats+=("CH$(awk -v r="$cur_cr" -v t="$prompt_tokens" 'BEGIN { printf "%.1f", r / t * 100 }')%")
fi
awk -v c="$cost" 'BEGIN { exit !(c > 0) }' && stats+=("\$$(printf '%.3f' "$cost")")
stats+=("$(fmt_tokens "$prompt_tokens")/$(fmt_tokens "$cw_size")")

two_columns "${stats[*]}" ""
