"""Selective HOME links with preflight, private backups, and conservative restore."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile


STATE = Path(".local/state/agent-config/backups")
FORBIDDEN = {
    "credentials", "credentials.json", "auth.json", "secrets", "secrets.json",
    "sessions", "session", "history", "history.jsonl", "cache", "caches",
    ".cache", "logs", "debug", "projects", "todos", "shell-snapshots",
    "runtime", "node_modules", ".git", ".ssh", ".aws", ".gnupg",
    ".claude.json", "telemetry", "statsig", "backups",
    "token", "tokens", "token.json", "token.txt", "api-key", "api-key.txt",
}


class InstallError(Exception):
    pass


def exists(path):
    return os.path.lexists(path)


def within(path, root):
    return path == root or root in path.parents


def relative_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InstallError("Paths must be nonempty strings")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise InstallError(f"Unsafe relative path: {value!r}")
    return path


def safe_source(path, repo):
    # Inspect names and metadata only, never credential contents.
    pending = [path]
    seen = set()
    while pending:
        item = pending.pop()
        resolved = item.resolve()
        if not within(resolved, repo) or not item.exists():
            raise InstallError(f"Missing or escaping source: {item}")
        for part in (*item.relative_to(repo).parts, *resolved.relative_to(repo).parts):
            name = part.lower()
            if (name in FORBIDDEN or name.startswith(".env")
                    or any(word in name for word in ("credential", "secret"))
                    or name.startswith(("id_rsa", "id_ed25519"))
                    or name.endswith((".key", ".pem", ".sqlite", ".sqlite3", ".db", ".log"))):
                raise InstallError(f"Credential or runtime source is forbidden: {item}")
        if resolved in seen:
            continue
        seen.add(resolved)
        if item.is_dir():
            pending.extend(item.iterdir())
        elif not item.is_file():
            raise InstallError(f"Source must be a file or directory: {item}")


def safe_parent(path, home):
    if not within(path, home) or path == home:
        raise InstallError(f"Target is outside HOME: {path}")
    for parent in reversed(path.parent.parents):
        if within(parent, home) and not within(parent.resolve(), home):
            raise InstallError(f"Target ancestor escapes HOME: {parent}")
    if not within(path.parent.resolve(), home):
        raise InstallError(f"Target ancestor escapes HOME: {path.parent}")
    for parent in (path.parent, *path.parent.parents):
        if within(parent, home) and exists(parent) and not parent.is_dir():
            raise InstallError(f"Target ancestor is not a directory: {parent}")


def correct_link(target, source):
    return target.is_symlink() and target.resolve() == source.resolve()


def identity(path):
    info = path.lstat()
    return [info.st_dev, info.st_ino, info.st_mode]


def link_identity(path):
    return [*identity(path), path.lstat().st_ctime_ns]


def manifest_links(mappings):
    extensions = Path("pi/agent/extensions")
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {"source", "target"}:
            raise InstallError("Each link must contain source and target")
        source = relative_path(mapping["source"])
        target = relative_path(mapping["target"])
        yield source, target, False
        if (source.name == "package.json" and source.is_relative_to(extensions)
                and target == Path(".pi/agent/extensions") / source.relative_to(extensions)):
            yield source.parent / "node_modules", target.parent / "node_modules", True


def preflight(repo, home, manifest, backup_existing=False):
    repo, home = Path(repo).resolve(), Path(home).resolve()
    if not home.is_dir():
        raise InstallError(f"HOME must be an existing directory: {home}")
    data = json.loads(Path(manifest).read_text())
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or not isinstance(data.get("links"), list)):
        raise InstallError("Expected manifest {version: 1, links: [...]}")
    entries, targets = [], []
    for source_path, target_path, dependency in manifest_links(data["links"]):
        source = repo / source_path
        target = home / target_path
        if dependency:
            # Link local dependencies without importing their contents as configuration.
            # A dangling link also supports running make dep after make install.
            if not within(source.resolve(), repo) or (exists(source) and not source.is_dir()):
                raise InstallError(f"Invalid dependency directory: {source}")
        else:
            safe_source(source, repo)
        safe_parent(target, home)
        effective = target.parent.resolve() / target.name
        if within(effective, repo) or within(repo, effective):
            raise InstallError(f"Target overlaps repository: {target}")
        reserved = home / STATE.parent
        if within(effective, reserved) or within(reserved, effective):
            raise InstallError(f"Target overlaps installer state: {target}")
        for previous in targets:
            if within(effective, previous) or within(previous, effective):
                raise InstallError(f"Duplicate or overlapping target: {target}")
        targets.append(effective)
        correct = correct_link(target, source)
        occupied = exists(target)
        if occupied and not correct and not backup_existing:
            raise InstallError(f"Occupied target (use --backup-existing): {target}")
        entries.append({"source": str(source), "target": str(target),
                        "effective": str(effective),
                        "original": identity(target) if occupied else None,
                        "directory": dependency or source.is_dir(),
                        "skip": correct})
    return entries


def state_root(home):
    root = home / STATE
    safe_parent(root / "run", home)
    for path in (root, *root.parents):
        if within(path, home) and path.is_symlink():
            raise InstallError(f"Installer state cannot use symlinks: {path}")
    return root


def save_journal(run, journal):
    temporary = run / "journal.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(journal, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(run / "journal.json")


def make_parents(target, home, run, journal):
    missing = []
    parent = target.parent
    while parent != home and not exists(parent):
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir()
        journal["parents"].append({"path": str(parent), "identity": identity(parent)})
        save_journal(run, journal)


def restore_entries(home, run, journal):
    """Preflight the entire journal before removing any installed links."""
    repo = Path(journal["repo"])
    if not repo.is_absolute() or not isinstance(journal["parents"], list):
        raise InstallError("Invalid journal repository or parents")
    for item in journal["parents"]:
        parent = Path(item["path"])
        safe_parent(parent, home)
        if within(parent.resolve(), repo) or within(repo, parent.resolve()):
            raise InstallError("Journal parent overlaps repository")
        if not isinstance(item["identity"], list) or len(item["identity"]) != 3:
            raise InstallError("Invalid parent identity in journal")
    actions = []
    targets = []
    for entry in journal["links"]:
        target, source = Path(entry["target"]), Path(entry["source"])
        backup = Path(entry["backup"]) if entry["backup"] else None
        if not target.is_absolute() or not source.is_absolute():
            raise InstallError("Invalid journal paths")
        safe_parent(target, home)
        effective = target.parent.resolve() / target.name
        if str(effective) != entry["effective"]:
            raise InstallError(f"Target ancestor has changed: {target}")
        if within(effective, repo) or within(repo, effective):
            raise InstallError("Journal target overlaps repository")
        if any(within(effective, previous) or within(previous, effective) for previous in targets):
            raise InstallError("Duplicate or overlapping journal targets")
        targets.append(effective)
        reserved = home / STATE.parent
        if within(effective, reserved) or within(reserved, effective):
            raise InstallError("Journal target overlaps installer state")
        if backup and (backup.parent != run or backup.name != str(entry["index"])):
            raise InstallError("Invalid backup path in journal")
        if entry["progress"] not in {"planned", "backed_up", "installed", "restoring", "restored"}:
            raise InstallError("Invalid journal progress")
        if entry["progress"] == "restored":
            continue
        original = entry["original"]
        has_backup = backup is not None and exists(backup)
        if has_backup and identity(backup) != original:
            raise InstallError(f"Backup has changed: {backup}")
        if original is not None and not has_backup:
            if (entry["progress"] in ("planned", "restoring") and exists(target)
                    and identity(target) == original):
                actions.append((entry, False, False))
                continue
            raise InstallError(f"Original restore destination is uncertain: {target}")
        installed = exists(target)
        if installed:
            if not entry.get("installed") or not correct_link(target, source):
                raise InstallError(f"Installed link has changed: {target}")
            if link_identity(target) != entry["installed"]:
                raise InstallError(f"Installed link has been replaced: {target}")
        elif entry["progress"] == "installed":
            raise InstallError(f"Installed link is missing: {target}")
        actions.append((entry, installed, has_backup))
    return actions


def perform_restore(home, run, journal):
    actions = restore_entries(home, run, journal)
    for entry, installed, has_backup in actions:
        target = Path(entry["target"])
        entry["progress"] = "restoring"
        save_journal(run, journal)
        if installed:
            safe_parent(target, home)
            if link_identity(target) != entry["installed"] or not target.is_symlink():
                raise InstallError(f"Installed link changed during restore: {target}")
            target.unlink()
        if has_backup:
            if exists(target):
                raise InstallError(f"Restore destination became occupied: {target}")
            Path(entry["backup"]).rename(target)
        entry["progress"] = "restored"
        save_journal(run, journal)
    for item in reversed(journal["parents"]):
        parent = Path(item["path"])
        if not within(parent, home) or parent == home:
            raise InstallError("Invalid parent in journal")
        safe_parent(parent, home)
        if exists(parent) and identity(parent) == item["identity"]:
            try:
                parent.rmdir()
            except OSError:
                pass  # Nonempty directories may contain new user files.
    journal["status"] = "restored"
    save_journal(run, journal)


def install(repo, home, manifest, apply=False, backup_existing=False):
    home = Path(home).resolve()
    entries = preflight(repo, home, manifest, backup_existing)
    pending = [entry for entry in entries if not entry["skip"]]
    for entry in entries:
        action = "unchanged" if entry["skip"] else "backup + link" if entry["original"] else "link"
        print(f"{action}: {entry['target']} -> {entry['source']}")
    if not apply or not pending:
        return None
    root = state_root(home)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    run = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    journal = {"version": 1, "home": str(home), "repo": str(Path(repo).resolve()), "status": "installing",
               "parents": [], "links": []}
    for index, entry in enumerate(pending):
        journal["links"].append({**entry, "index": index,
                                 "backup": str(run / str(index)) if entry["original"] else None,
                                 "progress": "planned", "installed": None})
    save_journal(run, journal)
    try:
        for entry in journal["links"]:
            target = Path(entry["target"])
            safe_parent(target, home)
            if str(target.parent.resolve() / target.name) != entry["effective"]:
                raise InstallError(f"Target ancestor changed after preflight: {target}")
            current = identity(target) if exists(target) else None
            if current != entry["original"]:
                raise InstallError(f"Target changed after preflight: {target}")
            make_parents(target, home, run, journal)
            if entry["backup"]:
                target.rename(entry["backup"])
                entry["progress"] = "backed_up"
                save_journal(run, journal)
            target.symlink_to(entry["source"], target_is_directory=entry["directory"])
            entry["installed"] = link_identity(target)
            entry["progress"] = "installed"
            save_journal(run, journal)
        journal["status"] = "installed"
        save_journal(run, journal)
    except Exception as error:
        try:
            perform_restore(home, run, journal)
        except Exception as rollback_error:
            raise InstallError(f"Install failed: {error}; rollback incomplete: {rollback_error}; run: {run}") from error
        raise InstallError(f"Install failed: {error}; rolled back; run: {run}") from error
    print(f"Restore journal: {run}")
    return run


def restore(home, run, apply=False):
    home = Path(home).resolve()
    root = state_root(home)
    run = Path(run).absolute()
    if run.is_symlink() or run.parent != root or not run.is_dir():
        raise InstallError(f"Restore run must be a directory directly under {root}")
    journal_path = run / "journal.json"
    if journal_path.is_symlink():
        raise InstallError("Journal cannot be a symlink")
    journal = json.loads(journal_path.read_text())
    if (not isinstance(journal, dict) or type(journal.get("version")) is not int
            or journal["version"] != 1 or journal.get("home") != str(home)
            or not isinstance(journal.get("links"), list)):
        raise InstallError("Journal version or HOME does not match")
    restore_entries(home, run, journal)
    if not apply:
        print(f"Dry run: restore {run}; use --apply to restore")
        return
    try:
        perform_restore(home, run, journal)
    except Exception as error:
        raise InstallError(f"Restore incomplete: {error}; run: {run}") from error
    print(f"Restored: {run}")


def main(argv=None):
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--manifest", type=Path, default=repo / "links.json")
    parser.add_argument("--apply", action="store_true", help="Perform changes (default: dry run)")
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="RUN_DIR")
    args = parser.parse_args(argv)
    try:
        if args.restore:
            restore(args.home, args.restore, args.apply)
        else:
            install(repo, args.home, args.manifest, args.apply, args.backup_existing)
    except (InstallError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
