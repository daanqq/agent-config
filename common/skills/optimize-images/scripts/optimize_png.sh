#!/usr/bin/env bash

set -euo pipefail

quality="${PNG_QUALITY:-85-95}"
speed="${PNG_SPEED:-1}"
optipng_level="${OPTIPNG_LEVEL:-4}"
reoptimize="${PNG_REOPTIMIZE:-0}"

usage() {
  cat <<'EOF'
Usage: optimize_png.sh <png-or-directory> [...]

Optimizes PNG files in place and stores untouched sources in a sibling
originals/ directory.

Environment:
  PNG_QUALITY       pngquant quality range (default: 85-95)
  PNG_SPEED         pngquant speed, 1-11 (default: 1)
  OPTIPNG_LEVEL     optipng level, 0-7 (default: 4)
  PNG_REOPTIMIZE    set to 1 to requantize indexed PNGs (default: 0)
EOF
}

if [ "$#" -eq 0 ]; then
  usage >&2
  exit 2
fi

if [ "$1" = '--help' ] || [ "$1" = '-h' ]; then
  usage
  exit 0
fi

for command_name in pngquant optipng; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'error: %s is required but was not found in PATH\n' "$command_name" >&2
    exit 1
  fi
done

files=()
declare -A seen_files=()

add_file() {
  local file="$1"
  local absolute_file
  absolute_file="$(realpath "$file")"

  if [ -z "${seen_files[$absolute_file]:-}" ]; then
    files+=("$absolute_file")
    seen_files[$absolute_file]=1
  fi
}

has_alpha() {
  local file="$1"
  local color_type="$2"

  if [ "$color_type" = '4' ] || [ "$color_type" = '6' ]; then
    return 0
  fi

  [ "$color_type" = '3' ] && grep -a -q 'tRNS' "$file"
}

for input_path in "$@"; do
  if [ -d "$input_path" ]; then
    while IFS= read -r -d '' file; do
      add_file "$file"
    done < <(
      find "$input_path" \
        -type d -name originals -prune -o \
        -type f -iname '*.png' -print0
    )
  elif [ -f "$input_path" ] && [[ "${input_path,,}" == *.png ]]; then
    if [[ "/$(realpath "$input_path")/" == */originals/* ]]; then
      printf 'warning: skipping original backup: %s\n' "$input_path" >&2
      continue
    fi
    add_file "$input_path"
  else
    printf 'warning: skipping non-PNG path: %s\n' "$input_path" >&2
  fi
done

if [ "${#files[@]}" -eq 0 ]; then
  printf 'No PNG files found.\n'
  exit 0
fi

total_before=0
total_after=0
optimized_count=0
skipped_count=0
failed_count=0
temporary_file=''
original_temporary_file=''

cleanup() {
  if [ -n "$temporary_file" ]; then
    rm -f "$temporary_file"
  fi
  if [ -n "$original_temporary_file" ]; then
    rm -f "$original_temporary_file"
  fi
}

trap cleanup EXIT

for file in "${files[@]}"; do
  directory="$(dirname "$file")"
  filename="$(basename "$file")"
  originals_directory="$directory/originals"
  original_file="$originals_directory/$filename"
  before_size="$(stat -c '%s' "$file")"
  color_type="$(od -An -tu1 -j25 -N1 "$file" | tr -d ' ')"
  geometry_before="$(od -An -tx1 -j16 -N8 "$file" | tr -d ' \n')"
  source_has_alpha=0

  if has_alpha "$file" "$color_type"; then
    source_has_alpha=1
  fi

  if [ -e "$original_file" ]; then
    printf 'error: review lock exists, leaving unchanged: %s\n' "$original_file" >&2
    failed_count="$((failed_count + 1))"
    continue
  fi

  temporary_file="$(mktemp "$directory/.optimize-png.XXXXXX")"

  # Indexed inputs get a lossless pass by default, preventing repeated lossy
  # quantization after the user has removed a reviewed original.
  if [ "$color_type" = '3' ] && [ "$reoptimize" != '1' ]; then
    cp -p -- "$file" "$temporary_file"
  else
    if ! pngquant \
      --quality "$quality" \
      --speed "$speed" \
      --strip \
      --force \
      --output "$temporary_file" \
      -- "$file"; then
      printf 'warning: pngquant could not optimize: %s\n' "$file" >&2
      rm -f "$temporary_file"
      temporary_file=''
      skipped_count="$((skipped_count + 1))"
      continue
    fi
  fi

  if ! optipng -quiet -fix "-o${optipng_level}" "$temporary_file"; then
    printf 'warning: optipng could not optimize: %s\n' "$file" >&2
    rm -f "$temporary_file"
    temporary_file=''
    skipped_count="$((skipped_count + 1))"
    continue
  fi

  after_size="$(stat -c '%s' "$temporary_file")"
  output_color_type="$(od -An -tu1 -j25 -N1 "$temporary_file" | tr -d ' ')"
  geometry_after="$(od -An -tx1 -j16 -N8 "$temporary_file" | tr -d ' \n')"

  if [ "$geometry_after" != "$geometry_before" ]; then
    printf 'error: dimensions changed, leaving original: %s\n' "$file" >&2
    rm -f "$temporary_file"
    temporary_file=''
    failed_count="$((failed_count + 1))"
    continue
  fi

  if [ "$source_has_alpha" = '1' ] && ! has_alpha "$temporary_file" "$output_color_type"; then
    printf 'error: transparency changed, leaving original: %s\n' "$file" >&2
    rm -f "$temporary_file"
    temporary_file=''
    failed_count="$((failed_count + 1))"
    continue
  fi

  if [ "$after_size" -ge "$before_size" ]; then
    printf 'skipped: optimized output is not smaller: %s\n' "$file"
    rm -f "$temporary_file"
    temporary_file=''
    skipped_count="$((skipped_count + 1))"
    continue
  fi

  original_temporary_file="$(mktemp "$directory/.original-png.XXXXXX")"
  cp -p -- "$file" "$original_temporary_file"

  if [ "$(sha256sum "$file" | cut -d ' ' -f1)" != \
    "$(sha256sum "$original_temporary_file" | cut -d ' ' -f1)" ]; then
    printf 'error: original backup verification failed: %s\n' "$file" >&2
    rm -f "$original_temporary_file" "$temporary_file"
    original_temporary_file=''
    temporary_file=''
    failed_count="$((failed_count + 1))"
    continue
  fi

  mkdir -p "$originals_directory"
  mv "$original_temporary_file" "$original_file"
  original_temporary_file=''
  mv -f "$temporary_file" "$file"
  temporary_file=''
  saved_percent="$((100 - after_size * 100 / before_size))"
  total_before="$((total_before + before_size))"
  total_after="$((total_after + after_size))"
  optimized_count="$((optimized_count + 1))"

  printf 'optimized: %s\n' "$file"
  printf '  original: %s\n' "$original_file"
  printf '  size: %s -> %s bytes (-%s%%)\n' \
    "$before_size" "$after_size" "$saved_percent"
done

if [ "$optimized_count" -gt 0 ]; then
  total_saved_percent="$((100 - total_after * 100 / total_before))"
  printf 'Total optimized: %s file(s), %s -> %s bytes (-%s%%)\n' \
    "$optimized_count" "$total_before" "$total_after" "$total_saved_percent"
fi

printf 'Skipped: %s; failed: %s\n' "$skipped_count" "$failed_count"

if [ "$failed_count" -gt 0 ]; then
  exit 1
fi
