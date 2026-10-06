import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "mr_echat.py"
SPEC = importlib.util.spec_from_file_location("mr_echat", SCRIPT)
assert SPEC and SPEC.loader
mr_echat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mr_echat)


class MrEchatTests(unittest.TestCase):
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
                mr_echat.link(SimpleNamespace(repo=["/work/client", "/work/rest"]))

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


if __name__ == "__main__":
    unittest.main()
