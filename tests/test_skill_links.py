import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-skill-links.py"
TREES = {
    "common/skills": ".agents/skills",
    "pi/agent/skills": ".pi/agent/skills",
    "claude/skills": ".claude/skills",
}


class SkillLinksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="skill-links-test-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.home = self.repo / "home"
        self.home.mkdir()
        for tree in TREES:
            (self.repo / tree).mkdir(parents=True)
        self.manifest = {"version": 1, "links": []}

    def skill(self, tree, name):
        path = self.repo / tree / name
        path.mkdir()
        (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n")
        return path

    def mapping(self, tree, name):
        return {"source": f"{tree}/{name}", "target": f"{TREES[tree]}/{name}"}

    def run_check(self):
        (self.repo / "links.json").write_text(json.dumps(self.manifest))
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo)],
            capture_output=True, text=True,
            env={**os.environ, "HOME": str(self.home)},
        )

    def test_valid_skill_without_home_mapping_fails_even_with_manual_home_link(self):
        skill = self.skill("claude/skills", "example")
        home = self.repo / "home/.claude/skills"
        home.mkdir(parents=True)
        (home / "example").symlink_to(skill)
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("claude/skills/example -> .claude/skills/example", result.stderr)

    def test_complete_common_skill_and_client_aliases_pass(self):
        self.skill("common/skills", "shared")
        for tree, target in [("pi/agent/skills", "../../../common/skills/shared"),
                             ("claude/skills", "../../common/skills/shared")]:
            (self.repo / tree / "shared").symlink_to(target)
        self.manifest["links"] = [self.mapping(tree, "shared") for tree in TREES]
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_client_alias_mapping_is_not_hidden_by_common_mapping(self):
        self.skill("common/skills", "shared")
        (self.repo / "claude/skills/shared").symlink_to("../../common/skills/shared")
        self.manifest["links"] = [self.mapping("common/skills", "shared")]
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("claude/skills/shared -> .claude/skills/shared", result.stderr)

    def test_wrong_home_target_fails(self):
        self.skill("pi/agent/skills", "example")
        self.manifest["links"] = [{"source": "pi/agent/skills/example",
                                   "target": ".claude/skills/example"}]
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_explicit_repository_only_skill_passes(self):
        self.skill("common/skills", "example")
        self.manifest["uninstalled_skills"] = {
            "common/skills/example": "Repository-only helper, not a client command.",
        }
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_exclusion_fails(self):
        self.manifest["uninstalled_skills"] = {"common/skills/missing": "obsolete"}
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Stale uninstalled_skills entry", result.stderr)

    def test_unexplained_exclusion_fails_for_an_existing_skill(self):
        self.skill("common/skills", "example")
        for reason in ("", " ", None, 1):
            with self.subTest(reason=reason):
                self.manifest["uninstalled_skills"] = {"common/skills/example": reason}
                result = self.run_check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires a nonempty reason", result.stderr)
                self.assertNotIn("Stale", result.stderr)

    def test_invalid_exclusion_shape_fails(self):
        self.manifest["uninstalled_skills"] = []
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must map skill source paths to reasons", result.stderr)

    def test_mapped_skill_cannot_be_excluded(self):
        self.skill("common/skills", "example")
        self.manifest["links"] = [self.mapping("common/skills", "example")]
        self.manifest["uninstalled_skills"] = {"common/skills/example": "not installed"}
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("both mapped and excluded", result.stderr)

    def test_non_skill_directory_needs_no_mapping(self):
        (self.repo / "claude/skills/plugin").mkdir()
        self.assertEqual(self.run_check().returncode, 0)

    def test_invalid_mapping_and_manifest_fail(self):
        for manifest in ({"version": True, "links": []},
                         {"version": 1, "links": [{"source": "../escape", "target": "x"}]},
                         {"version": 1, "links": [{"source": "x"}]}):
            with self.subTest(manifest=manifest):
                self.manifest = manifest
                self.assertNotEqual(self.run_check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
