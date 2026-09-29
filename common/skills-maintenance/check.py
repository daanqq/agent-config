#!/usr/bin/env python3
"""Check the shared skill inventory without contacting the network."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE = Path(__file__).resolve().parent
MANIFEST = MAINTENANCE / "manifest.json"
SCOPES = ("common", "pi", "claude")
SKILL_ROOTS = {
    "common": ROOT / "common" / "skills",
    "pi": ROOT / "pi" / "agent" / "skills",
    "claude": ROOT / "claude" / "skills",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
TRACKING = {"local", "exact", "overlay"}


def entries_hash(entries: list[tuple[str, str, int, bytes]]) -> str:
    digest = hashlib.sha256()
    for path, kind, mode, payload in sorted(entries):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(kind.encode())
        digest.update(b"\0")
        git_mode = 0o777 if kind == "link" else 0o755 if mode & 0o111 else 0o644
        digest.update(f"{git_mode:o}".encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def directory_hash(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.is_dir():
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            entries.append((path.relative_to(root).as_posix(), "link", mode, os.readlink(path).encode()))
        else:
            entries.append((path.relative_to(root).as_posix(), "file", mode, path.read_bytes()))
    return entries_hash(entries)


def archive_hash(repo: Path, revision: str, source_path: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", revision, source_path],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    prefix = source_path.rstrip("/") + "/"
    entries = []
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isdir() or not member.name.startswith(prefix):
                continue
            relative = member.name[len(prefix):]
            if not relative:
                continue
            if member.issym():
                entries.append((relative, "link", member.mode, member.linkname.encode()))
            elif member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                entries.append((relative, "file", member.mode, stream.read()))
    return entries_hash(entries)


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^([a-z][a-z0-9-]*):\s*(.*?)\s*$", line)
        if match:
            value = match.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[match.group(1)] = value
    return result


def _safe_relative(path: str) -> bool:
    return not Path(path).is_absolute()


def _safe_manifest_relative(path: str) -> bool:
    return _safe_relative(path) and ".." not in Path(path).parts


def _skill_dirs(scope: str) -> tuple[dict[str, Path], list[str]]:
    root = SKILL_ROOTS[scope]
    physical, errors = {}, []
    if not root.is_dir():
        return physical, [f"{scope}: missing skill directory {root}"]
    for entry in root.iterdir():
        if entry.name == "__pycache__":
            continue
        if entry.is_symlink():
            target = entry.resolve(strict=False)
            expected = SKILL_ROOTS["common"] / entry.name
            if (
                scope != "common"
                and not Path(os.readlink(entry)).is_absolute()
                and entry.is_dir()
                and target == expected.resolve()
                and expected.is_dir()
            ):
                continue
            errors.append(f"{scope}: forbidden skill-directory symlink {entry}")
            continue
        if not entry.is_dir():
            errors.append(f"{scope}: unexpected entry {entry.name}")
            continue
        # A client tree also contains non-skill directories (for example a
        # plugin). Inventory is the set of physical Agent Skill directories.
        if (entry / "SKILL.md").is_file():
            physical[entry.name] = entry
    return physical, errors


def _check_links(scope: str, name: str, skill_dir: Path, errors: list[str]) -> None:
    for markdown in skill_dir.rglob("*.md"):
        if any("__pycache__" == part for part in markdown.parts):
            continue
        try:
            text = markdown.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{scope}/{name}: cannot read {markdown}: {exc}")
            continue
        for raw in LINK_RE.findall(text):
            target = raw.split("#", 1)[0].strip().replace("%20", " ")
            if not target or "://" in target or target.startswith(("mailto:", "<")) or any(c in target for c in "{}*"):
                continue
            if not _safe_relative(target):
                errors.append(f"{scope}/{name}: unsafe relative link {target!r} in {markdown}")
                continue
            resolved = (markdown.parent / target).resolve(strict=False)
            allowed = [SKILL_ROOTS["common"].resolve(), SKILL_ROOTS[scope].resolve()]
            if scope == "common":
                allowed.append((ROOT / "common").resolve())
            if not resolved.exists() or not any(resolved == base or base in resolved.parents for base in allowed):
                errors.append(f"{scope}/{name}: broken link {target!r} in {markdown.relative_to(ROOT)}")


def _repository_errors(repositories: object) -> list[str]:
    if not isinstance(repositories, dict) or not repositories:
        return ["repositories must be a non-empty object"]
    errors = []
    for name, record in repositories.items():
        if not isinstance(name, str) or not isinstance(record, dict):
            errors.append(f"invalid repository record {name!r}")
            continue
        if not all(isinstance(record.get(key), str) and record[key] for key in ("cache", "revision")):
            errors.append(f"{name}: repository requires cache and revision")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=SCOPES, default=None)
    parser.add_argument("--check-sources", action="store_true")
    parser.add_argument("--refresh-installed-hashes", action="store_true")
    args = parser.parse_args(argv)
    if not MANIFEST.is_file():
        print(f"Skill maintenance check failed: missing manifest {MANIFEST}", file=sys.stderr)
        return 1
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Skill maintenance check failed: invalid manifest: {exc}", file=sys.stderr)
        return 1
    errors = []
    if data.get("schema_version") != 2:
        errors.append("manifest schema_version must be 2")
    errors += _repository_errors(data.get("repositories"))
    declared = data.get("skills")
    if not isinstance(declared, dict) or set(declared) != set(SCOPES):
        errors.append("skills must contain exactly common, pi, and claude")
        declared = {scope: {} for scope in SCOPES}
    physical = {}
    for scope in SCOPES:
        physical[scope], scope_errors = _skill_dirs(scope)
        errors += scope_errors
    common_names = set(physical["common"])
    for scope in ("pi", "claude"):
        own = set(physical[scope])
        overlap = common_names & own
        if overlap:
            errors.append(f"{scope}: own skills collide with common: {', '.join(sorted(overlap))}")
        for alias in SKILL_ROOTS[scope].iterdir() if SKILL_ROOTS[scope].is_dir() else ():
            if alias.is_symlink() and alias.name in common_names:
                expected = SKILL_ROOTS["common"] / alias.name
                if alias.resolve(strict=False) != expected.resolve():
                    errors.append(f"{scope}: alias {alias.name} does not point to common/{alias.name}")
    selected = (args.scope,) if args.scope else SCOPES
    for scope in SCOPES:
        records = declared.get(scope, {})
        if not isinstance(records, dict):
            errors.append(f"{scope}: skill records must be an object")
            continue
        actual = set(physical[scope])
        if set(records) != actual:
            errors.append(f"{scope}: manifest inventory differs (missing {sorted(actual-set(records))}, stale {sorted(set(records)-actual)})")
        for name, skill in records.items():
            if not isinstance(skill, dict):
                errors.append(f"{scope}/{name}: record must be an object")
                continue
            skill_dir = physical[scope].get(name)
            if skill_dir is None or scope not in selected:
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                errors.append(f"{scope}/{name}: missing SKILL.md")
                continue
            fields = frontmatter(skill_file)
            if fields.get("name") != name:
                errors.append(f"{scope}/{name}: frontmatter name is {fields.get('name')!r}")
            if not NAME_RE.fullmatch(name) or len(name) > 64:
                errors.append(f"{scope}/{name}: invalid Agent Skills name")
            if not fields.get("description"):
                errors.append(f"{scope}/{name}: missing frontmatter description")
            elif len(fields["description"]) > 1024:
                errors.append(f"{scope}/{name}: description exceeds 1024 characters")
            if fields.get("compatibility") and len(fields["compatibility"]) > 500:
                errors.append(f"{scope}/{name}: compatibility exceeds 500 characters")
            _check_links(scope, name, skill_dir, errors)
            tracking = skill.get("tracking")
            if tracking not in TRACKING:
                errors.append(f"{scope}/{name}: invalid tracking mode {tracking!r}")
            elif tracking == "local":
                if any(key in skill for key in ("repository", "path", "overlay")):
                    errors.append(f"{scope}/{name}: local skill has upstream fields")
            else:
                repo_name, source_path = skill.get("repository"), skill.get("path")
                if repo_name not in data.get("repositories", {}) or not isinstance(source_path, str) or not source_path or not _safe_manifest_relative(source_path):
                    errors.append(f"{scope}/{name}: incomplete or unsafe upstream declaration")
                if tracking == "overlay":
                    overlay = skill.get("overlay")
                    if not isinstance(overlay, str) or not _safe_manifest_relative(overlay) or not (MAINTENANCE / overlay).is_file():
                        errors.append(f"{scope}/{name}: missing or unsafe semantic overlay")
                elif "overlay" in skill:
                    errors.append(f"{scope}/{name}: exact skill must not declare an overlay")
            installed = directory_hash(skill_dir)
            recorded = skill.get("installed_hash")
            drift = recorded != installed
            if drift and not (args.refresh_installed_hashes and scope in selected):
                errors.append(f"{scope}/{name}: installed hash drift ({installed})")
            elif args.refresh_installed_hashes and scope in selected:
                skill["installed_hash"] = installed
            if args.check_sources and scope in selected and tracking in {"exact", "overlay"} and skill.get("repository") in data.get("repositories", {}):
                repo_record = data["repositories"][skill["repository"]]
                repo = Path.home() / ".cache" / "checkouts" / repo_record["cache"]
                if not (repo / ".git").exists():
                    errors.append(f"{scope}/{name}: missing cached repository {repo}")
                else:
                    try:
                        source = archive_hash(repo, repo_record["revision"], skill["path"])
                        if tracking == "exact" and source != installed:
                            errors.append(f"{scope}/{name}: exact copy differs from locked upstream")
                    except (subprocess.CalledProcessError, OSError, tarfile.TarError) as exc:
                        errors.append(f"{scope}/{name}: cannot read locked source: {exc}")
    if args.refresh_installed_hashes and not errors:
        MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = ", ".join(f"{scope}={len(physical[scope])}" for scope in SCOPES)
    if errors:
        print("Skill maintenance check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(f"Inventory: {counts}", file=sys.stderr)
        return 1
    print(f"Skill maintenance check passed ({counts}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
