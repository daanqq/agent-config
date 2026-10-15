#!/usr/bin/env zsh
set -eu

exec python3 "${0:A:h}/mr_context.py" "$@"
