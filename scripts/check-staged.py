"""Run make check against the Git index without stashing or changing the worktree."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check_staged():
    root = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True,
    ).strip())
    result = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--check"])
    if result.returncode:
        return result.returncode

    local_variables = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--local-env-vars"], text=True,
    ).splitlines()
    clean_environment = os.environ.copy()
    for name in local_variables:
        clean_environment.pop(name, None)
    clean_environment["PYTHONDONTWRITEBYTECODE"] = "1"

    with tempfile.TemporaryDirectory(prefix="agent-config-pre-commit-") as temporary:
        snapshot = Path(temporary) / "repo"
        snapshot.mkdir()
        result = subprocess.run([
            "git", "-C", str(root), "checkout-index", "--all",
            "--ignore-skip-worktree-bits", f"--prefix={snapshot}/",
        ])
        if result.returncode:
            return result.returncode
        # Tests create their own Git fixtures: never leak the hook's GIT_INDEX_FILE
        # or GIT_DIR into those repositories or the snapshot's private index.
        for command in (["git", "init", "--quiet"], ["git", "add", "--force", "--all"]):
            result = subprocess.run(command, cwd=snapshot, env=clean_environment)
            if result.returncode:
                return result.returncode
        print("Checking staged snapshot with make check (working files are untouched).", flush=True)
        result = subprocess.run(["make", "check"], cwd=snapshot, env=clean_environment)
        return result.returncode


def main():
    try:
        code = check_staged()
        return code if code >= 0 else 128 - code
    except KeyboardInterrupt:
        return 130
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Staged check failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
