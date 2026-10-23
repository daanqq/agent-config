from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import io
import json
import os
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
    _render_verification,
    extract_task_id,
    extract_task_ids,
    parse_mr_url,
    verification_commands,
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
        self.assertEqual(extract_task_ids(["t-12 T-9", "T-12"]), ["T-12", "T-9"])

    def test_task_ids_do_not_match_work_ids_or_partial_identifiers(self) -> None:
        self.assertEqual(extract_task_id("feature/T-123"), "T-123")
        self.assertEqual(extract_task_id("task/T-124"), "T-124")
        self.assertIsNone(extract_task_id("J-123 J-EUTP-456 J-T-789 T-12abc"))
        self.assertIsNone(extract_task_id("T-123 T-124"))
        self.assertIsNone(extract_task_id("feature/T-123-T-124"))
        self.assertEqual(extract_task_id("EUTP-456"), "EUTP-456")

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


class VerificationCommandsTests(unittest.TestCase):
    def make_package(self, root: Path, package: dict, *, tools: tuple[str, ...] = (), installed: tuple[str, ...] = ()) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
        modules = root / "node_modules"
        modules.mkdir()
        (modules / ".bin").mkdir()
        for tool in tools:
            (modules / ".bin" / tool).write_text("", encoding="utf-8")
        for name in installed:
            (modules / name).mkdir(parents=True, exist_ok=True)

    def test_no_package_json_gives_no_verification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(verification_commands(Path(raw)))

    def test_scripts_use_lockfile_package_manager(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            self.make_package(
                repo,
                {"scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"}, "devDependencies": {"vitest": "1"}},
                installed=("vitest",),
            )
            (repo / "pnpm-lock.yaml").write_text("", encoding="utf-8")
            result = verification_commands(repo)
            self.assertEqual(result["test_command"], f"cd '{repo}' && pnpm run test")
            self.assertEqual(result["typecheck_command"], f"cd '{repo}' && pnpm run typecheck")
            self.assertEqual(result["missing_dependencies"], [])
            self.assertEqual(result["notes"], [])

    def test_binaries_come_from_node_modules_bin_when_scripts_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            self.make_package(repo, {}, tools=("vitest", "tsc"))
            (repo / "tsconfig.json").write_text("{}", encoding="utf-8")
            result = verification_commands(repo)
            self.assertEqual(result["test_command"], f"cd '{repo}' && '{repo}/node_modules/.bin/vitest' run")
            self.assertEqual(result["typecheck_command"], f"cd '{repo}' && '{repo}/node_modules/.bin/tsc' --noEmit")

    def test_missing_runner_and_dependencies_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            self.make_package(
                repo,
                {"dependencies": {"libphonenumber-js": "1", "@scope/present": "1"}},
                installed=("@scope/present",),
            )
            result = verification_commands(repo)
            self.assertEqual(result["missing_dependencies"], ["libphonenumber-js"])
            self.assertIsNone(result["test_command"])
            self.assertIsNone(result["typecheck_command"])
            notes = " ".join(result["notes"])
            self.assertIn("libphonenumber-js", notes)
            self.assertIn("report test as not run", notes)
            self.assertIn("report typecheck as not run", notes)

    def test_missing_node_modules_gives_no_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            repo.mkdir()
            (repo / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            result = verification_commands(repo)
            self.assertIsNone(result["node_modules"])
            self.assertIsNone(result["test_command"])
            self.assertIn("not found", result["notes"][0])

    def test_source_repository_node_modules_is_used_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source"
            self.make_package(source, {"scripts": {"test": "vitest run"}})
            worktree = root / "worktree"
            worktree.mkdir()
            (worktree / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            result = verification_commands(worktree, source)
            self.assertEqual(result["node_modules"], str(source / "node_modules"))
            self.assertEqual(
                result["test_command"],
                f"cd '{worktree}' && PATH='{source}/node_modules/.bin':\"$PATH\" npm run test",
            )
            self.assertIn("only in the source repository", result["notes"][0])

    def test_markdown_renders_commands_and_notes(self) -> None:
        target = {
            "repo": "app",
            "verification": {"test_command": "cd x && npm run test", "typecheck_command": None, "notes": ["note one"]},
        }
        text = "\n".join(_render_verification(target))
        self.assertIn("## Verification commands: app", text)
        self.assertIn("cd x && npm run test", text)
        self.assertIn("- note one", text)
        self.assertEqual(_render_verification({"repo": "app", "verification": None}), [])


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
            run("git", "-C", str(repo), "checkout", "-b", "feature/T-123")
            (repo / "tracked.txt").write_text("branch\n", encoding="utf-8")
            run("git", "-C", str(repo), "commit", "-am", "T-123 branch change")
            (repo / "tracked.txt").write_text("working tree\n", encoding="utf-8")
            (repo / "new.txt").write_text("untracked\n", encoding="utf-8")

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
            self.assertEqual(target["task_id"], "T-123")
            self.assertIsNone(context["primary_task"]["task"])
            self.assertEqual(target["scope"], "all")
            self.assertIn("tracked.txt", target["file_sets"]["branch"])
            self.assertIn("tracked.txt", target["file_sets"]["unstaged"])
            self.assertEqual(target["untracked_files"], ["new.txt"])
            cleanup_code, _, cleanup_stderr = self.invoke(["cleanup", result["workspace"]])
            self.assertEqual((cleanup_code, cleanup_stderr), (0, ""))
            self.assertFalse(Path(result["workspace"]).exists())

    def test_local_prepare_emits_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            run("git", "init", "-b", "master", str(repo))
            configure_repo(repo)
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"absent-dep": "1"}}), encoding="utf-8"
            )
            (repo / ".gitignore").write_text("node_modules\n", encoding="utf-8")
            run("git", "-C", str(repo), "add", ".")
            run("git", "-C", str(repo), "commit", "-m", "base")
            (repo / "node_modules").mkdir()

            code, stdout, stderr = self.invoke(
                [
                    "prepare", "local", str(repo), "--base", "master", "--scope", "all",
                    "--output-root", str(root / "jobs"), "--lock-root", str(root / "locks"), "--offline",
                ]
            )
            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            context = json.loads(Path(result["review_context_json"]).read_text(encoding="utf-8"))
            verification = context["targets"][0]["verification"]
            self.assertEqual(verification["test_command"], f"cd '{repo}' && npm run test")
            self.assertEqual(verification["missing_dependencies"], ["absent-dep"])
            markdown = Path(result["review_context_markdown"]).read_text(encoding="utf-8")
            self.assertIn("## Verification commands: repo", markdown)
            self.assertIn("absent-dep", markdown)
            self.invoke(["cleanup", result["workspace"]])

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
            run("git", "-C", str(seed), "checkout", "-b", "feature/T-77")
            (seed / "app.txt").write_text("mr\n", encoding="utf-8")
            run("git", "-C", str(seed), "commit", "-am", "T-77 MR")
            run("git", "-C", str(seed), "push", "origin", "HEAD:refs/merge-requests/7/head")
            clones.mkdir()
            run("git", "clone", str(origin), str(source))
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps({"title": "T-77 change", "source_branch": "feature/T-77", "target_branch": "master"}),
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
            self.assertEqual(target["task_id"], "T-77")
            self.assertEqual(target["mr"]["target_branch"], "master")
            self.assertEqual(target["file_sets"]["in_scope"], ["app.txt"])
            self.assertTrue(Path(target["path"]).is_dir())
            self.assertEqual(run("git", "-C", target["path"], "branch", "--show-current"), "")

            cleanup_code, _, cleanup_stderr = self.invoke(["cleanup", result["manifest"]])
            self.assertEqual((cleanup_code, cleanup_stderr), (0, ""))
            self.assertFalse(Path(result["workspace"]).exists())
            self.assertNotIn("echat-mr-review", run("git", "-C", str(source), "show-ref"))


