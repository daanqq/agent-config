#!/usr/bin/env python3
"""Print GitLab diff line anchors for every changed line of a commit.

Usage:
    git -C <repo> show <sha> -U3 --format= | python3 diff_line_anchors.py

Each output line is: <line_code> <TAB> <path> <TAB> <+new|-old> <TAB> <text>.
Link a line as https://<host>/<project>/-/merge_requests/<iid>/diffs?commit_id=<full-sha>#<line_code>.
"""

import hashlib
import re
import sys

HUNK = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def main() -> None:
    path_hash = path = None
    old_path = None
    old = new = 0

    for raw in sys.stdin.read().splitlines():
        if raw.startswith("diff --git "):
            path_hash = path = old_path = None
            continue
        if raw.startswith("--- "):
            old_path = raw[6:] if raw.startswith("--- a/") else None
            continue
        if raw.startswith("+++ "):
            # GitLab hashes the new path; deleted files keep the old one
            path = raw[6:] if raw.startswith("+++ b/") else old_path
            path_hash = hashlib.sha1(path.encode()).hexdigest() if path else None
            continue

        match = HUNK.match(raw)
        if match:
            old, new = int(match.group(1)), int(match.group(2))
            continue

        if not path_hash or not raw or raw.startswith("\\"):
            continue

        # Added lines keep the next old line number, removed lines the next new one
        kind, text = raw[0], raw[1:].strip()
        if kind == "+":
            print(f"{path_hash}_{old}_{new}\t{path}\t+{new}\t{text}")
            new += 1
        elif kind == "-":
            print(f"{path_hash}_{old}_{new}\t{path}\t-{old}\t{text}")
            old += 1
        elif kind == " ":
            old += 1
            new += 1


if __name__ == "__main__":
    main()
