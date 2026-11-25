#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: checkout.sh <repo> [options]

Ensure a cached checkout exists at:
  ~/.cache/checkouts/<host>/<org>/<repo>

Examples:
  checkout.sh mitsuhiko/minijinja
  checkout.sh github.com/mitsuhiko/minijinja
  checkout.sh https://github.com/mitsuhiko/minijinja
  checkout.sh git@github.com:mitsuhiko/minijinja.git

Options:
  --path-only                 Print only the checkout path.
  --force-update              Always fetch from origin and attempt fast-forward.
  --update-interval <secs>    Minimum seconds between updates (default: 300).
  --shallow                   Use --depth=1 on initial clone (partial blobless clone).
  --ttl-days <days>           Remove clean checkouts unused for more than N days (default: 30, 0 disables).

Environment:
  LIBRARIAN_CACHE_ROOT        Override cache root (default: ~/.cache/checkouts)
  LIBRARIAN_DEFAULT_HOST      Host for owner/repo shorthand (default: github.com)
  LIBRARIAN_UPDATE_INTERVAL   Default update interval in seconds
  LIBRARIAN_TTL_DAYS          Default TTL in days for automatic cache pruning (default: 30)
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

repo_input=""
path_only=0
force_update=0
shallow=0
update_interval="${LIBRARIAN_UPDATE_INTERVAL:-300}"
ttl_days="${LIBRARIAN_TTL_DAYS:-30}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path-only)
      path_only=1
      shift
      ;;
    --force-update)
      force_update=1
      shift
      ;;
    --shallow)
      shallow=1
      shift
      ;;
    --update-interval)
      if [[ $# -lt 2 ]]; then
        echo "error: --update-interval expects a value" >&2
        exit 2
      fi
      update_interval="$2"
      shift 2
      ;;
    --ttl-days)
      if [[ $# -lt 2 ]]; then
        echo "error: --ttl-days expects a value" >&2
        exit 2
      fi
      ttl_days="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$repo_input" ]]; then
        repo_input="$1"
      else
        echo "error: unexpected argument: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$repo_input" ]]; then
  echo "error: repository is required" >&2
  exit 2
fi

if ! [[ "$update_interval" =~ ^[0-9]+$ ]]; then
  echo "error: update interval must be a non-negative integer" >&2
  exit 2
fi

if ! [[ "$ttl_days" =~ ^[0-9]+$ ]]; then
  echo "error: ttl-days must be a non-negative integer" >&2
  exit 2
fi

trim_repo_input() {
  local s="$1"
  # Trim leading/trailing whitespace.
  s="${s#${s%%[![:space:]]*}}"
  s="${s%${s##*[![:space:]]}}"
  printf '%s' "$s"
}

