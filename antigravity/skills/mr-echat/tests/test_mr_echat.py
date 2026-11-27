import importlib.util
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "mr_echat.py"
SPEC = importlib.util.spec_from_file_location("mr_echat", SCRIPT)
assert SPEC and SPEC.loader
mr_echat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mr_echat)


def _isolate_state_dir(case: unittest.TestCase) -> Path:
    state_dir = tempfile.TemporaryDirectory(prefix="mr-echat-state-")
    case.addCleanup(state_dir.cleanup)
    patcher = patch.dict(os.environ, {mr_echat.STATE_DIR_ENV: state_dir.name})
    patcher.start()
    case.addCleanup(patcher.stop)
    return Path(state_dir.name).resolve()


class MrEchatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_root = _isolate_state_dir(self)

    def test_extracts_normalized_task_id(self) -> None:
        self.assertEqual(mr_echat.task_id_for("feature/t-123"), "T-123")

    def test_rejects_branch_without_task(self) -> None:
        for branch in (
            "feature/no-task", "feature/J-123", "feature/J-T-123",
            "feature/T-123-T-124", "feature/T-12abc", "fix/T-123",
        ):
            with self.subTest(branch=branch), self.assertRaises(mr_echat.WorkflowError):
                mr_echat.task_id_for(branch)

    def test_task_title_normalization_replaces_old_suffix_once(self) -> None:
        self.assertEqual(
            mr_echat.normalized_title("fix rendering #EUTP-456 #T-999", "T-123"),
            "fix rendering #T-123",
        )

    def test_validates_exact_title_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            title = Path(directory) / "title.txt"
            title.write_text("fix message rendering #T-123\n", encoding="utf-8")
            self.assertEqual(
                mr_echat.validated_title(str(title), "T-123"),
                "fix message rendering #T-123",
            )
            title.write_text("fix message rendering #T-999\n", encoding="utf-8")
            with self.assertRaises(mr_echat.WorkflowError):
                mr_echat.validated_title(str(title), "T-123")

    def test_template_replaces_https_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            template = repo / ".gitlab" / "merge_request_templates" / "Default.md"
            template.parent.mkdir(parents=True)
            for placeholder in (
                "https://spacehub.esoft.tech/entity/T-…",
                "https://spacehub.esoft.tech/entity/T-",
                "https://spacehub.esoft.tech/entity/T-<ID>",
                "https://urs.esoft.tech/issue/EUTP-...",
                "https://youtrack.esoft.tech/issue/EUTP-",
            ):
                with self.subTest(placeholder=placeholder):
                    template.write_text(placeholder + "\nhttps://spacehub.esoft.tech/entity/T-999\n", encoding="utf-8")
                    self.assertEqual(
                        mr_echat.read_template(repo, "T-123"),
                        "https://spacehub.esoft.tech/entity/T-123\nhttps://spacehub.esoft.tech/entity/T-999\n",
                    )
            template.write_text("https://spacehub.esoft.tech/entity/T-UNKNOWN\n", encoding="utf-8")
            with self.assertRaisesRegex(mr_echat.WorkflowError, "unresolved task placeholder"):
                mr_echat.read_template(repo, "T-123")

    def test_decomposed_parent_selection_and_branch_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args], cwd=repo, check=True, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                ).stdout.strip()

            git("init", "-b", "master")
            git("config", "user.name", "Test User")
            git("config", "user.email", "test@example.com")
            (repo / "file.txt").write_text("base\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "base")
            git("update-ref", "refs/remotes/origin/master", "HEAD")
            git("switch", "-c", "feature/T-10")
            (repo / "file.txt").write_text("feature\n", encoding="utf-8")
            git("commit", "-am", "feature")
            parent_head = git("rev-parse", "HEAD")
            git("update-ref", "refs/remotes/origin/feature/T-10", "HEAD")
            git("switch", "master")

            with self.assertRaises(mr_echat.WorkflowError):
                mr_echat.select_branch(repo, "task/T-11", None)
            self.assertEqual(git("branch", "--show-current"), "master")
            self.assertEqual(mr_echat.select_branch(repo, "task/T-11", "feature/T-10"), "task/T-11")
            self.assertEqual(git("rev-parse", "HEAD"), parent_head)
            self.assertEqual(mr_echat.select_parent_task_branch(repo, "task/T-11"), "feature/T-10")
            self.assertIsNone(mr_echat.select_parent_task_branch(repo, "feature/T-11"))

            git("update-ref", "refs/remotes/origin/task/T-12", "HEAD")
            self.assertEqual(mr_echat.select_parent_task_branch(repo, "task/T-11"), "feature/T-10")
            git("update-ref", "refs/remotes/origin/feature/T-20", "HEAD")
            with self.assertRaisesRegex(mr_echat.WorkflowError, "ambiguous"):
                mr_echat.select_parent_task_branch(repo, "task/T-11")

    def test_detached_head_attaches_to_the_branch_it_extends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            other = Path(directory) / "other"
            repo.mkdir()

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args], cwd=repo, check=True, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                ).stdout.strip()

            git("init", "-b", "master")
            git("config", "user.name", "Test User")
            git("config", "user.email", "test@example.com")
            (repo / "file.txt").write_text("base\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            git("switch", "-c", "feature/T-10")
            (repo / "file.txt").write_text("feature\n", encoding="utf-8")
            git("commit", "-am", "feature")
            git("update-ref", "refs/remotes/origin/feature/T-10", "HEAD")

            git("switch", "--detach", base)
            with self.assertRaisesRegex(mr_echat.WorkflowError, "does not contain"):
                mr_echat.select_branch(repo, "feature/T-10", None)
            with self.assertRaisesRegex(mr_echat.WorkflowError, "pass --branch"):
                mr_echat.select_branch(repo, None, None)

            git("switch", "--detach", "feature/T-10")
            git("commit", "--allow-empty", "-m", "merge master")
            merged = git("rev-parse", "HEAD")
            git("worktree", "add", str(other), "feature/T-10")
            with self.assertRaisesRegex(mr_echat.WorkflowError, "another worktree"):
                mr_echat.select_branch(repo, "feature/T-10", None)
            git("worktree", "remove", str(other))

            (repo / "file.txt").write_text("uncommitted\n", encoding="utf-8")
            self.assertEqual(mr_echat.select_branch(repo, "feature/T-10", None), "feature/T-10")
            self.assertEqual(git("branch", "--show-current"), "feature/T-10")
            self.assertEqual(git("rev-parse", "HEAD"), merged)
            self.assertEqual((repo / "file.txt").read_text(encoding="utf-8"), "uncommitted\n")

    def test_prepare_task_does_not_fall_back_to_integration_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            workspace = repo / "workspace"
            workspace.mkdir()
            with (
                patch.object(mr_echat, "resolve_repo", return_value=repo),
                patch.object(mr_echat, "select_branch", return_value="task/T-11"),
                patch.object(mr_echat, "changed_paths", return_value=["file.txt"]),
                patch.object(mr_echat, "git", return_value=SimpleNamespace(stdout=b"")),
                patch.object(mr_echat, "existing_mr", return_value=None),
                patch.object(mr_echat, "select_parent_task_branch", return_value=None),
                patch.object(mr_echat.tempfile, "mkdtemp", return_value=str(workspace)),
                patch.object(mr_echat, "default_target_branch", return_value="master") as default_target,
            ):
                with self.assertRaisesRegex(mr_echat.WorkflowError, "parent feature"):
                    mr_echat.prepare(SimpleNamespace(repo=str(repo), branch=None, target_branch=None))
                default_target.assert_not_called()

    def test_excludes_generated_paths_only_from_model_diff(self) -> None:
        self.assertTrue(mr_echat.is_model_excluded("frontend/package-lock.json"))
        self.assertTrue(mr_echat.is_model_excluded("src/generated/client.ts"))
        self.assertFalse(mr_echat.is_model_excluded("src/client.ts"))

    def test_default_target_prefers_origin_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory) / "remote.git"
            repo = Path(directory) / "repo"
            subprocess.run(["git", "init", "--bare", "--initial-branch=main", remote], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "clone", str(remote), str(repo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            (repo / "file.txt").write_text("content\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "remote", "set-head", "origin", "main"], cwd=repo, check=True)
            self.assertEqual(mr_echat.default_target_branch(repo), "main")

    def test_prepare_includes_untracked_files_when_index_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            def git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.DEVNULL)

            git("init", "-b", "master")
            git("config", "user.name", "Test User")
            git("config", "user.email", "test@example.com")
            (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
            template = repo / ".gitlab" / "merge_request_templates" / "Default.md"
            template.parent.mkdir(parents=True)
            template.write_text("http://spacehub.esoft.tech/entity/T-…\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "initial")
            git("switch", "-c", "feature/T-123")
            (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
            (repo / "new.txt").write_text("new\n", encoding="utf-8")

            with patch.object(mr_echat, "existing_mr", return_value=None):
                result = mr_echat.prepare(SimpleNamespace(repo=str(repo), branch=None, target_branch=None))
            try:
                self.assertEqual(result["scope"], "all")
                self.assertEqual(result["included_paths"], ["new.txt", "tracked.txt"])
                model_diff = Path(result["model_diff_path"]).read_text(encoding="utf-8")
                self.assertIn("tracked.txt", model_diff)
                self.assertIn("new.txt", model_diff)
            finally:
                shutil.rmtree(result["workspace"])

    def test_prepare_commit_and_push_reaches_the_remote_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            repo = root / "repo"
            subprocess.run(["git", "init", "--bare", "--initial-branch=master", remote], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "clone", str(remote), str(repo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            template = repo / ".gitlab" / "merge_request_templates" / "Default.md"
            template.parent.mkdir(parents=True)
            template.write_text("https://spacehub.esoft.tech/entity/T-…\n", encoding="utf-8")
            (repo / "file.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "push", "-u", "origin", "master"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "switch", "-c", "feature/T-123"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
            (repo / "file.txt").write_text("after\n", encoding="utf-8")

            with patch.object(mr_echat, "existing_mr", return_value=None):
                prepared = mr_echat.prepare(SimpleNamespace(repo=str(repo), branch=None, target_branch=None))
            try:
                title = Path(prepared["workspace"]) / "title.txt"
                title.write_text("fix test workflow #T-123\n", encoding="utf-8")
                committed = mr_echat.commit(SimpleNamespace(state=prepared["state_path"], title_file=str(title)))
                pushed = mr_echat.push(SimpleNamespace(state=prepared["state_path"], force_with_lease=False))
                remote_sha = subprocess.run(
                    ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/feature/T-123"],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout.strip()
                self.assertEqual(committed["commit"], remote_sha)
                self.assertEqual(pushed["status"], "pushed")
            finally:
                shutil.rmtree(prepared["workspace"])

    def test_generate_and_ship_publish_model_texts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            repo = root / "repo"

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args], cwd=repo, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                ).stdout.strip()

            subprocess.run(["git", "init", "--bare", "--initial-branch=master", remote], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "clone", str(remote), str(repo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            git("config", "user.name", "Test User")
            git("config", "user.email", "test@example.com")
            template = repo / ".gitlab" / "merge_request_templates" / "Default.md"
            template.parent.mkdir(parents=True)
            template.write_text("https://spacehub.esoft.tech/entity/T-…\n", encoding="utf-8")
            (repo / "file.txt").write_text("before\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "initial")
            git("push", "-u", "origin", "master")
            git("switch", "-c", "feature/T-123")
            (repo / "committed.txt").write_text("committed change\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "add committed file #T-123")
            (repo / "file.txt").write_text("pending change\n", encoding="utf-8")

            with patch.object(mr_echat, "existing_mr", return_value=None):
                prepared = mr_echat.prepare(SimpleNamespace(repo=str(repo), branch=None, target_branch=None))
            workspace = Path(prepared["workspace"])
            try:
                notes = workspace / "notes.md"
                notes.write_text("Ran unit tests: passed.\n", encoding="utf-8")
                answer = "<title>fix pending file #T-123</title>\n<description>\n### Описание\n\nТекст.\n</description>\n"
                with patch.object(mr_echat, "ask_model", return_value=answer) as ask_model:
                    generated = mr_echat.generate(
                        SimpleNamespace(state=prepared["state_path"], notes_file=str(notes), title=None)
                    )
                prompt = ask_model.call_args.args[0]
                self.assertIn("committed change", prompt)
                self.assertIn("pending change", prompt)
                self.assertIn("https://spacehub.esoft.tech/entity/T-123", prompt)
                self.assertIn("Ran unit tests: passed.", prompt)
                self.assertEqual(generated["title"], "fix pending file #T-123")

                glab_calls: list[tuple[str, ...]] = []

                def fake_glab(_repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
                    glab_calls.append(args)
                    return subprocess.CompletedProcess(args, 0, stdout="https://gitlab.example/mr/1\n", stderr="")

                with patch.object(mr_echat, "existing_mr", return_value=None), patch.object(mr_echat, "glab", fake_glab):
                    shipped = mr_echat.ship(SimpleNamespace(state=prepared["state_path"], force_with_lease=False))
                remote_sha = subprocess.run(
                    ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/feature/T-123"],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout.strip()
                self.assertEqual(shipped["status"], "created")
                self.assertEqual(shipped["commit"], remote_sha)
                self.assertEqual(git("log", "-1", "--format=%s"), "fix pending file #T-123")
                create = next(call for call in glab_calls if call[:2] == ("mr", "create"))
                self.assertEqual(create[create.index("--title") + 1], "fix pending file #T-123")
                self.assertEqual(create[create.index("--description") + 1], "### Описание\n\nТекст.")
                self.assertFalse(workspace.exists())
            finally:
                shutil.rmtree(workspace, ignore_errors=True)

    def test_link_rewrites_only_the_related_block(self) -> None:
        mrs = {
            "client": {"ref": "2708", "url": "https://gitlab.example/echat/tidy-client/-/merge_requests/2708"},
            "rest": {"ref": "1987", "url": "https://gitlab.example/echat/tidy-rest/-/merge_requests/1987"},
        }
        descriptions = {
            "2708": "Клиент.\n\n<!-- mr-echat:related -->\nСвязанные MR: старая ссылка.\n<!-- /mr-echat:related -->\n",
            "1987": "Сервер.",
        }

        def fake_glab(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("mr", "update"):
                descriptions[args[2]] = args[args.index("--description") + 1]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            patch.object(mr_echat, "resolve_repo", side_effect=Path),
            patch.object(mr_echat, "current_branch", return_value="feature/T-1"),
            patch.object(mr_echat, "existing_mr", side_effect=lambda repo, _: mrs[repo.name]),
            patch.object(mr_echat, "mr_description", side_effect=lambda _, ref: descriptions[ref]),
            patch.object(mr_echat, "glab", fake_glab),
        ):
            for _ in range(2):
                mr_echat.link(SimpleNamespace(repo=["/work/client", "/work/rest"], dry_run=False))

        self.assertEqual(
            descriptions["2708"],
            "Клиент.\n\n<!-- mr-echat:related -->\n"
            f"Связанные MR: [tidy-rest!1987]({mrs['rest']['url']}).\n<!-- /mr-echat:related -->",
        )
        self.assertEqual(
            descriptions["1987"],
            "Сервер.\n\n<!-- mr-echat:related -->\n"
            f"Связанные MR: [tidy-client!2708]({mrs['client']['url']}).\n<!-- /mr-echat:related -->",
        )

    def test_link_dry_run_lists_merge_requests_without_updating(self) -> None:
        mrs = {
            "client": {"ref": "2708", "url": "https://gitlab.example/echat/tidy-client/-/merge_requests/2708"},
            "rest": {"ref": "1987", "url": "https://gitlab.example/echat/tidy-rest/-/merge_requests/1987"},
        }
        with (
            patch.object(mr_echat, "resolve_repo", side_effect=Path),
            patch.object(mr_echat, "current_branch", return_value="task/EUTP-1"),
            patch.object(mr_echat, "existing_mr", side_effect=lambda repo, _: mrs[repo.name]),
            patch.object(mr_echat, "glab") as glab,
        ):
            result = mr_echat.link(SimpleNamespace(repo=["/work/client", "/work/rest"], dry_run=True))

        self.assertEqual(result, {"status": "dry-run", "urls": [mrs["client"]["url"], mrs["rest"]["url"]]})
        glab.assert_not_called()

    def test_generate_keeps_related_block_out_of_the_prompt(self) -> None:
        block = "<!-- mr-echat:related -->\nСвязанные MR: [a!1](u).\n<!-- /mr-echat:related -->"
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "current-description.md").write_text(f"Старое.\n\n{block}\n", encoding="utf-8")
            state_path = workspace / "state.json"
            state = {"workspace": str(workspace), "task_id": "T-1", "included_paths": [], "existing_mr": {"ref": "1"}}
            with (
                patch.object(mr_echat, "load_state", return_value=(workspace, state)),
                patch.object(mr_echat, "ask_model", return_value="<description>Новое.</description>") as ask_model,
            ):
                generated = mr_echat.generate(SimpleNamespace(state=str(state_path), notes_file=None, title=None))
            self.assertNotIn("Связанные MR", ask_model.call_args.args[0])
            self.assertEqual(generated["description"], f"Новое.\n\n{block}")


class WorkspaceCwdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_root = _isolate_state_dir(self)
        self.workspace = Path(tempfile.mkdtemp(prefix="claude-mr-echat-t-1-", dir=self.state_root))
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        (self.workspace / "nested").mkdir()
        self.state_path = self.workspace / "state.json"
        self.state = {
            "workspace": str(self.workspace), "task_id": "T-1", "included_paths": ["a"],
            "description_path": str(self.workspace / "description.md"), "published": True,
        }
        patcher = patch.object(mr_echat, "load_state", return_value=(self.workspace, self.state))
        patcher.start()
        self.addCleanup(patcher.stop)
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)

    def test_ship_refuses_inside_the_workspace_before_any_write(self) -> None:
        for inside in (self.workspace, self.workspace / "nested"):
            os.chdir(inside)
            with self.subTest(cwd=inside), patch.object(mr_echat, "commit") as commit, patch.object(mr_echat, "push") as push:
                with self.assertRaisesRegex(mr_echat.WorkflowError, "inside the workspace"):
                    mr_echat.ship(SimpleNamespace(state=str(self.state_path), force_with_lease=False))
                commit.assert_not_called()
                push.assert_not_called()

    def test_cleanup_keeps_the_workspace_when_cwd_is_inside(self) -> None:
        os.chdir(self.workspace / "nested")
        with self.assertRaisesRegex(mr_echat.WorkflowError, "inside the workspace"):
            mr_echat.cleanup(SimpleNamespace(state=str(self.state_path)))
        self.assertTrue(self.workspace.exists())

    def test_cleanup_removes_the_workspace_from_another_directory(self) -> None:
        os.chdir("/")
        self.assertEqual(mr_echat.cleanup(SimpleNamespace(state=str(self.state_path)))["status"], "cleaned")
        self.assertFalse(self.workspace.exists())

    def test_cleanup_accepts_workspace_created_under_custom_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="custom-tmpdir-") as custom_tmp:
            previous_tempdir = tempfile.tempdir
            tempfile.tempdir = None
            try:
                with patch.dict(os.environ, {"TMPDIR": custom_tmp}):
                    workspace = Path(tempfile.mkdtemp(prefix="claude-mr-echat-t-99-", dir=self.state_root))
                    self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
                    state_path = workspace / "state.json"
                    state = {"workspace": str(workspace), "published": True}
                    with patch.object(mr_echat, "load_state", return_value=(workspace, state)):
                        os.chdir("/")
                        self.assertEqual(mr_echat.cleanup(SimpleNamespace(state=str(state_path)))["status"], "cleaned")
                        self.assertFalse(workspace.exists())

                    unowned = Path(tempfile.mkdtemp(prefix="claude-mr-echat-t-100-", dir=custom_tmp))
                    self.addCleanup(shutil.rmtree, unowned, ignore_errors=True)
                    unowned_state = {"workspace": str(unowned), "published": True}
                    with patch.object(mr_echat, "load_state", return_value=(unowned, unowned_state)):
                        with self.assertRaisesRegex(mr_echat.WorkflowError, "unowned workspace"):
                            mr_echat.cleanup(SimpleNamespace(state=str(unowned / "state.json")))
                        self.assertTrue(unowned.exists())
            finally:
                tempfile.tempdir = previous_tempdir


class PersistentWorkspaceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_root = _isolate_state_dir(self)

    def test_default_workspace_root_uses_private_home_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fake-home-") as fake_home:
            env = {k: v for k, v in os.environ.items() if k != mr_echat.STATE_DIR_ENV}
            with patch.dict(os.environ, env, clear=True), patch.object(Path, "home", return_value=Path(fake_home)):
                root = mr_echat.workspace_root(create=True)
                expected = (Path(fake_home) / ".cache" / "echat-mr-echat").resolve()
                self.assertEqual(root, expected)
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)

    def test_prepare_generate_and_ship_survives_tmpdir_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory) / "remote.git"
            repo = Path(directory) / "repo"
            tmp_a = Path(directory) / "tmp-a"
            tmp_b = Path(directory) / "tmp-b"
            tmp_a.mkdir()
            tmp_b.mkdir()
            subprocess.run(["git", "init", "--bare", "--initial-branch=master", remote], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "clone", str(remote), str(repo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args], cwd=repo, check=True, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                ).stdout.strip()

            git("config", "user.name", "Test User")
            git("config", "user.email", "test@example.com")
            template = repo / ".gitlab" / "merge_request_templates" / "Default.md"
            template.parent.mkdir(parents=True)
            template.write_text("### Описание\n\nhttps://spacehub.esoft.tech/entity/T-…\n", encoding="utf-8")
            (repo / "file.txt").write_text("base\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "initial")
            git("push", "-u", "origin", "master")
            git("switch", "-c", "feature/T-2346")
            (repo / "file.txt").write_text("approved change\n", encoding="utf-8")

            previous_tempdir = tempfile.tempdir
            tempfile.tempdir = None
            try:
                with patch.dict(os.environ, {"TMPDIR": str(tmp_a)}):
                    with patch.object(mr_echat, "existing_mr", return_value=None):
                        prepared = mr_echat.prepare(SimpleNamespace(repo=str(repo), branch=None, target_branch=None))
                workspace = Path(prepared["workspace"])
                self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
                self.assertEqual(workspace.parent, self.state_root)
                self.assertEqual(stat.S_IMODE(self.state_root.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(workspace.stat().st_mode), 0o700)

                answer = "<title>approved title #T-2346</title>\n<description>\n### Описание\n\nОдобренный текст.\n</description>\n"
                with patch.object(mr_echat, "ask_model", return_value=answer):
                    mr_echat.generate(SimpleNamespace(state=prepared["state_path"], notes_file=None, title=None))

                # Simulate T3 Code / Antigravity restart that deletes the old per-run TMPDIR.
                shutil.rmtree(tmp_a)
                tempfile.tempdir = None
                glab_calls: list[tuple[str, ...]] = []

                def fake_glab(_repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
                    glab_calls.append(args)
                    return subprocess.CompletedProcess(args, 0, stdout="https://gitlab.example/mr/2346\n", stderr="")

                with patch.dict(os.environ, {"TMPDIR": str(tmp_b)}):
                    with patch.object(mr_echat, "existing_mr", return_value=None), patch.object(mr_echat, "glab", fake_glab):
                        shipped = mr_echat.ship(SimpleNamespace(state=prepared["state_path"], force_with_lease=False))

                self.assertEqual(shipped["status"], "created")
                self.assertEqual(git("log", "-1", "--format=%s"), "approved title #T-2346")
                create = next(call for call in glab_calls if call[:2] == ("mr", "create"))
                self.assertEqual(create[create.index("--title") + 1], "approved title #T-2346")
                self.assertEqual(create[create.index("--description") + 1], "### Описание\n\nОдобренный текст.")
                self.assertFalse(workspace.exists())
            finally:
                tempfile.tempdir = previous_tempdir

    def test_prepare_prunes_stale_owned_workspaces_only(self) -> None:
        stale = self.state_root / "claude-mr-echat-t-old-abc"
        fresh = self.state_root / "claude-mr-echat-t-fresh-def"
        foreign = self.state_root / "other-dir"
        stray_file = self.state_root / "claude-mr-echat-file"
        external = tempfile.TemporaryDirectory(prefix="external-target-")
        self.addCleanup(external.cleanup)
        external_path = Path(external.name)
        symlink = self.state_root / "claude-mr-echat-t-link-ghi"

        for directory in (stale, fresh, foreign):
            directory.mkdir()
        (stale / "state.json").write_text("{}\n", encoding="utf-8")
        stray_file.write_text("keep\n", encoding="utf-8")
        symlink.symlink_to(external_path)

        old_ts = time.time() - mr_echat.STALE_WORKSPACE_MAX_AGE_SECONDS - 3600
        fresh_ts = time.time() - 3600
        os.utime(stale / "state.json", (old_ts, old_ts))
        os.utime(stale, (old_ts, old_ts))
        os.utime(foreign, (old_ts, old_ts))
        os.utime(stray_file, (old_ts, old_ts))
        os.utime(fresh, (fresh_ts, fresh_ts))

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            subprocess.run(["git", "init", "--initial-branch=master", repo], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            (repo / "file.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "switch", "-c", "feature/T-2347"], cwd=repo, check=True, stderr=subprocess.DEVNULL)
            (repo / "file.txt").write_text("change\n", encoding="utf-8")

            with patch.object(mr_echat, "existing_mr", return_value=None):
                prepared = mr_echat.prepare(SimpleNamespace(repo=str(repo), branch=None, target_branch=None))
            current = Path(prepared["workspace"])
            self.addCleanup(shutil.rmtree, current, ignore_errors=True)

            self.assertFalse(stale.exists())
            self.assertTrue(current.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(foreign.exists())
            self.assertTrue(stray_file.exists())
            self.assertTrue(symlink.is_symlink())
            self.assertTrue(external_path.exists())


class TaskChainTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_root = _isolate_state_dir(self)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.remote = root / "remote.git"
        self.repo = root / "repo"
        subprocess.run(["git", "init", "--bare", "--initial-branch=master", self.remote], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "clone", str(self.remote), str(self.repo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.com")
        template = self.repo / ".gitlab" / "merge_request_templates" / "Default.md"
        template.parent.mkdir(parents=True)
        template.write_text("https://spacehub.esoft.tech/entity/T-…\n", encoding="utf-8")
        self.commit_file("base.txt", "base")
        self.git("push", "-u", "origin", "master")
        # feature/T-10 <- task/T-11 <- task/T-12 <- task/T-13, one commit per branch.
        previous = "master"
        for branch in ("feature/T-10", "task/T-11", "task/T-12"):
            self.git("switch", "-c", branch, previous)
            self.commit_file(f"{branch.split('/')[1]}.txt", branch)
            self.git("push", "-u", "origin", branch)
            previous = branch
        self.git("switch", "-c", "task/T-13", "task/T-12")
        self.commit_file("T-13.txt", "task/T-13")
        (self.repo / "T-13-wip.txt").write_text("wip\n", encoding="utf-8")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()

    def commit_file(self, name: str, content: str) -> None:
        (self.repo / name).write_text(content + "\n", encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", content)

    def prepare(self, target: str | None, branch: str | None = None) -> dict:
        with patch.object(mr_echat, "existing_mr", return_value=None):
            return mr_echat.prepare(SimpleNamespace(repo=str(self.repo), branch=branch, target_branch=target))

    def branch_diff(self, prepared: dict) -> str:
        return Path(prepared["branch_diff_path"]).read_text(encoding="utf-8")

    def test_chain_links_target_the_previous_task_branch(self) -> None:
        for branch, target, own, others in (
            ("task/T-13", "task/T-12", "T-13.txt", ("T-12.txt", "T-11.txt", "feature")),
            ("task/T-12", "task/T-11", "T-12.txt", ("T-11.txt", "T-13.txt")),
        ):
            with self.subTest(branch=branch):
                self.git("switch", branch)
                prepared = self.prepare(target)
                try:
                    self.assertEqual(prepared["target_branch"], target)
                    self.assertTrue(Path(prepared["branch_diff_path"]).is_file())
                    diff = self.branch_diff(prepared)
                    self.assertIn(own, diff)
                    for other in others:
                        self.assertNotIn(other, diff)
                finally:
                    shutil.rmtree(prepared["workspace"])

    def test_chain_target_can_start_a_new_task_branch(self) -> None:
        self.git("stash", "-u")
        self.assertEqual(mr_echat.select_branch(self.repo, "task/T-14", "task/T-13"), "task/T-14")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "task/T-13"))

    def test_default_target_stays_the_parent_feature(self) -> None:
        self.git("switch", "task/T-11")
        (self.repo / "T-11-wip.txt").write_text("wip\n", encoding="utf-8")
        self.git("branch", "-D", "task/T-12", "task/T-13")
        self.git("push", "origin", "--delete", "task/T-12")
        prepared = self.prepare(None)
        try:
            self.assertEqual(prepared["target_branch"], "feature/T-10")
        finally:
            shutil.rmtree(prepared["workspace"])

    def test_other_targets_are_still_rejected(self) -> None:
        for target in ("master", "fix/T-12", "task/T-abc", "task/T-13", "task/T-12-extra"):
            with self.subTest(target=target), self.assertRaises(mr_echat.WorkflowError):
                self.prepare(target)
        with self.assertRaises(mr_echat.WorkflowError):
            mr_echat.select_branch(self.repo, "task/T-14", "master")


class GenerationFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="mr-format-test-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.state_path = self.workspace / "state.json"
        self.state_path.write_text("{}\n", encoding="utf-8")
        (self.workspace / "template.md").write_text("Template.\n", encoding="utf-8")
        self.state = {
            "workspace": str(self.workspace), "task_id": "T-1",
            "included_paths": ["file.txt"], "existing_mr": None,
        }
        for name, options in (
            ("load_state", {"return_value": (self.workspace, self.state)}),
            ("previous_title", {"return_value": None}),
        ):
            patcher = patch.object(mr_echat, name, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def generate(self, title: str | None = None):
        return mr_echat.generate(SimpleNamespace(
            state=str(self.state_path), notes_file=None, title=title,
        ))

    def test_valid_first_answer_needs_no_retry(self) -> None:
        with patch.object(mr_echat, "ask_model", return_value=(
            "<title>fix rendering</title><description>Text.</description>"
        )) as ask:
            result = self.generate()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(result["title"], "fix rendering #T-1")
        self.assertEqual(list(self.workspace.glob("generation-invalid-*.txt")), [])

    def test_bad_title_tag_is_archived_and_corrected_once(self) -> None:
        invalid = "<fix>fix rendering</fix><description>Text.</description>\n" + "x" * 700
        valid = "<title>fix rendering</title><description>Corrected.</description>"
        with patch.object(mr_echat, "ask_model", side_effect=[invalid, valid]) as ask:
            result = self.generate()
        self.assertEqual(ask.call_count, 2)
        self.assertIn("Missing or empty required blocks: <title>", ask.call_args.args[0])
        self.assertEqual(result["description"], "Corrected.")
        saved, = self.workspace.glob("generation-invalid-*.txt")
        self.assertEqual(saved.read_text(encoding="utf-8"), invalid)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(result["title_path"]).read_text(), "fix rendering #T-1\n")

    def test_empty_description_triggers_format_retry(self) -> None:
        with patch.object(mr_echat, "ask_model", side_effect=[
            "<title>fix rendering</title><description> </description>",
            "<title>fix rendering</title><description>Text.</description>",
        ]) as ask:
            self.generate()
        self.assertIn("Missing or empty required blocks: <description>", ask.call_args.args[0])
        self.assertEqual(ask.call_count, 2)

    def test_two_invalid_answers_stop_without_publishing_or_updating_state(self) -> None:
        answers = ["<fix>first</fix>", "<title>second</title>"]
        with (
            patch.object(mr_echat, "ask_model", side_effect=answers) as ask,
            patch.object(mr_echat, "git") as git,
            patch.object(mr_echat, "glab") as glab,
        ):
            with self.assertRaisesRegex(mr_echat.WorkflowError, "after one format retry") as error:
                self.generate()
        self.assertEqual(ask.call_count, 2)
        saved = list(self.workspace.glob("generation-invalid-*.txt"))
        self.assertEqual({p.read_text() for p in saved}, set(answers))
        for path in saved:
            self.assertIn(str(path), str(error.exception))
        self.assertEqual(self.state_path.read_text(), "{}\n")
        self.assertFalse((self.workspace / "title.txt").exists())
        self.assertFalse((self.workspace / "description.md").exists())
        git.assert_not_called()
        glab.assert_not_called()

    def test_non_format_errors_are_not_retried(self) -> None:
        for failure in (mr_echat.WorkflowError("authentication failed"), OSError("pi missing")):
            with self.subTest(failure=failure), patch.object(
                mr_echat, "ask_model", side_effect=failure,
            ) as ask:
                with self.assertRaises(type(failure)):
                    self.generate()
                self.assertEqual(ask.call_count, 1)
        self.assertEqual(list(self.workspace.glob("generation-invalid-*.txt")), [])

    def test_quota_exhaustion_falls_back_to_another_provider(self) -> None:
        quota = mr_echat.WorkflowError("pi --print --no-session failed: You have hit your ChatGPT usage limit.")
        with patch.object(mr_echat, "ask_model", side_effect=[
            quota, "<title>fix rendering</title><description>Text.</description>",
        ]) as ask:
            result = self.generate()
        self.assertEqual([c.args[2] for c in ask.call_args_list], [mr_echat.PI_MODEL, mr_echat.FALLBACK_MODEL])
        self.assertEqual(result["model"], mr_echat.FALLBACK_MODEL)
        self.assertFalse(mr_echat.FALLBACK_MODEL.startswith("openai-codex/"))

    def test_format_retry_after_fallback_stays_on_fallback(self) -> None:
        quota = mr_echat.WorkflowError("You have hit your ChatGPT usage limit.")
        with patch.object(mr_echat, "ask_model", side_effect=[
            quota, "<fix>wrong</fix>", "<title>fix rendering</title><description>Text.</description>",
        ]) as ask:
            result = self.generate()
        self.assertEqual([c.args[2] for c in ask.call_args_list],
                         [mr_echat.PI_MODEL, mr_echat.FALLBACK_MODEL, mr_echat.FALLBACK_MODEL])
        self.assertEqual(result["model"], mr_echat.FALLBACK_MODEL)

    def test_generate_warns_about_text_defects_outside_code(self) -> None:
        answer = (
            "<title>fix rendering</title><description>Исправлен рендер\u2014без эмоushen-стилей. "
            "Код `useЭмодзи` и ```\nconst a = 'x\u2014y'\n``` не проверяются.</description>"
        )
        with patch.object(mr_echat, "ask_model", return_value=answer):
            result = self.generate()
        warnings = result["warnings"]
        self.assertEqual(len(warnings), 2)
        self.assertIn("Em dash", warnings[0])
        self.assertIn("эмоushen", warnings[1])
        self.assertNotIn("useЭмодзи", warnings[1])

    def test_spaced_em_dash_becomes_hyphen_outside_code_only(self) -> None:
        answer = (
            "<title>fix rendering \u2014 again</title><description>Рендер \u2014 исправлен. Код `a \u2014 b` и\n"
            "```\nx \u2014 y\n```\nне меняются; слово\u2014слово остаётся.</description>"
        )
        with patch.object(mr_echat, "ask_model", return_value=answer):
            result = self.generate()
        self.assertEqual(result["title"], "fix rendering - again #T-1")
        self.assertEqual(
            result["description"],
            "Рендер - исправлен. Код `a \u2014 b` и\n```\nx \u2014 y\n```\nне меняются; слово\u2014слово остаётся.",
        )
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("Em dash", result["warnings"][0])
        self.assertEqual(Path(result["description_path"]).read_text(encoding="utf-8").count(" - "), 1)

    def test_em_dash_replacement_leaves_clean_text_without_warnings(self) -> None:
        with patch.object(mr_echat, "ask_model", return_value="<title>fix rendering</title><description>Исправлен \u2014 рендер.</description>"):
            result = self.generate()
        self.assertEqual(result["description"], "Исправлен - рендер.")
        self.assertEqual(result["warnings"], [])

    def test_update_prompt_carries_the_current_description_and_keep_rules(self) -> None:
        current = "### Что нужно проверить\n\n- `npm test`: 692 теста пройдены.\n\nПричина: старая."
        (self.workspace / "current-description.md").write_text(current, encoding="utf-8")
        (self.workspace / "branch.diff").write_text("net mr diff\n", encoding="utf-8")
        (self.workspace / "model.diff").write_text("pending commit diff\n", encoding="utf-8")
        self.state["existing_mr"] = {"ref": "1"}
        self.state["included_paths"] = []
        with patch.object(mr_echat, "ask_model", return_value="<description>Новое.</description>") as ask:
            self.generate()
        prompt = ask.call_args.args[0]
        self.assertIn(f"<current_description>\n{current}\n</current_description>", prompt)
        self.assertIn("<mr_diff>\nnet mr diff\n</mr_diff>", prompt)
        self.assertIn("<pending_diff>\n(none)\n</pending_diff>", prompt)
        self.assertIn("keep every check line of the current description", prompt)
        self.assertIn("keep the reason or cause of each earlier change", prompt)
        self.assertIn("branch-only detail was removed", prompt)
        self.assertIn("never needed", prompt)

    def test_prompt_omits_pending_diff_when_user_supplies_title(self) -> None:
        (self.workspace / "branch.diff").write_text("final mr diff\n", encoding="utf-8")
        (self.workspace / "model.diff").write_text("-mise exec\n+.nvmrc\n", encoding="utf-8")
        with patch.object(mr_echat, "ask_model", return_value="<description>Итог.</description>") as ask:
            self.generate("update docs")
        prompt = ask.call_args.args[0]
        self.assertIn("<mr_diff>\nfinal mr diff\n</mr_diff>", prompt)
        self.assertIn("<pending_diff>\n(none)\n</pending_diff>", prompt)
        self.assertNotIn("mise exec", prompt)

    def test_generate_clean_text_has_no_warnings(self) -> None:
        with patch.object(mr_echat, "ask_model", return_value="<title>fix rendering</title><description>Исправлен рендер T-4247 в emotion.</description>"):
            self.assertEqual(self.generate()["warnings"], [])

    def test_fallback_text_asks_to_check_against_notes(self) -> None:
        with patch.object(mr_echat, "ask_model", side_effect=[
            mr_echat.WorkflowError("usage limit"), "<title>fix rendering</title><description>Text.</description>",
        ]):
            warnings = self.generate()["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("notes.md", warnings[0])

    def test_fallback_failure_propagates_without_third_model(self) -> None:
        with patch.object(mr_echat, "ask_model", side_effect=[
            mr_echat.WorkflowError("usage limit"), mr_echat.WorkflowError("openrouter: 402 insufficient credits"),
        ]) as ask:
            with self.assertRaisesRegex(mr_echat.WorkflowError, "insufficient credits"):
                self.generate()
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(self.state_path.read_text(), "{}\n")

    def test_ask_model_passes_the_model_to_pi(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="out", stderr="")
        with patch.object(mr_echat, "run", return_value=completed) as run:
            mr_echat.ask_model("prompt", self.workspace, mr_echat.FALLBACK_MODEL)
        command = run.call_args.args[1]
        self.assertEqual(command[command.index("--model") + 1], mr_echat.FALLBACK_MODEL)
        self.assertIn("--no-tools", command)

    def test_retry_launch_failure_propagates_without_third_attempt(self) -> None:
        with patch.object(mr_echat, "ask_model", side_effect=[
            "<fix>wrong</fix>", mr_echat.WorkflowError("pi failed"),
        ]) as ask:
            with self.assertRaisesRegex(mr_echat.WorkflowError, "pi failed"):
                self.generate()
        self.assertEqual(ask.call_count, 2)
        saved, = self.workspace.glob("generation-invalid-*.txt")
        self.assertEqual(saved.read_text(), "<fix>wrong</fix>")
        self.assertEqual(self.state_path.read_text(), "{}\n")

    def test_title_not_required_with_user_title_or_existing_mr_without_pending_commit(self) -> None:
        (self.workspace / "current-description.md").write_text("Current.\n", encoding="utf-8")
        for title, paths, existing_mr in (
            ("fix supplied title", ["file.txt"], None),
            (None, [], {"ref": "1"}),
        ):
            with self.subTest(title=title, existing_mr=bool(existing_mr)):
                self.state["included_paths"] = paths
                self.state["existing_mr"] = existing_mr
                with patch.object(mr_echat, "ask_model", return_value=(
                    "<description>Text.</description>"
                )) as ask:
                    result = self.generate(title)
                self.assertEqual(ask.call_count, 1)
                self.assertEqual(result["title"], f"{title} #T-1" if title else None)

    def test_title_required_for_clean_committed_branch_without_mr(self) -> None:
        self.state["included_paths"] = []
        self.state["existing_mr"] = None
        with patch.object(mr_echat, "ask_model", return_value=(
            "<title>update agent docs</title><description>Text.</description>"
        )) as ask:
            result = self.generate()
        self.assertEqual(ask.call_count, 1)
        self.assertIn("<title_required>\nyes\n</title_required>", ask.call_args.args[0])
        self.assertEqual(result["title"], "update agent docs #T-1")
        self.assertTrue(Path(result["title_path"]).is_file())

    def test_generate_warns_when_fallback_template_was_used(self) -> None:
        self.state["template_fallback"] = True
        with patch.object(mr_echat, "ask_model", return_value="<title>fix docs</title><description>Text.</description>"):
            warnings = self.generate()["warnings"]
        self.assertIn(mr_echat.FALLBACK_TEMPLATE_WARNING, warnings)

    def test_semantically_empty_title_is_not_a_format_retry(self) -> None:
        with patch.object(mr_echat, "ask_model", return_value=(
            "<title>#T-1</title><description>Text.</description>"
        )) as ask:
            with self.assertRaisesRegex(mr_echat.WorkflowError, "commit title is empty"):
                self.generate()
        self.assertEqual(ask.call_count, 1)


class CommittedBranchAndFallbackTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state_root = _isolate_state_dir(self)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.remote = root / "remote.git"
        self.repo = root / "repo"
        subprocess.run(["git", "init", "--bare", "--initial-branch=main", self.remote], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "clone", str(self.remote), str(self.repo)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.com")
        self.commit_file("base.txt", "base")
        self.git("push", "-u", "origin", "main")
        self.git("switch", "-c", "feature/T-5509")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()

    def commit_file(self, name: str, content: str, message: str | None = None) -> str:
        (self.repo / name).write_text(content + "\n", encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", message or content)
        return self.git("rev-parse", "HEAD")

    def test_clean_committed_branch_without_mr_prepares_and_ships_without_new_commit(self) -> None:
        template = self.repo / ".gitlab" / "merge_request_templates" / "Default.md"
        template.parent.mkdir(parents=True)
        template.write_text("https://spacehub.esoft.tech/entity/T-…\n", encoding="utf-8")
        self.git("add", ".gitlab/merge_request_templates/Default.md")
        head_before = self.commit_file("AGENTS.md", "updated docs", "update docs #T-5509")
        index_before = self.git("write-tree")

        with patch.object(mr_echat, "existing_mr", return_value=None):
            prepared = mr_echat.prepare(SimpleNamespace(repo=str(self.repo), branch=None, target_branch=None))
        self.addCleanup(shutil.rmtree, prepared["workspace"], ignore_errors=True)

        self.assertEqual(prepared["scope"], "commits")
        self.assertEqual(prepared["included_paths"], [])
        self.assertEqual(prepared["target_branch"], "main")
        self.assertEqual(prepared["warnings"], [])
        self.assertIn("updated docs", Path(prepared["branch_diff_path"]).read_text(encoding="utf-8"))
        self.assertEqual(self.git("rev-parse", "HEAD"), head_before)
        self.assertEqual(self.git("write-tree"), index_before)

        with patch.object(mr_echat, "ask_model", return_value="<title>update docs</title><description>Обновлена документация.</description>"):
            generated = mr_echat.generate(SimpleNamespace(state=prepared["state_path"], notes_file=None, title=None))
        self.assertEqual(generated["title"], "update docs #T-5509")
        self.assertTrue(Path(generated["title_path"]).is_file())

        def fake_glab(_repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            if args[:2] == ("api", "user"):
                return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"username":"dev"}', stderr="")
            if args[:2] == ("mr", "create"):
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="https://gitlab.example.test/group/repo/-/merge_requests/42\n", stderr=""
                )
            raise AssertionError(f"unexpected glab call: {args}")

        with (
            patch.object(mr_echat, "existing_mr", side_effect=[None, {"ref": "42", "url": "https://gitlab.example.test/group/repo/-/merge_requests/42", "target_branch": "main"}]),
            patch.object(mr_echat, "glab", side_effect=fake_glab) as glab_mock,
            patch.object(mr_echat, "commit") as commit_mock,
        ):
            shipped = mr_echat.ship(SimpleNamespace(state=prepared["state_path"], force_with_lease=False))

        commit_mock.assert_not_called()
        self.assertEqual(shipped["status"], "created")
        self.assertEqual(shipped["commit"], head_before)
        self.assertEqual(shipped["committed_paths"], [])
        self.assertEqual(self.git("rev-parse", "HEAD"), head_before)
        self.assertEqual(self.git("write-tree"), index_before)
        create_calls = [call.args for call in glab_mock.call_args_list if call.args[1:3] == ("mr", "create")]
        self.assertEqual(len(create_calls), 1)
        self.assertIn("update docs #T-5509", create_calls[0])

    def test_clean_branch_with_no_commits_ahead_fails_and_preserves_head_and_index(self) -> None:
        head_before = self.git("rev-parse", "HEAD")
        index_before = self.git("write-tree")
        with patch.object(mr_echat, "existing_mr", return_value=None):
            with self.assertRaisesRegex(mr_echat.WorkflowError, "no changes to commit and no existing MR to update"):
                mr_echat.prepare(SimpleNamespace(repo=str(self.repo), branch=None, target_branch=None))
        self.assertEqual(self.git("rev-parse", "HEAD"), head_before)
        self.assertEqual(self.git("write-tree"), index_before)

    def test_missing_mr_template_uses_builtin_fallback_with_warning(self) -> None:
        self.commit_file("AGENTS.md", "desktop docs", "update desktop docs #T-5509")
        with patch.object(mr_echat, "existing_mr", return_value=None):
            prepared = mr_echat.prepare(SimpleNamespace(repo=str(self.repo), branch=None, target_branch=None))
        self.addCleanup(shutil.rmtree, prepared["workspace"], ignore_errors=True)

        self.assertTrue(prepared["template_fallback"])
        self.assertEqual(prepared["warnings"], [mr_echat.FALLBACK_TEMPLATE_WARNING])
        template_text = Path(prepared["template_path"]).read_text(encoding="utf-8")
        self.assertIn("https://spacehub.esoft.tech/entity/T-5509", template_text)
        self.assertIn("### Краткое описание изменений", template_text)

    def test_staged_followup_collapses_intermediate_branch_edits_in_mr_diff(self) -> None:
        self.commit_file("AGENTS.md", "run via mise exec", "add check commands #T-5509")
        (self.repo / "AGENTS.md").write_text("run with .nvmrc\n", encoding="utf-8")
        self.git("add", "AGENTS.md")
        (self.repo / "AGENTS.md").write_text("run with .nvmrc\nwip note\n", encoding="utf-8")

        with patch.object(mr_echat, "existing_mr", return_value=None):
            prepared = mr_echat.prepare(SimpleNamespace(repo=str(self.repo), branch=None, target_branch=None))
        self.addCleanup(shutil.rmtree, prepared["workspace"], ignore_errors=True)

        mr_diff = Path(prepared["branch_diff_path"]).read_text(encoding="utf-8")
        pending_diff = Path(prepared["model_diff_path"]).read_text(encoding="utf-8")
        self.assertIn("+run with .nvmrc", mr_diff)
        self.assertNotIn("mise exec", mr_diff)
        self.assertNotIn("wip note", mr_diff)
        self.assertIn("-run via mise exec", pending_diff)
        self.assertIn("+run with .nvmrc", pending_diff)

    def test_unstaged_followup_collapses_intermediate_branch_edits_in_mr_diff(self) -> None:
        self.commit_file("AGENTS.md", "run via mise exec", "add check commands #T-5509")
        (self.repo / "AGENTS.md").write_text("run with .nvmrc\n", encoding="utf-8")
        (self.repo / "extra.md").write_text("extra doc\n", encoding="utf-8")

        with patch.object(mr_echat, "existing_mr", return_value=None):
            prepared = mr_echat.prepare(SimpleNamespace(repo=str(self.repo), branch=None, target_branch=None))
        self.addCleanup(shutil.rmtree, prepared["workspace"], ignore_errors=True)

        mr_diff = Path(prepared["branch_diff_path"]).read_text(encoding="utf-8")
        self.assertIn("+run with .nvmrc", mr_diff)
        self.assertIn("+extra doc", mr_diff)
        self.assertNotIn("mise exec", mr_diff)


if __name__ == "__main__":
    unittest.main()