def mr_fixture(root: Path, files: dict[str, str]) -> tuple[Path, str]:
    """Bare origin with MR !7 adding `files`, and a review clone under root/clones."""
    origin, seed, clones = root / "origin.git", root / "seed", root / "clones"
    run("git", "init", "--bare", str(origin))
    run("git", "init", "-b", "master", str(seed))
    configure_repo(seed)
    (seed / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    run("git", "-C", str(seed), "add", ".")
    run("git", "-C", str(seed), "commit", "-m", "base")
    run("git", "-C", str(seed), "remote", "add", "origin", str(origin))
    run("git", "-C", str(seed), "push", "origin", "master")
    run("git", "-C", str(seed), "checkout", "-b", "feature/T-78")
    for name, content in files.items():
        (seed / name).write_text(content, encoding="utf-8")
    run("git", "-C", str(seed), "add", ".")
    run("git", "-C", str(seed), "commit", "-m", "T-78 MR")
    run("git", "-C", str(seed), "push", "origin", "HEAD:refs/merge-requests/7/head")
    clones.mkdir()
    run("git", "clone", str(origin), str(clones / "project"))
    return clones, "https://git.example.test/group/project/-/merge_requests/7"


def stub_bin(root: Path, scripts: dict[str, str]) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for name, body in scripts.items():
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir


PACKAGE_FILES = {
    "package.json": json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"dep-a": "1"}}),
    "package-lock.json": "{}\n",
}
# Records its argv and installs dep-a like a successful `npm ci`.
FAKE_NPM = 'printf "%s\\n" "$*" >> "$NPM_LOG"\nmkdir -p node_modules/dep-a\n'