parse_repo() {
  local input host path first rest
  input="$(trim_repo_input "$1")"

  # Strip query/fragment for URL-like inputs.
  input="${input%%\?*}"
  input="${input%%#*}"

  case "$input" in
    git@*:* )
      host="${input#git@}"
      host="${host%%:*}"
      path="${input#*:}"
      ;;
    ssh://* )
      rest="${input#ssh://}"
      host="${rest%%/*}"
      host="${host#*@}"
      path="${rest#*/}"
      ;;
    http://*|https://* )
      rest="${input#*://}"
      host="${rest%%/*}"
      path="${rest#*/}"
      ;;
    */* )
      first="${input%%/*}"
      if [[ "$first" == *.* || "$first" == localhost ]]; then
        host="$first"
        path="${input#*/}"
      else
        host="${LIBRARIAN_DEFAULT_HOST:-github.com}"
        path="$input"
      fi
      ;;
    * )
      echo "error: unsupported repository format: $input" >&2
      return 1
      ;;
  esac

  host="${host#*@}"
  path="${path#/}"
  path="${path%/}"

  # Strip GitLab /-/ deep-link suffixes before splitting path segments.
  path="${path%%/-/*}"

  # For GitHub-like deep links, use owner/repo only.
  IFS='/' read -r -a parts <<< "$path"
  if [[ ${#parts[@]} -ge 3 ]]; then
    case "${parts[2]}" in
      tree|blob|pull|issues|commit|actions|releases|compare|wiki)
        path="${parts[0]}/${parts[1]}"
        ;;
    esac
  fi

  # Strip optional .git suffix.
  path="${path%.git}"

  IFS='/' read -r -a parts <<< "$path"
  if [[ ${#parts[@]} -lt 2 ]]; then
    echo "error: repository path must contain at least org/repo: $path" >&2
    return 1
  fi

  local last_index=$(( ${#parts[@]} - 1 ))
  local repo="${parts[$last_index]}"
  local org_parts=("${parts[@]:0:$last_index}")
  local org
  org="$(IFS='/'; echo "${org_parts[*]}")"

  if [[ -z "$host" || -z "$org" || -z "$repo" ]]; then
    echo "error: failed to parse repository: $input" >&2
    return 1
  fi

  printf '%s\n%s\n%s\n' "$host" "$org" "$repo"
}

parsed_host=""
parsed_org=""
parsed_repo=""
parsed_index=0
while IFS= read -r line; do
  case "$parsed_index" in
    0) parsed_host="$line" ;;
    1) parsed_org="$line" ;;
    2) parsed_repo="$line" ;;
  esac
  parsed_index=$((parsed_index + 1))
done < <(parse_repo "$repo_input")

host="$parsed_host"
org="$parsed_org"
repo="$parsed_repo"

cache_root="${LIBRARIAN_CACHE_ROOT:-$HOME/.cache/checkouts}"
checkout_path="$cache_root/$host/$org/$repo"
origin_url="https://$host/$org/$repo.git"

mkdir -p "$(dirname "$checkout_path")"

if [[ ! -d "$checkout_path/.git" ]]; then
  clone_args=(--filter=blob:none)
  if (( shallow == 1 )); then
    clone_args+=(--depth=1)
  fi
  git clone "${clone_args[@]}" "$origin_url" "$checkout_path" >/dev/null
  clone_state="cloned"
else
  clone_state="existing"
fi

if [[ ! -d "$checkout_path/.git" ]]; then
  echo "error: checkout path is not a git repository: $checkout_path" >&2
  exit 3
fi

if ! git -C "$checkout_path" remote get-url origin >/dev/null 2>&1; then
  git -C "$checkout_path" remote add origin "$origin_url"
fi

# If remote URL changed (e.g. host shorthand), normalize to canonical HTTPS URL.
current_origin="$(git -C "$checkout_path" remote get-url origin 2>/dev/null || true)"
if [[ "$current_origin" != "$origin_url" ]]; then
  git -C "$checkout_path" remote set-url origin "$origin_url"
fi

last_fetch_file="$checkout_path/.git/librarian-last-fetch"
last_used_file="$checkout_path/.git/librarian-last-used"
now_epoch="$(date +%s)"
echo "$now_epoch" > "$last_used_file"
needs_update=1

if [[ -f "$last_fetch_file" && "$force_update" -eq 0 ]]; then
  last_epoch="$(cat "$last_fetch_file" 2>/dev/null || echo 0)"
  if [[ "$last_epoch" =~ ^[0-9]+$ ]]; then
    age=$(( now_epoch - last_epoch ))
    if (( age < update_interval )); then
      needs_update=0
    fi
  fi
fi

update_state="skipped"
ff_state="not-attempted"

if (( needs_update == 1 )); then
  git -C "$checkout_path" fetch --prune --tags origin >/dev/null
  echo "$now_epoch" > "$last_fetch_file"
  update_state="fetched"

  branch="$(git -C "$checkout_path" symbolic-ref --short -q HEAD 2>/dev/null || true)"
  upstream="$(git -C "$checkout_path" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  dirty="$(git -C "$checkout_path" status --porcelain --untracked-files=no)"

  if [[ -n "$branch" && -n "$upstream" && -z "$dirty" ]]; then
    if git -C "$checkout_path" merge --ff-only "$upstream" >/dev/null 2>&1; then
      ff_state="fast-forwarded"
    else
      ff_state="skipped-non-ff"
    fi
  elif [[ -n "$dirty" ]]; then
    ff_state="skipped-dirty"
  else
    ff_state="skipped-no-upstream"
  fi
fi

file_mtime_epoch() {
  local target="$1"
  if stat -c %Y "$target" >/dev/null 2>&1; then
    stat -c %Y "$target"
  elif stat -f %m "$target" >/dev/null 2>&1; then
    stat -f %m "$target"
  else
    echo 0
  fi
}

prune_stale_checkouts() {
  (( ttl_days > 0 )) || return 0
  [[ -d "$cache_root" ]] || return 0
  local cutoff=$(( now_epoch - ttl_days * 86400 ))
  local git_dir repo_dir last_used raw_val parent
  while IFS= read -r -d '' git_dir; do
    repo_dir="$(dirname "$git_dir")"
    [[ "$repo_dir" == "$checkout_path" ]] && continue
    last_used=""
    for marker in "$git_dir/librarian-last-used" "$git_dir/librarian-last-fetch"; do
      if [[ -f "$marker" ]]; then
        raw_val="$(cat "$marker" 2>/dev/null || true)"
        if [[ "$raw_val" =~ ^[0-9]+$ ]]; then
          last_used="$raw_val"
          break
        fi
      fi
    done
    if [[ -z "$last_used" ]]; then
      last_used="$(file_mtime_epoch "$git_dir")"
    fi
    [[ "$last_used" =~ ^[0-9]+$ ]] || continue
    (( last_used < cutoff )) || continue
    # Never delete a checkout with local edits or untracked files.
    if [[ -n "$(git -C "$repo_dir" status --porcelain 2>/dev/null || echo dirty)" ]]; then
      continue
    fi
    rm -rf "$repo_dir"
    parent="$(dirname "$repo_dir")"
    while [[ "$parent" != "$cache_root" && "$parent" == "$cache_root/"* ]]; do
      rmdir "$parent" 2>/dev/null || break
      parent="$(dirname "$parent")"
    done
  done < <(find "$cache_root" -mindepth 2 -maxdepth 6 -type d -name .git -print0 2>/dev/null)
}

prune_stale_checkouts || true

if (( path_only == 1 )); then
  printf '%s\n' "$checkout_path"
  exit 0
fi

cat <<EOF
repo: $host/$org/$repo
path: $checkout_path
state: $clone_state
update: $update_state
fast_forward: $ff_state
EOF
