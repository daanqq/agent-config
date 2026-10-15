#!/usr/bin/env python3
"""Read-only preflight for an explicit repository migration plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

class PlanError(Exception):
    pass


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-optional-locks", "--literal-pathspecs", "-C", str(repo), *args],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise PlanError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def path_in_repo(repo: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PlanError("Paths must be nonempty strings")
    path = Path(value)
    if (path.is_absolute() or value != path.as_posix()
            or any(part in {"..", ".git"} for part in path.parts) or path == Path(".")):
        raise PlanError(f"Unsafe repository path: {value!r}")
    current = repo
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise PlanError(f"Symlinks are not supported: {value}")
        if current != repo / path and current.exists() and not current.is_dir():
            raise PlanError(f"Non-directory ancestor: {value}")
    if not (repo / path).resolve().is_relative_to(repo):
        raise PlanError(f"Path escapes repository: {value}")
    return repo / path


def inventory(repo: Path, value: object) -> dict:
    root = path_in_repo(repo, value)
    entries = {}

    def visit(path: Path, name: str) -> None:
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            entries[name] = {"kind": "directory"}
            for child in sorted(path.iterdir()):
                if child.name == ".git":
                    raise PlanError(f"Nested Git metadata is unsupported: {child}")
                visit(child, child.name if name == "." else f"{name}/{child.name}")
        elif stat.S_ISREG(mode):
            entries[name] = {"kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "executable": bool(mode & 0o111)}
        else:
            raise PlanError(f"Only regular files/directories are supported: {path}")

    visit(root, ".")
    return entries


def overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def checked_inventory(repo: Path, op: dict) -> dict:
    actual = inventory(repo, op["source"])
    expected = op.get("expected")
    # Exact equality also rejects missing hashes, extra files, and changed types.
    if not isinstance(expected, dict) or actual != expected:
        raise PlanError(f"Inventory/fingerprint mismatch: {op['source']}")
    return actual


def preflight(repo: Path, plan: object) -> list[dict]:
    if (not isinstance(plan, dict) or set(plan) != {"version", "operations"}
            or type(plan["version"]) is not int or plan["version"] != 1
            or not isinstance(plan["operations"], list) or not plan["operations"]):
        raise PlanError("Expected {version: 1, operations: [nonempty operations]}")
    operations = plan["operations"]
    sources, destinations, inventories = {}, {}, {}
    for op in operations:
        if not isinstance(op, dict) or op.get("op") not in ("move", "remove"):
            raise PlanError("Each operation must be move or remove")
        keys = {"op", "source", "expected", "destination" if op["op"] == "move" else "preserve"}
        if set(op) != keys:
            raise PlanError(f"Operation requires exactly {sorted(keys)}")
        source = path_in_repo(repo, op["source"])
        if any(overlap(source, previous) for previous in sources):
            raise PlanError(f"Duplicate/overlapping sources: {op['source']}")
        sources[source] = op
        inventories[source] = checked_inventory(repo, op)
        if op["op"] == "move":
            destination = path_in_repo(repo, op["destination"])
            if any(overlap(destination, previous) for previous in destinations):
                raise PlanError(f"Duplicate/overlapping destinations: {op['destination']}")
            destinations[destination] = op

    for destination in destinations:
        for source, op in sources.items():
            # A replacement is an explicit remove plus move to precisely that path.
            if overlap(destination, source) and not (destination == source and op["op"] == "remove"):
                raise PlanError(f"Source/destination overlap: {destination.relative_to(repo)}")
        if destination.exists() and destination not in sources:
            raise PlanError(f"Occupied destination: {destination.relative_to(repo)}")
        if destination not in sources and git(repo, "ls-files", "-z", "--", destination.relative_to(repo).as_posix()):
            raise PlanError(f"Destination has tracked data: {destination.relative_to(repo)}")
        parent = destination.parent
        while parent != repo and not parent.exists():
            relative = parent.relative_to(repo).as_posix()
            if os.fsencode(relative) in git(repo, "ls-files", "-z", "--", relative).split(b"\0"):
                raise PlanError(f"Destination ancestor has tracked data: {relative}")
            parent = parent.parent

    report = []
    for source, op in sources.items():
        entries = inventories[source]
        tracked = git(repo, "ls-files", "--stage", "-z", "--", op["source"])
        staged_names = set(git(repo, "diff", "--cached", "--name-only", "-z", "--no-renames",
                               "--", op["source"]).split(b"\0"))
        tracked_names = set()
        for record in tracked.split(b"\0"):
            if not record:
                continue
            metadata, raw_name = record.split(b"\t", 1)
            mode, blob, stage = metadata.split()
            name = os.fsdecode(raw_name)
            if stage != b"0" or mode not in {b"100644", b"100755"}:
                raise PlanError(f"Unsupported/conflicted index entry: {name}")
            path = repo / name
            relative = "." if path == source else path.relative_to(source).as_posix()
            if relative not in entries or entries[relative]["kind"] != "file":
                raise PlanError(f"Tracked source is missing or changed type: {name}")
            if raw_name in staged_names:
                indexed = {"kind": "file", "sha256": hashlib.sha256(
                    git(repo, "cat-file", "blob", blob.decode("ascii"))).hexdigest(),
                    "executable": mode == b"100755"}
                if indexed != entries[relative]:
                    raise PlanError(f"Distinct staged content would be lost: {name}")
            tracked_names.add(relative)
        if op["op"] == "remove":
            files = {name: entry for name, entry in entries.items() if entry["kind"] == "file"}
            preserved = op["preserve"]
            if not isinstance(preserved, dict) or set(preserved) != set(files):
                raise PlanError(f"Every removed file needs an explicit retained copy: {op['source']}")
            for name, copy in preserved.items():
                retained = path_in_repo(repo, copy)
                if any(overlap(retained, root) for root in (*sources, *destinations)):
                    raise PlanError(f"Preserved copy is affected by plan: {copy}")
                if inventory(repo, copy) != {".": files[name]}:
                    raise PlanError(f"Preserved copy differs: {copy}")
        status = git(repo, "status", "--porcelain=v1", "-z", "--no-renames",
                     "--untracked-files=all", "--ignored=matching", "--", op["source"])
        report.append({"source": op["source"], "tracked_files": len(tracked_names),
                       "untracked_files": sum(entry["kind"] == "file" and name not in tracked_names
                                              for name, entry in entries.items()),
                       "git_status": [os.fsdecode(item) for item in status.split(b"\0") if item]})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", type=Path, help="Validate JSON plan; never execute it")
    mode.add_argument("--inventory", metavar="PATH", help="Print expected snapshot for one repository path")
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve(strict=True)
        top = Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel")).strip()).resolve()
        if repo != top:
            raise PlanError("--repo must be the repository root")
        if args.inventory is not None:
            output = inventory(repo, args.inventory)
        else:
            plan = json.loads(args.plan.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
            output = {"result": "passed", "sources": preflight(repo, plan)}
        print(json.dumps(output, indent=2, ensure_ascii=True))
        return 0
    except (PlanError, OSError, ValueError, RuntimeError) as error:
        print(f"Migration preflight failed: {error}", file=sys.stderr)
        return 1


def unique_keys(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


if __name__ == "__main__":
    raise SystemExit(main())
