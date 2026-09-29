import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "common/skills-maintenance/check.py"
spec = importlib.util.spec_from_file_location("skill_check", SOURCE)
check = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(check)


class SkillMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.maintenance = self.root / "common/skills-maintenance"
        self.maintenance.mkdir(parents=True)
        for scope in check.SCOPES:
            if scope == "pi":
                (self.root / scope / "agent" / "skills").mkdir(parents=True)
            else:
                (self.root / scope / "skills").mkdir(parents=True)
        self.old = (check.ROOT, check.MAINTENANCE, check.MANIFEST, check.SKILL_ROOTS)
        check.ROOT = self.root
        check.MAINTENANCE = self.maintenance
        check.MANIFEST = self.maintenance / "manifest.json"
        check.SKILL_ROOTS = {
            "common": self.root / "common" / "skills",
            "pi": self.root / "pi" / "agent" / "skills",
            "claude": self.root / "claude" / "skills",
        }

    def tearDown(self):
        check.ROOT, check.MAINTENANCE, check.MANIFEST, check.SKILL_ROOTS = self.old
        self.tmp.cleanup()

    def skill(self, scope, name, text=None):
        path = check.SKILL_ROOTS[scope] / name
        path.mkdir()
        (path / "SKILL.md").write_text(text or f"---\nname: {name}\ndescription: test\n---\n", encoding="utf-8")
        return path

    def manifest(self, records):
        check.MANIFEST.write_text(json.dumps({"schema_version": 2, "repositories": {"x": {"cache": "x", "revision": "HEAD"}}, "skills": records}), encoding="utf-8")

    def records(self, scopes):
        result = {s: {} for s in check.SCOPES}
        for scope, names in scopes.items():
            for name in names:
                result[scope][name] = {"tracking": "local", "installed_hash": check.directory_hash(check.SKILL_ROOTS[scope] / name)}
        return result

    def test_clean_scopes_and_common_alias(self):
        self.skill("common", "shared")
        self.skill("pi", "own")
        (check.SKILL_ROOTS["pi"] / "shared").symlink_to(Path("../../../common/skills/shared"))
        self.manifest(self.records({"common": ["shared"], "pi": ["own"]}))
        self.assertEqual(check.main([]), 0)

    def test_broken_link_and_unknown_directory_fail(self):
        path = self.skill("common", "shared", "---\nname: shared\ndescription: test\n---\n[bad](missing.md)\n")
        (check.SKILL_ROOTS["common"] / "unknown").mkdir()
        (check.SKILL_ROOTS["common"] / "unknown" / "SKILL.md").write_text("", encoding="utf-8")
        self.manifest(self.records({"common": ["shared"]}))
        self.assertNotEqual(check.main([]), 0)

    def test_refresh_does_not_write_on_structural_error(self):
        self.skill("common", "shared")
        self.manifest(self.records({}))
        before = check.MANIFEST.read_text()
        self.assertNotEqual(check.main(["--refresh-installed-hashes"]), 0)
        self.assertEqual(check.MANIFEST.read_text(), before)

    def test_hash_drift_is_refreshable_in_selected_scope(self):
        self.skill("common", "shared")
        records = self.records({"common": ["shared"]})
        records["common"]["shared"]["installed_hash"] = "old"
        self.manifest(records)
        self.assertEqual(check.main(["--scope", "common", "--refresh-installed-hashes"]), 0)
        refreshed = json.loads(check.MANIFEST.read_text())
        self.assertEqual(refreshed["skills"]["common"]["shared"]["installed_hash"], check.directory_hash(check.SKILL_ROOTS["common"] / "shared"))

    def test_hash_algorithm_keeps_symlink_kind(self):
        path = self.skill("common", "shared")
        (path / "file").write_text("x")
        (path / "alias").symlink_to("file")
        self.assertNotEqual(check.directory_hash(path), check.directory_hash(path / "file"))

    def test_hash_tracks_executable_bit_but_not_group_write_permission(self):
        path = self.skill("common", "shared")
        skill_file = path / "SKILL.md"
        skill_file.chmod(0o644)
        regular = check.directory_hash(path)
        skill_file.chmod(0o664)
        self.assertEqual(check.directory_hash(path), regular)
        skill_file.chmod(0o755)
        executable = check.directory_hash(path)
        self.assertNotEqual(executable, regular)
        skill_file.chmod(0o775)
        self.assertEqual(check.directory_hash(path), executable)


if __name__ == "__main__":
    unittest.main()
