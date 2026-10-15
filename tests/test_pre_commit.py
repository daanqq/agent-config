import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-staged.py"
HOOK = ROOT / ".githooks/pre-commit"


class PreCommitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agent-config-hook-test-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo with spaces"
        self.repo.mkdir()
        self.env = os.environ.copy()
        for name in subprocess.check_output(
            ["git", "rev-parse", "--local-env-vars"], text=True,
        ).splitlines():
            self.env.pop(name, None)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.git("init", "--quiet")
        self.git("config", "user.name", "Hook test")
        self.git("config", "user.email", "hook-test@example.invalid")
        (self.repo / "Makefile").write_text(
            "check:\n\t@test \"$$(cat value)\" = good\n", encoding="utf-8",
        )
        (self.repo / "value").write_text("good", encoding="utf-8")
        self.git("add", "--all")

    def git(self, *arguments, check=True, env=None):
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments], env=env or self.env,
            check=check, capture_output=True, text=True,
        )

    def run_check(self, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=self.repo, env=env or self.env,
            capture_output=True, text=True,
        )

    def test_staged_failure_is_not_hidden_by_unstaged_fix(self):
        value = self.repo / "value"
        value.write_text("bad", encoding="utf-8")
        self.git("add", "value")
        value.write_text("good", encoding="utf-8")
        index = (self.repo / ".git/index").read_bytes()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(value.read_text(), "good")
        self.assertEqual(self.git("show", ":value").stdout, "bad")
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)

    def test_unstaged_failure_and_untracked_files_do_not_change_staged_check(self):
        (self.repo / "value").write_text("bad", encoding="utf-8")
        unknown = self.repo / "private-untracked.txt"
        unknown.write_text("keep", encoding="utf-8")
        index = (self.repo / ".git/index").read_bytes()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.repo / "value").read_text(), "bad")
        self.assertEqual(unknown.read_text(), "keep")
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)

    def test_skip_worktree_entries_are_included_without_changing_original_index(self):
        self.git("update-index", "--skip-worktree", "value")
        (self.repo / "value").unlink()
        index = (self.repo / ".git/index").read_bytes()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.repo / "value").exists())
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertTrue(self.git("ls-files", "-v", "value").stdout.startswith("S "))

    def test_hook_git_environment_does_not_leak_into_snapshot(self):
        env = {**self.env, "GIT_DIR": str(self.repo / ".git"),
               "GIT_INDEX_FILE": str(self.repo / ".git/index"),
               "GIT_WORK_TREE": str(self.repo)}
        index = (self.repo / ".git/index").read_bytes()
        result = self.run_check(env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)

    def install_hook(self):
        for source, relative in ((HOOK, ".githooks/pre-commit"),
                                 (SCRIPT, "scripts/check-staged.py")):
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (self.repo / ".githooks/pre-commit").chmod(0o755)
        self.git("config", "core.hooksPath", ".githooks")
        self.git("add", "--all")

    def test_git_commit_is_blocked_on_staged_failure(self):
        self.install_hook()
        (self.repo / "value").write_text("bad", encoding="utf-8")
        self.git("add", "value")
        result = self.git("commit", "--quiet", "-m", "test: rejected", check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Checking staged snapshot", result.stdout + result.stderr)
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)

    def test_git_commit_accepts_good_index_without_stashing_unstaged_changes(self):
        self.install_hook()
        (self.repo / "value").write_text("unstaged user edit", encoding="utf-8")
        result = self.git("commit", "--quiet", "-m", "test: accepted", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("show", "HEAD:value").stdout, "good")
        self.assertEqual((self.repo / "value").read_text(), "unstaged user edit")
        self.assertEqual(self.git("stash", "list").stdout, "")

    def test_staged_whitespace_error_is_rejected(self):
        (self.repo / "whitespace.txt").write_text("trailing space \n", encoding="utf-8")
        self.git("add", "whitespace.txt")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Checking staged snapshot", result.stdout)


if __name__ == "__main__":
    unittest.main()
