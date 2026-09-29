#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 6 ]; then
	printf 'usage: log.sh <logfile> <phase> <decision> <why> <evidence> <result>\n' >&2
	exit 1
fi

logfile="$1"
shift

logdir="$(dirname "$logfile")"
if [ "$logdir" != "." ]; then
	mkdir -p "$logdir"
fi

# Append even when a network mount reports a stale existence check. A duplicate
# header is safer than truncating an existing trail.
if [ ! -s "$logfile" ]; then
	printf 'ts\tphase\tdecision\twhy\tevidence\tresult\n' >> "$logfile"
fi

clean_cell() {
	local value
	value=$(printf '%s' "$1" | tr '\t\n\r' '   ')
	# Logs are commonly opened in spreadsheets, so neutralize leading formula bytes.
	case "$value" in
		=*|+*|-*|@*) printf "'%s" "$value" ;;
		*) printf '%s' "$value" ;;
	esac
}

printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
	"$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	"$(clean_cell "$1")" \
	"$(clean_cell "$2")" \
	"$(clean_cell "$3")" \
	"$(clean_cell "$4")" \
	"$(clean_cell "$5")" \
	>> "$logfile"
