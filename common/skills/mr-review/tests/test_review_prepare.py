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

from echat_mr_review import core  # noqa: E402
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

    def test_cleanup_refuses_to_remove_the_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            run("git", "init", "-b", "master", str(repo))
            configure_repo(repo)
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            run("git", "-C", str(repo), "add", "tracked.txt")
            run("git", "-C", str(repo), "commit", "-m", "base")
            code, stdout, stderr = self.invoke(
                [
                    "prepare", "local", str(repo), "--base", "master", "--scope", "all",
                    "--output-root", str(root / "jobs"), "--lock-root", str(root / "locks"), "--offline",
                ]
            )
            self.assertEqual((code, stderr), (0, ""))
            workspace = Path(json.loads(stdout)["workspace"])
            previous = os.getcwd()
            os.chdir(workspace)
            try:
                code, _, stderr = self.invoke(["cleanup", str(workspace)])
            finally:
                os.chdir(previous)
            self.assertNotEqual(code, 0)
            self.assertIn("inside the workspace", stderr)
            self.assertTrue(workspace.exists())
            self.assertEqual(self.invoke(["cleanup", str(workspace)])[0], 0)
            self.assertFalse(workspace.exists())

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

    def test_nvmrc_prefers_mise_over_n(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, {**PACKAGE_FILES, ".nvmrc": "22\n"})
            bin_dir = stub_bin(
                root,
                {
                    "npm": FAKE_NPM,
                    "n": 'printf "n %s\\n" "$*" >> "$NPM_LOG"\nshift 2\nexec "$@"\n',
                    "mise": 'printf "mise %s\\n" "$*" >> "$NPM_LOG"\nshift 2\nexec "$@"\n',
                },
            )
            with patch.dict(os.environ, self.env(root, bin_dir)):
                target = self.prepare(root, clones, url)
            verification = target["verification"]
            self.assertTrue(verification["install"]["command"].startswith("mise exec -- npm ci"))
            log = (root / "npm.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(log[0], "mise exec -- npm ci --ignore-scripts --prefer-offline --no-audit --no-fund")
            self.assertEqual(verification["test_command"], f"cd '{target['path']}' && mise exec -- npm run test")

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


def discussion(index: int, *, system: bool = False, resolved: bool | None = None, position: dict | None = None) -> dict:
    note: dict = {
        "system": system,
        "author": {"username": f"user{index}", "name": f"User {index}"},
        "created_at": "2026-11-04T10:00:00Z",
        "body": f"note {index}",
    }
    if resolved is not None:
        note.update(resolvable=True, resolved=resolved)
    if position:
        note["position"] = position
    return {"id": f"d{index}", "notes": [note]}


class MrDiscussionsTests(unittest.TestCase):
    ref = parse_mr_url("https://git.example.test/group/project/-/merge_requests/7")

    def fetch(self, pages: dict[int, object] | Exception):
        requested: list[str] = []

        def fake(request, *, timeout: float, label: str):
            requested.append(request.full_url)
            if isinstance(pages, Exception):
                raise pages
            return pages[int(request.full_url.rsplit("page=", 1)[1])]

        with patch("echat_mr_review.core._fetch_json_value", side_effect=fake), patch(
            "echat_mr_review.core.shutil.which", return_value=None
        ):
            result = core.fetch_gitlab_discussions(self.ref, token="t", timeout=3, offline=False)
        return result, requested

    def test_offline_mode_skips_fetch(self) -> None:
        discussions, warning = core.fetch_gitlab_discussions(self.ref, token=None, timeout=3, offline=True)
        self.assertIsNone(discussions)
        self.assertIn("offline", warning)

    def test_all_pages_are_fetched(self) -> None:
        full = [discussion(i) for i in range(core.DISCUSSIONS_PER_PAGE)]
        (discussions, warning), requested = self.fetch({1: full, 2: [discussion(900)]})
        self.assertIsNone(warning)
        self.assertEqual(len(discussions), core.DISCUSSIONS_PER_PAGE + 1)
        self.assertEqual(discussions[-1]["notes"][0]["author"], "user900")
        self.assertEqual(len(requested), 2)
        self.assertIn("/merge_requests/7/discussions?per_page=100&page=2", requested[1])

    def test_system_notes_are_skipped(self) -> None:
        system_only = discussion(1, system=True)
        mixed = discussion(2)
        mixed["notes"].append(discussion(3, system=True)["notes"][0])
        (discussions, _), _ = self.fetch({1: [system_only, mixed]})
        self.assertEqual([item["id"] for item in discussions], ["d2"])
        self.assertEqual([note["body"] for note in discussions[0]["notes"]], ["note 2"])

    def test_resolved_state_and_diff_position_are_kept(self) -> None:
        position = {"new_path": "src/a.ts", "new_line": 12, "old_path": "src/a.ts", "old_line": None}
        (discussions, _), _ = self.fetch(
            {1: [discussion(1, resolved=True, position=position), discussion(2, resolved=False), discussion(3)]}
        )
        resolved, unresolved, plain = discussions
        self.assertEqual((resolved["resolvable"], resolved["resolved"]), (True, True))
        self.assertEqual(resolved["notes"][0]["position"], {"path": "src/a.ts", "line": 12})
        self.assertEqual((unresolved["resolvable"], unresolved["resolved"]), (True, False))
        self.assertEqual((plain["resolvable"], plain["resolved"]), (False, None))
        self.assertNotIn("position", plain["notes"][0])
        self.assertEqual(resolved["notes"][0]["author_name"], "User 1")

    def test_fetch_failure_is_reported(self) -> None:
        (discussions, warning), _ = self.fetch(ReviewError("GitLab API request failed: boom"))
        self.assertIsNone(discussions)
        self.assertIn("boom", warning)

    def test_prepare_puts_discussions_and_failure_warning_into_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clones, url = mr_fixture(root, {"app.txt": "mr\n"})
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"source_branch": "feature/T-78", "target_branch": "master"}), encoding="utf-8")

            def prepare(fake) -> dict:
                stdout = io.StringIO()
                with patch("echat_mr_review.core._fetch_json_value", side_effect=fake), patch(
                    "echat_mr_review.core.shutil.which", return_value=None
                ), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = main(
                        [
                            "prepare", "mr", url, "--repo-root", str(clones), "--gitlab-metadata-file", str(metadata),
                            "--output-root", str(root / "jobs"), "--lock-root", str(root / "locks"),
                        ]
                    )
                self.assertEqual(code, 0)
                result = json.loads(stdout.getvalue())
                self.addCleanup(main, ["cleanup", result["manifest"]])
                context = json.loads(Path(result["review_context_json"]).read_text(encoding="utf-8"))
                return context, Path(result["review_context_markdown"]).read_text(encoding="utf-8")

            context, markdown = prepare(lambda *_a, **_k: [discussion(1, resolved=False)])
            self.assertEqual(context["targets"][0]["mr"]["discussions"][0]["notes"][0]["body"], "note 1")
            self.assertEqual(context["warnings"], [])
            self.assertIn("MR discussions", markdown)
            self.assertIn("> note 1", markdown)

            def broken(*_a, **_k):
                raise ReviewError("boom")

            context, _ = prepare(broken)
            self.assertIsNone(context["targets"][0]["mr"]["discussions"])
            self.assertTrue(any("discussions" in item and "boom" in item for item in context["warnings"]))


class ReviewHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.history = self.root / "history"
        patcher = patch.dict(os.environ, {"MR_REVIEW_HISTORY_DIR": str(self.history)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clones, self.url = mr_fixture(self.root, {"app.txt": "mr\n"})
        self.seed = self.root / "seed"
        self.record_file = self.history / "git.example.test" / "group" / "project" / "7.json"

    def invoke(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def prepare(self) -> tuple[dict, dict, str]:
        metadata = self.root / "metadata.json"
        metadata.write_text(json.dumps({"source_branch": "feature/T-78", "target_branch": "master"}), encoding="utf-8")
        code, stdout, stderr = self.invoke(
            [
                "prepare", "mr", self.url, "--repo-root", str(self.clones), "--gitlab-metadata-file", str(metadata),
                "--output-root", str(self.root / "jobs"), "--lock-root", str(self.root / "locks"),
                "--offline", "--no-install-dependencies",
            ]
        )
        self.assertEqual((code, stderr), (0, ""))
        result = json.loads(stdout)
        self.addCleanup(main, ["cleanup", result["manifest"]])
        context = json.loads(Path(result["review_context_json"]).read_text(encoding="utf-8"))
        return result, context, Path(result["review_context_markdown"]).read_text(encoding="utf-8")

    def seed_head(self) -> str:
        return run("git", "-C", str(self.seed), "rev-parse", "HEAD")

    def write_record(self, head_sha: str, report: str = "- Major: old finding\n") -> None:
        self.record_file.parent.mkdir(parents=True)
        self.record_file.write_text(
            json.dumps({"head_sha": head_sha, "reviewed_at": "2026-11-10T10:00:00+00:00", "report": report}),
            encoding="utf-8",
        )

    def test_without_record_context_has_no_previous_review(self) -> None:
        _, context, markdown = self.prepare()
        target = context["targets"][0]
        self.assertEqual(target["head_sha"], self.seed_head())
        self.assertNotIn("previous_review", target)
        self.assertNotIn("Previous review", markdown)

    def test_same_head_is_reported_with_previous_report(self) -> None:
        self.write_record(self.seed_head())
        _, context, markdown = self.prepare()
        previous = context["targets"][0]["previous_review"]
        self.assertEqual(
            (previous["same_head"], previous["head_reachable"], previous["reviewed_at"], previous["path"]),
            (True, True, "2026-11-10T10:00:00+00:00", str(self.record_file)),
        )
        self.assertEqual(previous["report"], "- Major: old finding\n")
        self.assertIn("## Previous review: project", markdown)
        self.assertIn("- Same head: yes", markdown)
        self.assertIn("> - Major: old finding", markdown)
        self.assertNotIn("Incremental diff", markdown)

    def test_new_head_with_reachable_old_head_gives_incremental_diff(self) -> None:
        old_head = self.seed_head()
        self.write_record(old_head)
        (self.seed / "app.txt").write_text("mr 2\n", encoding="utf-8")
        run("git", "-C", str(self.seed), "commit", "-am", "T-78 follow-up")
        run("git", "-C", str(self.seed), "push", "-f", "origin", "HEAD:refs/merge-requests/7/head")
        # A previous review fetched the old head, so it is in the clone's object store.
        run("git", "-C", str(self.clones / "project"), "fetch", "origin", old_head)
        _, context, markdown = self.prepare()
        target = context["targets"][0]
        self.assertEqual(target["head_sha"], self.seed_head())
        self.assertEqual(
            (target["previous_review"]["same_head"], target["previous_review"]["head_reachable"]), (False, True)
        )
        self.assertIn(f"diff --find-renames {old_head}..HEAD --", markdown)
        self.assertIn(f"git -C '{target['path']}'", markdown)

    def test_unreachable_old_head_gives_no_incremental_diff(self) -> None:
        self.write_record("0" * 40)
        _, context, markdown = self.prepare()
        previous = context["targets"][0]["previous_review"]
        self.assertEqual((previous["same_head"], previous["head_reachable"]), (False, False))
        self.assertIn("- Previous head reachable in the worktree: no", markdown)
        self.assertNotIn("Incremental diff", markdown)

    def test_unusable_record_is_ignored_with_warning(self) -> None:
        self.record_file.parent.mkdir(parents=True)
        self.record_file.write_text("{broken", encoding="utf-8")
        _, context, _ = self.prepare()
        self.assertNotIn("previous_review", context["targets"][0])
        self.assertTrue(any("previous review record is unusable" in item for item in context["warnings"]))

    def test_record_writes_latest_review_and_next_prepare_sees_same_head(self) -> None:
        result, context, _ = self.prepare()
        report = self.root / "review-report.md"
        report.write_text("# Review\n\n- Minor: first\n", encoding="utf-8")
        code, stdout, stderr = self.invoke(["record", result["workspace"], "--report", str(report)])
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["recorded"], [str(self.record_file)])
        record = json.loads(self.record_file.read_text(encoding="utf-8"))
        target = context["targets"][0]
        self.assertEqual(
            (record["head_sha"], record["target_branch"], record["merge_base"], record["report"]),
            (target["head_sha"], "master", target["merge_base"], "# Review\n\n- Minor: first"),
        )
        self.assertRegex(record["reviewed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(sorted(path.name for path in self.record_file.parent.iterdir()), ["7.json"])

        _, next_context, _ = self.prepare()
        self.assertTrue(next_context["targets"][0]["previous_review"]["same_head"])
        report.write_text("# Review\n\n- Major: second\n", encoding="utf-8")
        self.assertEqual(self.invoke(["record", result["manifest"], "--report", str(report)])[0], 0)
        self.assertIn("second", json.loads(self.record_file.read_text(encoding="utf-8"))["report"])

    def test_record_target_filter(self) -> None:
        result, _, _ = self.prepare()
        report = self.root / "review-report.md"
        report.write_text("report\n", encoding="utf-8")
        other = "https://git.example.test/group/project/-/merge_requests/8"
        code, _, stderr = self.invoke(["record", result["workspace"], "--report", str(report), "--target", other])
        self.assertEqual(code, 2)
        self.assertIn("Not MR targets", stderr)
        self.assertFalse(self.record_file.exists())
        code, _, _ = self.invoke(["record", result["workspace"], "--report", str(report), "--target", self.url])
        self.assertEqual(code, 0)
        self.assertTrue(self.record_file.is_file())

    def test_record_refuses_foreign_workspace(self) -> None:
        report = self.root / "review-report.md"
        report.write_text("report\n", encoding="utf-8")
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "manifest.json").write_text(
            json.dumps({"tool": "other", "schema_version": 1, "root": str(foreign)}), encoding="utf-8"
        )
        code, _, stderr = self.invoke(["record", str(foreign), "--report", str(report)])
        self.assertEqual(code, 2)
        self.assertIn("Not a echat-mr-review manifest", stderr)

        result, _, _ = self.prepare()
        (Path(result["workspace"]) / ".echat-mr-review-workspace").write_text("someone-else\n", encoding="utf-8")
        code, _, stderr = self.invoke(["record", result["workspace"], "--report", str(report)])
        self.assertEqual(code, 2)
        self.assertIn("Unsafe workspace ownership data", stderr)
        self.assertFalse(self.history.exists())

    def test_record_refuses_local_workspace_and_empty_report(self) -> None:
        repo = self.root / "local"
        run("git", "init", "-b", "master", str(repo))
        configure_repo(repo)
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        run("git", "-C", str(repo), "add", ".")
        run("git", "-C", str(repo), "commit", "-m", "base")
        code, stdout, _ = self.invoke(
            [
                "prepare", "local", str(repo), "--base", "master", "--output-root", str(self.root / "jobs"),
                "--lock-root", str(self.root / "locks"), "--offline",
            ]
        )
        self.assertEqual(code, 0)
        local = json.loads(stdout)
        self.addCleanup(main, ["cleanup", local["manifest"]])
        report = self.root / "review-report.md"
        report.write_text("report\n", encoding="utf-8")
        code, _, stderr = self.invoke(["record", local["workspace"], "--report", str(report)])
        self.assertEqual(code, 2)
        self.assertIn("no MR targets", stderr)

        result, _, _ = self.prepare()
        report.write_text("  \n", encoding="utf-8")
        code, _, stderr = self.invoke(["record", result["workspace"], "--report", str(report)])
        self.assertEqual(code, 2)
        self.assertIn("report is empty", stderr)
        self.assertFalse(self.history.exists())

    def test_default_repo_root_falls_back_to_workspace_when_reviews_dir_missing(self) -> None:
        from echat_mr_review.cli import default_repo_root

        prev_repos = os.environ.pop("ECHAT_REVIEW_REPOS_ROOT", None)
        prev_ws = os.environ.get("ECHAT_WORKSPACE_ROOT")
        try:
            os.environ["ECHAT_WORKSPACE_ROOT"] = "/tmp/fake-echat-root"
            if not Path("/home/user/echat/reviews").is_dir():
                self.assertEqual(default_repo_root(), Path("/tmp/fake-echat-root"))
            os.environ["ECHAT_REVIEW_REPOS_ROOT"] = "/tmp/explicit-reviews"
            self.assertEqual(default_repo_root(), Path("/tmp/explicit-reviews"))
        finally:
            if prev_repos is None:
                os.environ.pop("ECHAT_REVIEW_REPOS_ROOT", None)
            else:
                os.environ["ECHAT_REVIEW_REPOS_ROOT"] = prev_repos
            if prev_ws is None:
                os.environ.pop("ECHAT_WORKSPACE_ROOT", None)
            else:
                os.environ["ECHAT_WORKSPACE_ROOT"] = prev_ws

    def test_previous_review_report_body_is_deduplicated_across_targets(self) -> None:
        from echat_mr_review.core import _render_previous_reviews

        body = "# Shared cross-repo review\nFinding 1"
        t1 = {
            "repo": "tidy-rest",
            "path": "/tmp/job/tidy-rest",
            "head_sha": "aaa111",
            "previous_review": {
                "reviewed_at": "2026-11-23T12:00:00Z",
                "head_sha": "aaa000",
                "same_head": False,
                "head_reachable": True,
                "path": "/tmp/history/tidy-rest/1.json",
                "report": body,
            },
        }
        t2 = {
            "repo": "tidy-client",
            "path": "/tmp/job/tidy-client",
            "head_sha": "bbb111",
            "previous_review": {
                "reviewed_at": "2026-11-23T12:00:00Z",
                "head_sha": "bbb111",
                "same_head": True,
                "head_reachable": True,
                "path": "/tmp/history/tidy-client/2.json",
                "report": body,
            },
        }
        rendered = "\n".join(_render_previous_reviews([t1, t2]))
        self.assertEqual(rendered.count("# Shared cross-repo review"), 1)
        self.assertIn("diff --find-renames aaa000..HEAD", rendered)
        self.assertIn("Previous report: identical to `tidy-rest` above.", rendered)

    def test_prune_stale_workspaces_removes_only_old_marked_jobs(self) -> None:
        from echat_mr_review.core import SCHEMA_VERSION, TOOL_NAME, WORKSPACE_MARKER, prune_stale_workspaces

        jobs = self.root / "prune-jobs"
        jobs.mkdir()
        stale = jobs / "review-20260801-000000-aaaaaaaa"
        stale.mkdir()
        (stale / WORKSPACE_MARKER).write_text(f"{stale.name}\n", encoding="utf-8")
        (stale / "manifest.json").write_text(
            json.dumps(
                {
                    "tool": TOOL_NAME,
                    "schema_version": SCHEMA_VERSION,
                    "root": str(stale),
                    "workspace_id": stale.name,
                    "lock_root": str(self.root / "locks"),
                    "worktrees": [],
                }
            ),
            encoding="utf-8",
        )
        old_ts = 1_000_000.0
        os.utime(stale / "manifest.json", (old_ts, old_ts))

        fresh = jobs / "review-20261125-000000-bbbbbbbb"
        fresh.mkdir()
        (fresh / WORKSPACE_MARKER).write_text("echat-mr-review-workspace-v1\n", encoding="utf-8")

        foreign = jobs / "review-20260801-000000-foreign"
        foreign.mkdir()
        os.utime(foreign, (old_ts, old_ts))

        removed = prune_stale_workspaces(jobs, max_age_seconds=3600, now=old_ts + 7200)
        self.assertEqual(removed, [str(stale)])
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(foreign.exists())

    def test_skipped_postinstall_and_patches_reported_in_verification(self) -> None:
        from unittest.mock import patch
        from echat_mr_review.core import mr_verification

        wt = self.root / "wt-postinstall"
        wt.mkdir()
        (wt / "package.json").write_text(
            json.dumps(
                {
                    "name": "tidy-client",
                    "scripts": {"postinstall": "patch-package --error-on-fail", "test:run": "vitest run"},
                }
            ),
            encoding="utf-8",
        )
        (wt / "package-lock.json").write_text('{"name":"tidy-client","lockfileVersion":3}\n', encoding="utf-8")
        patches = wt / "patches"
        patches.mkdir()
        (patches / "react-filerobot-image-editor+4.9.1.patch").write_text("--- a\n+++ b\n", encoding="utf-8")
        (patches / "@scope+pkg+1.2.3.patch").write_text("--- a\n+++ b\n", encoding="utf-8")

        fake_install = {"status": "installed", "command": "npm ci --ignore-scripts", "detail": ""}
        with patch("echat_mr_review.core.install_review_dependencies", return_value=fake_install):
            result = mr_verification(
                wt,
                wt,
                install_dependencies=True,
                install_timeout=30,
            )
        self.assertIsNotNone(result)
        skipped = result.get("skipped_postinstall")
        self.assertIsNotNone(skipped)
        self.assertEqual(skipped["script"], "patch-package --error-on-fail")
        self.assertEqual(skipped["patches_dir"], "patches")
        self.assertEqual(skipped["patched_packages"], ["@scope/pkg", "react-filerobot-image-editor"])
        notes_text = "\n".join(result["notes"])
        self.assertIn("patch-package --error-on-fail", notes_text)
        self.assertIn("patches/", notes_text)
        self.assertIn("react-filerobot-image-editor", notes_text)
        self.assertIn("same SHA", notes_text)


if __name__ == "__main__":
    unittest.main()
