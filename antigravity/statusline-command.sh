#!/bin/bash
# Mirrors claude/statusline-command.sh and the pi footer:
# line 1 is project (branch) on the left and model/mode on the right,
# line 2 is session token/cache/cost/context stats.

input=$(cat)
export LC_NUMERIC=C

# Unit separator instead of tab: read collapses adjacent tabs, shifting empty fields.
IFS=$'\x1f' read -r dir model effort cycle_mode sandbox_on term_width \
  total_in total_out cw_size used_pct cur_in cur_cr cur_cc cost_usd task_count running_subagents < <(
  jq -r '[
    (.workspace.current_dir // .cwd // ""),
    (.model.display_name // .model.id // "no-model"),
    (.model.effort // ""),
    (.cycle_mode // ""),
    (if .sandbox.enabled == true then "1" else "0" end),
    (.terminal_width // 0),
    (.context_window.total_input_tokens // 0),
    (.context_window.total_output_tokens // 0),
    (.context_window.context_window_size // 0),
    (.context_window.used_percentage // ""),
    (.context_window.current_usage.input_tokens // 0),
    (.context_window.current_usage.cache_read_input_tokens // 0),
    (.context_window.current_usage.cache_creation_input_tokens // 0),
    (.cost.total_usd // 0),
    (.task_count // 0),
    ([(.subagents // [])[] | select(.status == "running")] | length)
  ] | map(tostring) | join("\u001f")' <<<"$input"
)
[ -n "$dir" ] || dir=$(pwd)

case "$effort" in
  low) token=warning ;;
  medium) token=success ;;
  high) token=permission ;;
  xhigh) token=autoAccept ;;
  max) token=effortUltra ;;
  *) token=claude ;;
esac
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

right=$model
if [ -n "$effort" ]; then
  # Antigravity display_name often already embeds "(High)" / "(Medium)".
  case "${model,,}" in
    *"(${effort,,})"*) ;;
    *) right="$right $effort" ;;
  esac
fi
[ -n "$cycle_mode" ] && right="$right · $cycle_mode"
[ "$sandbox_on" = "1" ] && right="$right · sandbox"

if (( term_width > 4 )); then
  width=$(( term_width - 4 ))
else
  width=$(( ${COLUMNS:-80} - 4 ))
fi

two_columns() {
  local gap=$(( width - ${#1} - ${#2} ))
  (( gap < 2 )) && gap=2
  [ -n "$2" ] || gap=0
  printf '%s%s%*s%s%s\n' "$color" "$1" "$gap" "" "$2" "$reset"
}
two_columns "$left" "$right"

stats=()
(( total_in > 0 )) && stats+=("↑$(fmt_tokens "$total_in")")
(( total_out > 0 )) && stats+=("↓$(fmt_tokens "$total_out")")
prompt_tokens=$(( cur_in + cur_cr + cur_cc ))
if (( cur_cr + cur_cc > 0 && prompt_tokens > 0 )); then
  stats+=("CH$(awk -v r="$cur_cr" -v t="$prompt_tokens" 'BEGIN { printf "%.1f", r / t * 100 }')%")
fi
awk -v c="$cost_usd" 'BEGIN { exit !(c > 0) }' && stats+=("\$$(printf '%.3f' "$cost_usd")")
if (( cw_size > 0 )); then
  if (( prompt_tokens > 0 )); then
    stats+=("$(fmt_tokens "$prompt_tokens")/$(fmt_tokens "$cw_size")")
  elif [ -n "$used_pct" ]; then
    stats+=("$(awk -v p="$used_pct" 'BEGIN { printf "%.0f%%", p }')/$(fmt_tokens "$cw_size")")
  fi
fi
(( running_subagents > 0 )) && stats+=("agents:$running_subagents")
(( task_count > 0 )) && stats+=("tasks:$task_count")

if (( ${#stats[@]} > 0 )); then
  two_columns "${stats[*]}" ""
fi