class DependencyInstallTests(unittest.TestCase):
    def prepare(self, root: Path, clones: Path, url: str, *extra: str) -> dict:
        stdout, stderr = io.StringIO(), io.StringIO()
        metadata = root / "metadata.json"
        metadata.write_text(json.dumps({"source_branch": "feature/T-78", "target_branch": "master"}), encoding="utf-8")
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "prepare", "mr", url, "--repo-root", str(clones), "--gitlab-metadata-file", str(metadata),
                    "--output-root", str(root / "jobs"), "--lock-root", str(root / "locks"), "--offline", *extra,
                ]
            )
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        result = json.loads(stdout.getvalue())
        self.addCleanup(main, ["cleanup", result["manifest"]])
        return json.loads(Path(result["review_context_json"]).read_text(encoding="utf-8"))["targets"][0]

    def env(self, root: Path, bin_dir: Path) -> dict[str, str]:
        return {"PATH": f"{bin_dir}:/usr/bin:/bin", "NPM_LOG": str(root / "npm.log")}

    def test_npm_ci_runs_in_review_worktree_from_mr_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, PACKAGE_FILES)
            bin_dir = stub_bin(root, {"npm": FAKE_NPM})
            with patch.dict(os.environ, self.env(root, bin_dir)):
                target = self.prepare(root, clones, url)
            verification = target["verification"]
            self.assertEqual(verification["install"]["status"], "installed")
            self.assertEqual(verification["node_modules"], str(Path(target["path"]) / "node_modules"))
            self.assertEqual(verification["missing_dependencies"], [])
            self.assertEqual(verification["test_command"], f"cd '{target['path']}' && npm run test")
            self.assertIn("installed from the MR lockfile", verification["notes"][0])
            log = (root / "npm.log").read_text(encoding="utf-8")
            self.assertEqual(log, "ci --ignore-scripts --prefer-offline --no-audit --no-fund\n")
            self.assertFalse((clones / "project" / "node_modules").exists())

    def test_nvmrc_runs_npm_through_n(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, {**PACKAGE_FILES, ".nvmrc": "22\n"})
            bin_dir = stub_bin(
                root,
                {"npm": FAKE_NPM, "n": 'printf "n %s\\n" "$*" >> "$NPM_LOG"\nshift 2\nexec "$@"\n'},
            )
            with patch.dict(os.environ, self.env(root, bin_dir)):
                target = self.prepare(root, clones, url)
            self.assertTrue(target["verification"]["install"]["command"].startswith("n exec 22 npm ci"))
            log = (root / "npm.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(log[0], "n exec 22 npm ci --ignore-scripts --prefer-offline --no-audit --no-fund")

    def test_failed_install_is_reported_without_failing_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, PACKAGE_FILES)
            bin_dir = stub_bin(root, {"npm": 'echo "npm ERR! 401 Unauthorized" >&2\nexit 1\n'})
            with patch.dict(os.environ, self.env(root, bin_dir)):
                target = self.prepare(root, clones, url)
            verification = target["verification"]
            self.assertEqual(verification["install"]["status"], "failed")
            self.assertIn("401 Unauthorized", verification["install"]["detail"])
            self.assertIn("401 Unauthorized", verification["notes"][0])
            self.assertIsNone(verification["node_modules"])

    def test_install_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, PACKAGE_FILES)
            bin_dir = stub_bin(root, {"npm": FAKE_NPM})
            with patch.dict(os.environ, self.env(root, bin_dir)):
                target = self.prepare(root, clones, url, "--no-install-dependencies")
            self.assertNotIn("install", target["verification"])
            self.assertFalse((root / "npm.log").exists())

    def test_without_lockfile_nothing_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, {"package.json": PACKAGE_FILES["package.json"]})
            bin_dir = stub_bin(root, {"npm": FAKE_NPM})
            with patch.dict(os.environ, self.env(root, bin_dir)):
                target = self.prepare(root, clones, url)
            self.assertNotIn("install", target["verification"])
            self.assertFalse((root / "npm.log").exists())


if __name__ == "__main__":
    unittest.main()
