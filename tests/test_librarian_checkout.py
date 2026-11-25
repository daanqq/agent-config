import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "common/skills/librarian/checkout.sh"


def run_git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


class LibrarianCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="librarian-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.cache = self.root / "checkouts"
        self.remotes = self.root / "remotes"
        self.remotes.mkdir()

        # Map https://example.test/ -> local bare repos via temporary HOME .gitconfig
        gitconfig = self.home / ".gitconfig"
        gitconfig.write_text(
            f"[url \"file://{self.remotes}/\"]\n\tinsteadOf = https://example.test/\n",
            encoding="utf-8",
        )

    def make_bare_repo(self, rel_path):
        src = self.root / f"src-{rel_path.replace('/', '-')}"
        src.mkdir(parents=True)
        run_git(src, "init", "-b", "main")
        run_git(src, "config", "user.email", "test@example.com")
        run_git(src, "config", "user.name", "Test")
        (src / "README.md").write_text(f"# {rel_path}\n", encoding="utf-8")
        run_git(src, "add", "README.md")
        run_git(src, "commit", "-m", "init")
        bare = self.remotes / f"{rel_path}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        run_git(self.root, "clone", "--bare", str(src), str(bare))
        return bare

    def invoke(self, *args, extra_env=None):
        env = {
            **os.environ,
            "HOME": str(self.home),
            "LIBRARIAN_CACHE_ROOT": str(self.cache),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_clones_marks_last_used_and_prunes_only_stale_clean_checkouts(self):
        self.make_bare_repo("group/sub/active")
        self.make_bare_repo("oldorg/stale-clean")
        self.make_bare_repo("oldorg/stale-dirty")
        self.make_bare_repo("freshorg/recent")

        for ref in (
            "https://example.test/oldorg/stale-clean",
            "https://example.test/oldorg/stale-dirty",
            "https://example.test/freshorg/recent",
        ):
            res = self.invoke(ref, "--shallow", "--path-only")
            self.assertEqual(res.returncode, 0, res.stderr)

        stale_clean = self.cache / "example.test/oldorg/stale-clean"
        stale_dirty = self.cache / "example.test/oldorg/stale-dirty"
        recent = self.cache / "example.test/freshorg/recent"

        old_ts = str(int(time.time()) - 31 * 86400)
        (stale_clean / ".git/librarian-last-used").write_text(old_ts + "\n", encoding="utf-8")
        (stale_dirty / ".git/librarian-last-used").write_text(old_ts + "\n", encoding="utf-8")
        (stale_dirty / "untracked.txt").write_text("keep me\n", encoding="utf-8")

        # Deep GitLab URL with /-/blob/... should resolve cleanly and prune stale_clean.
        res = self.invoke("https://example.test/group/sub/active/-/blob/main/README.md", "--shallow", "--path-only")
        self.assertEqual(res.returncode, 0, res.stderr)
        active = Path(res.stdout.strip())
        self.assertEqual(active, self.cache / "example.test/group/sub/active")
        self.assertTrue((active / ".git/librarian-last-used").is_file())

        self.assertFalse(stale_clean.exists(), "clean checkout older than 30 days should be pruned")
        self.assertTrue(stale_dirty.exists(), "dirty checkout must never be pruned")
        self.assertTrue(recent.exists(), "fresh checkout within 30-day TTL must remain")


if __name__ == "__main__":
    unittest.main()
