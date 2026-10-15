#!/usr/bin/env python3
"""Rename the calling Herdr tab after a fetched SpaceHub task."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


MAX_LABEL_CHARS = 40


def tab_label(task_id: str, title: str) -> str:
    label = " ".join(f"{task_id} {title}".split())
    if len(label) <= MAX_LABEL_CHARS:
        return label
    return label[: MAX_LABEL_CHARS - 1].rstrip() + "…"


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_json", type=Path, help="task.json from fetch-spacehub-task")
    options = parser.parse_args(argv)

    tab_id = os.environ.get("HERDR_TAB_ID")
    if os.environ.get("HERDR_ENV") != "1" or not tab_id:
        print("Not running inside a Herdr tab; skipped.")
        return 0

    try:
        issue = json.loads(options.task_json.read_text(encoding="utf-8"))["issue"]
        label = tab_label(str(issue["id"]), str(issue.get("title") or ""))
        # Untrusted task text stays in argv and never reaches a shell.
        subprocess.run(
            ["herdr", "tab", "rename", tab_id, label],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or error
        print(f"Herdr tab was not renamed: {detail}", file=sys.stderr)
        return 0

    print(f"Herdr tab {tab_id} renamed: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
