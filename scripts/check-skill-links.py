"""Check that every skill and client alias has its declared HOME installation link."""

import argparse
import json
from pathlib import Path
import sys

from install import InstallError, manifest_links


SKILL_TREES = {
    "common/skills": ".agents/skills",
    "pi/agent/skills": ".pi/agent/skills",
    "claude/skills": ".claude/skills",
}


def check_links(repo):
    data = json.loads((repo / "links.json").read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("version")) is not int
            or data["version"] != 1 or not isinstance(data.get("links"), list)):
        raise InstallError("Expected manifest {version: 1, links: [...]}")
    mappings = {(str(source), str(target))
                for source, target, _ in manifest_links(data["links"])}
    expected = {}
    for source_root, target_root in SKILL_TREES.items():
        for skill in (repo / source_root).iterdir():
            if (skill / "SKILL.md").is_file():
                expected[f"{source_root}/{skill.name}"] = f"{target_root}/{skill.name}"

    exclusions = data.get("uninstalled_skills", {})
    if not isinstance(exclusions, dict):
        raise InstallError("uninstalled_skills must map skill source paths to reasons")
    errors = []
    for source, reason in exclusions.items():
        if source not in expected:
            errors.append(f"Stale uninstalled_skills entry: {source}")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"uninstalled_skills requires a nonempty reason: {source}")
        if any(mapped_source == source for mapped_source, _ in mappings):
            errors.append(f"Skill is both mapped and excluded: {source}")
    for source, target in sorted(expected.items()):
        if source not in exclusions and (source, target) not in mappings:
            errors.append(f"Missing skill HOME mapping: {source} -> {target}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors = check_links(args.repo)
    except (InstallError, OSError, ValueError) as error:
        errors = [str(error)]
    if errors:
        print("Skill installation coverage check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Skill installation coverage check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
