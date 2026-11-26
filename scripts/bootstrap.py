"""Idempotent post-link bootstrap for mutable configs, T3 Antigravity providers, and Claude MCP."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


BACKUP_STATE = Path(".local/state/agent-config/backups")
T3_ANTIGRAVITY_EXCLUDED_INSTANCE_IDS = ("antigravity_antigravitytextgen",)


class BootstrapError(Exception):
    pass


def expand_template(text, home):
    return text.replace("{{HOME}}", str(home))


def seed_file(source, target, home, apply=False, expand_home=True):
    if os.path.lexists(target):
        print(f"skip (exists): {target}")
        return "skipped"
    print(f"seed: {target} <- {source}")
    if not apply:
        return "planned"
    content = source.read_text(encoding="utf-8")
    if expand_home:
        content = expand_template(content, home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return "seeded"


def is_same_resolved_link(target, source):
    return target.is_symlink() and target.resolve() == source.resolve()


def t3_antigravity_profile_hash(instance_id):
    return hashlib.sha256(instance_id.encode("utf-8")).hexdigest()


def excluded_t3_antigravity_profiles(home):
    excluded = {t3_antigravity_profile_hash(name) for name in T3_ANTIGRAVITY_EXCLUDED_INSTANCE_IDS}
    settings_path = home / ".t3/userdata/settings.json"
    if settings_path.is_file():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("providerInstances"), dict):
            for instance_id, cfg in data["providerInstances"].items():
                if not isinstance(cfg, dict) or cfg.get("driver") != "antigravity":
                    continue
                display_name = str(cfg.get("displayName", ""))
                if "textgen" in instance_id.lower() or "textgen" in display_name.lower():
                    excluded.add(t3_antigravity_profile_hash(instance_id))
    return excluded


def link_t3_antigravity(repo, home, apply=False, backup_existing=False):
    root = home / ".t3/userdata/providers/antigravity"
    if not root.is_dir():
        print(f"skip (no T3 Antigravity providers dir): {root}")
        return {"linked": 0, "unchanged": 0, "instances": 0}

    excluded = excluded_t3_antigravity_profiles(home)
    instances = []
    for candidate in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
        if candidate.name.endswith("-helper") or candidate.name in excluded:
            print(f"skip (excluded T3 Antigravity profile): {candidate}")
            continue
        instances.append(candidate)
    if not instances:
        print(f"skip (no T3 Antigravity provider instances): {root}")
        return {"linked": 0, "unchanged": 0, "instances": 0}

    gemini_skills = home / ".gemini/config/skills"
    plan = []
    for instance in instances:
        mappings = [
            (repo / "antigravity/GEMINI.md", instance / "GEMINI.md", False),
            (repo / "antigravity/config.json", instance / "config/config.json", False),
            (repo / "antigravity/t3-hooks.json", instance / "config/hooks.json", False),
            (repo / "antigravity/t3-mcp_config.json", instance / "config/mcp_config.json", False),
        ]
        if os.path.lexists(gemini_skills):
            mappings.append((gemini_skills, instance / "config/skills", True))
        for source, target, is_dir in mappings:
            if not os.path.lexists(source):
                raise BootstrapError(f"Missing Antigravity link source: {source}")
            if is_same_resolved_link(target, source):
                plan.append(("unchanged", source, target, is_dir))
            elif os.path.lexists(target):
                if not backup_existing:
                    raise BootstrapError(f"Occupied T3 Antigravity target (use --backup-existing): {target}")
                plan.append(("backup + link", source, target, is_dir))
            else:
                plan.append(("link", source, target, is_dir))

    linked = 0
    unchanged = 0
    backup_dir = None
    for index, (action, source, target, is_dir) in enumerate(plan):
        print(f"{action}: {target} -> {source}")
        if action == "unchanged":
            unchanged += 1
            continue
        if not apply:
            linked += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if action == "backup + link":
            if backup_dir is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup_root = home / BACKUP_STATE
                backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                backup_dir = backup_root / f"t3-antigravity-{stamp}"
                backup_dir.mkdir(mode=0o700, exist_ok=True)
            target.rename(backup_dir / f"{index}-{target.name}")
        target.symlink_to(source, target_is_directory=is_dir)
        linked += 1

    if backup_dir is not None:
        print(f"T3 Antigravity backup dir: {backup_dir}")
    return {"linked": linked, "unchanged": unchanged, "instances": len(instances)}


def sync_claude_mcp(repo, home, apply=False, claude_bin=None):
    spec_path = repo / "claude/mcp.json"
    if not spec_path.is_file():
        return {"added": 0, "skipped": 0}
    spec = json.loads(expand_template(spec_path.read_text(encoding="utf-8"), home))
    servers = spec.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise BootstrapError(f"Invalid mcpServers in {spec_path}")

    existing = {}
    claude_json = home / ".claude.json"
    if claude_json.is_file():
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
                existing = data["mcpServers"]
        except json.JSONDecodeError as error:
            raise BootstrapError(f"Invalid JSON in {claude_json}: {error}") from error

    missing = [(name, cfg) for name, cfg in servers.items() if name not in existing]
    for name in servers:
        if name in existing:
            print(f"unchanged mcp: {name}")
    if not missing:
        return {"added": 0, "skipped": len(servers)}

    binary = shutil.which("claude") if claude_bin is None else claude_bin
    added = 0
    for name, cfg in missing:
        if not apply:
            print(f"add mcp (claude -s user): {name}")
            added += 1
            continue
        if not binary:
            print(f"skip mcp (claude CLI not found): {name}")
            continue
        payload = json.dumps(cfg, separators=(",", ":"))
        env = {**os.environ, "HOME": str(home)}
        result = subprocess.run(
            [binary, "mcp", "add-json", "-s", "user", name, payload],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise BootstrapError(f"claude mcp add-json failed for {name}: {detail}")
        print(f"added mcp: {name}")
        added += 1
    return {"added": added, "skipped": len(servers) - len(missing)}


def report_missing_secrets(home):
    expected = [
        (home / ".claude/secrets/cliproxy-api-key", "Claude/Codex CLIProxy API key (via chezmoi)"),
        (home / ".pi/agent/models.json", "Pi models config (copy pi/agent/models.example.json or render via chezmoi)"),
        (home / ".pi/agent/secrets/cliproxy-management.json", "CLIProxy management credentials (optional, for quota)"),
    ]
    missing = [(path, hint) for path, hint in expected if not os.path.lexists(path)]
    if missing:
        print("Missing local secret/private files:")
        for path, hint in missing:
            print(f"  - {path}: {hint}")
    return [str(path) for path, _ in missing]


def run_bootstrap(repo, home, apply=False, backup_existing=False, claude_bin=None):
    repo = Path(repo).resolve()
    home = Path(home).resolve()
    if not home.is_dir():
        raise BootstrapError(f"HOME must be an existing directory: {home}")

    seeded = {
        "codex_config": seed_file(
            repo / "codex/config.base.toml",
            home / ".codex/config.toml",
            home,
            apply=apply,
            expand_home=True,
        ),
        "t3_settings": seed_file(
            repo / "t3/settings.base.json",
            home / ".t3/userdata/settings.json",
            home,
            apply=apply,
            expand_home=True,
        ),
        "t3_keybindings": seed_file(
            repo / "t3/keybindings.json",
            home / ".t3/userdata/keybindings.json",
            home,
            apply=apply,
            expand_home=False,
        ),
        "antigravity_cli_settings": seed_file(
            repo / "antigravity/cli-settings.base.json",
            home / ".gemini/antigravity-cli/settings.json",
            home,
            apply=apply,
            expand_home=True,
        ),
    }
    t3_links = link_t3_antigravity(repo, home, apply=apply, backup_existing=backup_existing)
    mcp = sync_claude_mcp(repo, home, apply=apply, claude_bin=claude_bin)
    missing_secrets = report_missing_secrets(home)
    return {
        "seeded": seeded,
        "t3_links": t3_links,
        "mcp": mcp,
        "missing_secrets": missing_secrets,
    }


def main(argv=None):
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--apply", action="store_true", help="Perform changes (default: dry run)")
    parser.add_argument("--backup-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_bootstrap(repo, args.home, apply=args.apply, backup_existing=args.backup_existing)
    except (BootstrapError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
