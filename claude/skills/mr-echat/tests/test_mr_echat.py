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

    def test_title_not_required_with_user_title_or_no_pending_commit(self) -> None:
        for title, paths in (("fix supplied title", ["file.txt"]), (None, [])):
            with self.subTest(title=title):
                self.state["included_paths"] = paths
                with patch.object(mr_echat, "ask_model", return_value=(
                    "<description>Text.</description>"
                )) as ask:
                    result = self.generate(title)
                self.assertEqual(ask.call_count, 1)
                self.assertEqual(result["title"], f"{title} #T-1" if title else None)

    def test_semantically_empty_title_is_not_a_format_retry(self) -> None:
        with patch.object(mr_echat, "ask_model", return_value=(
            "<title>#T-1</title><description>Text.</description>"
        )) as ask:
            with self.assertRaisesRegex(mr_echat.WorkflowError, "commit title is empty"):
                self.generate()
        self.assertEqual(ask.call_count, 1)


if __name__ == "__main__":
    unittest.main()
