from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from echat_mr_review.cli import main  # noqa: E402
from echat_mr_review.core import (  # noqa: E402
    MAX_HTTP_RESPONSE_BYTES,
    ReviewError,
    _NoRedirect,
    _fetch_json,
    extract_task_ids,
    parse_mr_url,
)


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.stdout.strip()


def configure_repo(repo: Path) -> None:
    run("git", "-C", str(repo), "config", "user.email", "review-test@example.invalid")
    run("git", "-C", str(repo), "config", "user.name", "Review Test")


class PureLogicTests(unittest.TestCase):
    def test_parse_nested_gitlab_mr_url(self) -> None:
        ref = parse_mr_url("https://git.example.test/group/sub/project/-/merge_requests/42")
        self.assertEqual(ref.host, "git.example.test")
        self.assertEqual(ref.project_path, "group/sub/project")
        self.assertEqual(ref.repo, "project")
        self.assertEqual(ref.iid, 42)

    def test_extract_task_ids_is_ordered_and_unique(self) -> None:
        self.assertEqual(extract_task_ids(["eutp-12 EUTP-9", "EUTP-12"]), ["EUTP-12", "EUTP-9"])

    def test_fetch_json_disables_redirects(self) -> None:
        class Response:
            headers: dict[str, str] = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit: int) -> bytes:
                return b'{"ok": true}'

        class Opener:
            def open(self, _request, timeout: float):
                self.timeout = timeout
                return Response()

        opener = Opener()
        with patch("echat_mr_review.core.urllib.request.build_opener", return_value=opener) as build:
            result = _fetch_json(object(), timeout=3, label="test")

        self.assertEqual(result, {"ok": True})
        self.assertIsInstance(build.call_args.args[0], _NoRedirect)
        self.assertEqual(opener.timeout, 3)

    def test_fetch_json_rejects_oversized_response(self) -> None:
        class Response:
            headers = {"Content-Length": str(MAX_HTTP_RESPONSE_BYTES + 1)}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        class Opener:
            def open(self, _request, timeout: float):
                return Response()

        with patch("echat_mr_review.core.urllib.request.build_opener", return_value=Opener()):
            with self.assertRaisesRegex(ReviewError, "size limit"):
                _fetch_json(object(), timeout=3, label="test")


class CliIntegrationTests(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_local_prepare_captures_branch_status_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            run("git", "init", "-b", "master", str(repo))
            configure_repo(repo)
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            run("git", "-C", str(repo), "add", "tracked.txt")
            run("git", "-C", str(repo), "commit", "-m", "base")
            run("git", "-C", str(repo), "checkout", "-b", "EUTP-123-feature")
            (repo / "tracked.txt").write_text("branch\n", encoding="utf-8")
            run("git", "-C", str(repo), "commit", "-am", "EUTP-123 branch change")
            (repo / "tracked.txt").write_text("working tree\n", encoding="utf-8")
            (repo / "new.txt").write_text("untracked\n", encoding="utf-8")

            secret = "test-pora-secret-must-not-be-written"
            with patch.dict("os.environ", {"PORA_SESSION": secret}):
                code, stdout, stderr = self.invoke(
                    [
                        "prepare", "local", str(repo), "--base", "master", "--scope", "all",
                        "--output-root", str(root / "jobs"), "--lock-root", str(root / "locks"), "--offline",
                    ]
                )
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertIn(str(SCRIPTS / "review_prepare.py"), result["cleanup_command"])
            context = json.loads(Path(result["review_context_json"]).read_text(encoding="utf-8"))
            target = context["targets"][0]
            self.assertEqual(target["task_id"], "EUTP-123")
            self.assertEqual(target["scope"], "all")
            self.assertIn("tracked.txt", target["file_sets"]["branch"])
            self.assertIn("tracked.txt", target["file_sets"]["unstaged"])
            self.assertEqual(target["untracked_files"], ["new.txt"])
            for artifact in (result["review_context_json"], result["review_context_markdown"], result["manifest"]):
                self.assertNotIn(secret, Path(artifact).read_text(encoding="utf-8"))

            cleanup_code, _, cleanup_stderr = self.invoke(["cleanup", result["workspace"]])
            self.assertEqual((cleanup_code, cleanup_stderr), (0, ""))
            self.assertFalse(Path(result["workspace"]).exists())

    def test_mr_prepare_uses_fixture_and_isolated_worktree_then_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            origin = root / "origin.git"
            seed = root / "seed"
            clones = root / "clones"
            source = clones / "project"
            run("git", "init", "--bare", str(origin))
            run("git", "init", "-b", "master", str(seed))
            configure_repo(seed)
            (seed / "app.txt").write_text("base\n", encoding="utf-8")
            run("git", "-C", str(seed), "add", "app.txt")
            run("git", "-C", str(seed), "commit", "-m", "base")
            run("git", "-C", str(seed), "remote", "add", "origin", str(origin))
            run("git", "-C", str(seed), "push", "origin", "master")
            run("git", "-C", str(seed), "checkout", "-b", "EUTP-77-feature")
            (seed / "app.txt").write_text("mr\n", encoding="utf-8")
            run("git", "-C", str(seed), "commit", "-am", "EUTP-77 MR")
            run("git", "-C", str(seed), "push", "origin", "HEAD:refs/merge-requests/7/head")
            clones.mkdir()
            run("git", "clone", str(origin), str(source))
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps({"title": "EUTP-77 change", "source_branch": "EUTP-77-feature", "target_branch": "master"}),
                encoding="utf-8",
            )
            url = "https://git.example.test/group/project/-/merge_requests/7"

            code, stdout, stderr = self.invoke(
                [
                    "prepare", "mr", url, "--repo-root", str(clones), "--gitlab-metadata-file", str(metadata),
                    "--output-root", str(root / "jobs"), "--lock-root", str(root / "locks"), "--offline",
                ]
            )
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            context = json.loads(Path(result["review_context_json"]).read_text(encoding="utf-8"))
            target = context["targets"][0]
            self.assertEqual(target["task_id"], "EUTP-77")
            self.assertEqual(target["mr"]["target_branch"], "master")
            self.assertEqual(target["file_sets"]["in_scope"], ["app.txt"])
            self.assertTrue(Path(target["path"]).is_dir())
            self.assertEqual(run("git", "-C", target["path"], "branch", "--show-current"), "")

            cleanup_code, _, cleanup_stderr = self.invoke(["cleanup", result["manifest"]])
            self.assertEqual((cleanup_code, cleanup_stderr), (0, ""))
            self.assertFalse(Path(result["workspace"]).exists())
            self.assertNotIn("echat-mr-review", run("git", "-C", str(source), "show-ref"))


if __name__ == "__main__":
    unittest.main()
