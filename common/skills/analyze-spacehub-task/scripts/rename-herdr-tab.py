#!/usr/bin/env python3
"""Rename the calling Herdr tab after a fetched SpaceHub task.

Under Claude Code, also print the /rename command for the session: only the
user can run slash commands.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


MAX_LABEL_CHARS = 40


def task_title(task_id: str, title: str) -> str:
    return " ".join(f"{task_id} {title}".split())


def tab_label(title: str) -> str:
    if len(title) <= MAX_LABEL_CHARS:
        return title
    return title[: MAX_LABEL_CHARS - 1].rstrip() + "…"


def rename_herdr_tab(label: str) -> None:
    tab_id = os.environ.get("HERDR_TAB_ID")
    if os.environ.get("HERDR_ENV") != "1" or not tab_id:
        print("Not running inside a Herdr tab; skipped.")
        return

    try:
        # Untrusted task text stays in argv and never reaches a shell.
        subprocess.run(
            ["herdr", "tab", "rename", tab_id, label],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or error
        print(f"Herdr tab was not renamed: {detail}", file=sys.stderr)
        return

    print(f"Herdr tab {tab_id} renamed: {label}")


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_json", type=Path, help="task.json from fetch-spacehub-task")
    options = parser.parse_args(argv)

    try:
        issue = json.loads(options.task_json.read_text(encoding="utf-8"))["issue"]
        title = task_title(str(issue["id"]), str(issue.get("title") or ""))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Task title was not read: {error}", file=sys.stderr)
        return 0

    rename_herdr_tab(tab_label(title))
    if os.environ.get("CLAUDECODE") == "1":
        print(f"Claude Code session rename command: /rename {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
