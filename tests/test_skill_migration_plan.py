import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "common/skills-maintenance/check-migration-plan.py"
spec = importlib.util.spec_from_file_location("migration_check", SCRIPT)
check = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(check)


class SkillMigrationPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.plan_file = Path(self.tmp.name) / "plan.json"
        self.env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull}
        self.git("init", "-q")
        self.put("early/SKILL.md", "early\n")
        self.put("late/SKILL.md", "late\n")
        self.put("retained/SKILL.md", "late\n")
        self.put("unrelated", "original\n")
        self.put("common/skills-maintenance/manifest.json", "{}\n")
        self.put("links.json", "{}\n")
        (self.repo / "alias").symlink_to("early")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def put(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def move(self, source, destination):
        return {"op": "move", "source": source, "destination": destination,
                "expected": check.inventory(self.repo, source)}

    def remove(self, source, preserve):
        return {"op": "remove", "source": source, "preserve": preserve,
                "expected": check.inventory(self.repo, source)}

    def snapshot(self):
        # Include all Git internals (especially index), manifests, links and empty dirs.
        result = {}
        for path in self.repo.rglob("*"):
            mode = path.lstat().st_mode
            data = os.readlink(path) if stat.S_ISLNK(mode) else path.read_bytes() if path.is_file() else None
            result[path.relative_to(self.repo).as_posix()] = (mode, data)
        return result

    def cli(self, operations=None, inventory=None):
        command = [sys.executable, str(SCRIPT), "--repo", str(self.repo)]
        if inventory is not None:
            command += ["--inventory", inventory]
        else:
            self.plan_file.write_text(json.dumps({"version": 1, "operations": operations}), encoding="utf-8")
            command += ["--plan", str(self.plan_file)]
        before = self.snapshot()
        result = subprocess.run(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(self.snapshot(), before, result.stderr)
        return result

    def assert_rejected(self, operations, message=None):
        result = self.cli(operations)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        if message:
            self.assertIn(message, result.stderr)
        return result

    def test_late_conflict_and_unknown_helper_are_read_only(self):
        operations = [self.move("early", "new/early"), self.move("late", "new/late")]
        self.put("new/late/unknown", "do not overwrite\n")
        self.put("late/helper.py", "unknown helper\n")
        self.assert_rejected(operations, "mismatch")
        # With the helper declared, the late destination still blocks the whole plan.
        operations[1] = self.move("late", "new/late")
        self.assert_rejected(operations, "Occupied destination")
        self.assertTrue((self.repo / "early/SKILL.md").exists())

    def test_valid_modified_move_and_preserved_removal_unrelated_dirty_allowed(self):
        self.put("early/SKILL.md", "known local changes\n")
        self.put("late/SKILL.md", "modified late\n")
        self.put("retained/SKILL.md", "modified late\n")
        self.put("unrelated", "unrelated dirty data\n")
        self.put("other-untracked", "leave alone\n")
        result = self.cli([self.move("early", "shared/early"),
                           self.remove("late", {"SKILL.md": "retained/SKILL.md"})])
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["result"], "passed")
        self.assertIn(" M early/SKILL.md", report["sources"][0]["git_status"])

    def test_explicit_replacement(self):
        result = self.cli([self.remove("late", {"SKILL.md": "retained/SKILL.md"}),
                           self.move("early", "late")])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_hash_and_content_mode_or_inventory_drift(self):
        op = self.move("early", "new")
        del op["expected"]["SKILL.md"]["sha256"]
        self.assert_rejected([op], "mismatch")
        for change in ("content", "mode", "empty directory", "ignored file"):
            with self.subTest(change=change):
                op = self.move("early", "new")
                if change == "content":
                    self.put("early/SKILL.md", "different\n")
                elif change == "mode":
                    (self.repo / "early/SKILL.md").chmod(0o755)
                elif change == "empty directory":
                    (self.repo / "early/empty").mkdir()
                else:
                    self.put(".gitignore", "*.cache\n")
                    self.put("early/local.cache", "unknown\n")
                self.assert_rejected([op], "mismatch")

    def test_removal_requires_exact_retained_copy_even_with_current_hash(self):
        self.put("late/SKILL.md", "unique local content\n")
        self.assert_rejected([self.remove("late", {})], "Every removed file")
        self.assert_rejected([self.remove("late", {"SKILL.md": "retained/SKILL.md"})], "differs")
        self.put("retained/SKILL.md", "unique local content\n")
        self.assert_rejected([self.remove("late", {"SKILL.md": "retained/SKILL.md"}),
                              self.move("retained", "elsewhere")], "affected by plan")
        self.assert_rejected([self.remove("late", {"SKILL.md": "late/SKILL.md"})], "affected by plan")

    def test_duplicates_and_ancestor_collisions(self):
        cases = [
            [self.move("early", "new"), self.move("early", "other")],
            [self.move("early", "new"), self.move("early/SKILL.md", "other")],
            [self.move("early", "new"), self.move("late", "new")],
            [self.move("early", "new"), self.move("late", "new/late")],
            [self.move("early", "early/new")],
            [self.move("early", "late")],
            [self.move("early", "retained/SKILL.md/child")],
        ]
        for ops in cases:
            with self.subTest(ops=ops):
                self.assert_rejected(ops)

    def test_unsafe_paths_and_symlinks(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.repo / "escape").symlink_to(outside, target_is_directory=True)
        (self.repo / "dangling").symlink_to("missing")
        for path in ("../outside", str(outside), ".", "early/../late", ".git/index",
                     "escape/new", "alias/new", "dangling", "early//new"):
            with self.subTest(path=path):
                op = self.move("early", "new")
                op["destination"] = path
                self.assert_rejected([op])
        (self.repo / "early/link").symlink_to(outside)
        self.assert_rejected([{"op": "move", "source": "early", "destination": "new", "expected": {}}])

    def test_missing_tracked_source_and_absent_tracked_target(self):
        (self.repo / "early/SKILL.md").unlink()
        self.assert_rejected([self.move("early", "new")], "Tracked source is missing")
        (self.repo / "late/SKILL.md").unlink()
        self.assert_rejected([self.move("retained/SKILL.md", "late/SKILL.md")], "tracked data")
        (self.repo / "unrelated").unlink()
        self.assert_rejected([self.move("retained", "unrelated/new")], "ancestor has tracked data")

    def test_inventory_cli_and_untracked_declared_move(self):
        self.put("early/helper.py", "declared helper\n")
        result = self.cli(inventory="early")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), check.inventory(self.repo, "early"))
        op = self.move("early", "new")
        op["expected"] = json.loads(result.stdout)
        result = self.cli([op])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sources"][0]["untracked_files"], 1)

    def test_staged_content_must_not_hide_an_extra_version(self):
        self.put("early/SKILL.md", "declared staged version\n")
        self.git("add", "early/SKILL.md")
        result = self.cli([self.move("early", "new")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.put("early/SKILL.md", "different worktree version\n")
        self.assert_rejected([self.move("early", "new")], "Distinct staged content")

    def test_preservation_requires_matching_executable_state(self):
        (self.repo / "retained/SKILL.md").chmod(0o755)
        self.assert_rejected([self.remove("late", {"SKILL.md": "retained/SKILL.md"})], "differs")

    def test_invalid_schema_and_duplicate_json_keys(self):
        self.assert_rejected([])
        self.assert_rejected([{"op": "execute"}])
        self.assert_rejected([{"op": []}])
        self.assert_rejected([{"op": "move", "source": "early", "destination": "new"}])
        self.plan_file.write_text('{"version":1,"version":1,"operations":[]}', encoding="utf-8")
        before = self.snapshot()
        result = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo),
                                 "--plan", str(self.plan_file)], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate JSON key", result.stderr)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
