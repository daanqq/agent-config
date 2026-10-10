#!/usr/bin/env bash
# Usage: send.sh <file> [caption]    sends a document
#        send.sh --text <message>    sends a text message
set -euo pipefail

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  secrets="$HOME/.config/zsh/secrets.zsh"
  # shellcheck source=/dev/null
  [[ -r "$secrets" ]] && source "$secrets"
fi
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is not set}"
: "${TELEGRAM_CHAT_ID:?TELEGRAM_CHAT_ID is not set}"

api="https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN"

if [[ "${1:-}" == "--text" ]]; then
  response=$(curl -sS "$api/sendMessage" \
    --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" \
    --data-urlencode "text=${2:?message is required}")
else
  file="${1:?file is required}"
  [[ -f "$file" ]] || { echo "not a file: $file" >&2; exit 1; }
  # Bot API rejects uploads over 50 MB.
  if (( $(stat -c %s "$file") > 50 * 1024 * 1024 )); then
    echo "file exceeds the 50 MB Bot API limit: $file" >&2
    exit 1
  fi
  response=$(curl -sS "$api/sendDocument" \
    -F "chat_id=$TELEGRAM_CHAT_ID" \
    -F "document=@$file" \
    -F "caption=${2:-}")
fi

python3 -c '
import json, sys
d = json.loads(sys.argv[1])
if not d.get("ok"):
    sys.exit("telegram error: %s %s" % (d.get("error_code"), d.get("description")))
print("sent, message_id=%s" % d["result"]["message_id"])
' "$response"
