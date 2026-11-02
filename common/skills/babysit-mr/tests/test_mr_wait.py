import contextlib
import importlib.machinery
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mr-wait"
loader = importlib.machinery.SourceFileLoader("mr_wait", str(SCRIPT))
spec = importlib.util.spec_from_loader("mr_wait", loader)
mr_wait = importlib.util.module_from_spec(spec)
loader.exec_module(mr_wait)

PROJECT = "projects/tidy%2Ftidy-client"
MR = f"{PROJECT}/merge_requests/7"
HEAD = "a" * 40
URL = "https://git.example/tidy/tidy-client/-/merge_requests/7"


def mr(**overrides):
    data = {
        "state": "opened",
        "web_url": URL,
        "sha": HEAD,
        "source_branch": "feature/T-1",
        "target_branch": "master",
        "author": {"username": "me"},
        "has_conflicts": False,
        "head_pipeline": None,
    }
    data.update(overrides)
    return data


def pipeline(status, sha=HEAD):
    return {"id": 5, "sha": sha, "status": status, "web_url": "https://git.example/p/5"}


def job(name, status, allow_failure=False):
    return {"name": name, "status": status, "allow_failure": allow_failure, "web_url": f"https://git.example/j/{name}"}


def note(note_id, author, body="please fix", **extra):
    return {"id": note_id, "author": {"username": author}, "body": body, "system": False, **extra}


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, endpoint):
        self.calls.append(endpoint)
        path = endpoint.split("?", 1)[0]
        value = self.responses.get(path)
        if value is None:
            if path.endswith("/discussions") or path.endswith("/jobs") or path.endswith("/diffs"):
                return []
            raise mr_wait.ApiError(f"{endpoint}: 404", False)
        return value(endpoint) if callable(value) else value


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.responses = {
            "user": {"username": "me"},
            MR: mr(),
            f"{PROJECT}/repository/branches/master": {"commit": {"id": "b" * 40}},
        }
        self.api = FakeApi(self.responses)

    def watcher(self, until="pipeline", **kwargs):
        return mr_wait.Watcher(
            "git.example", "tidy/tidy-client", 7, self.api, until,
            state_dir=Path(self.tmp.name), now=self.clock, **kwargs,
        )

    def poll(self, watcher):
        out = io.StringIO()
        code = None
        with contextlib.redirect_stdout(out):
            try:
                watcher.poll()
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue()

    def test_manual_pipeline_is_final_and_passed(self):
        self.responses[MR] = mr(head_pipeline=pipeline("manual"))
        self.responses[f"{PROJECT}/pipelines/5/jobs"] = [job("lint", "success"), job("container_build", "manual")]
        code, out = self.poll(self.watcher())
        self.assertEqual(code, 0)
        self.assertIn("stopped at manual jobs (final status)", out)
        self.assertIn("manual jobs not started: container_build", out)

    def test_failed_pipeline_lists_blocking_jobs_only(self):
        self.responses[MR] = mr(head_pipeline=pipeline("failed"))
        self.responses[f"{PROJECT}/pipelines/5/jobs"] = [
            job("lint", "failed"), job("audit", "failed", allow_failure=True), job("build", "success"),
        ]
        code, out = self.poll(self.watcher())
        self.assertEqual(code, 1)
        self.assertIn("pipeline failed on aaaaaaaa: lint https://git.example/j/lint", out)
        self.assertNotIn("audit https://", out)
        self.assertIn("allowed to fail: audit", out)

    def test_pipeline_of_previous_head_is_not_the_result(self):
        self.responses[MR] = mr(head_pipeline=pipeline("success", sha="c" * 40))
        watcher = self.watcher(grace=600)
        code, out = self.poll(watcher)
        self.assertIsNone(code)
        self.assertEqual(out, "")
        self.clock.value += 600
        code, out = self.poll(watcher)
        self.assertEqual(code, 1)
        self.assertIn("no pipeline for head aaaaaaaa after 10 min", out)

    def test_running_pipeline_keeps_waiting(self):
        self.responses[MR] = mr(head_pipeline=pipeline("running"))
        code, out = self.poll(self.watcher())
        self.assertIsNone(code)
        self.assertEqual(out, "")

    def test_first_run_records_existing_comments_and_reports_new_ones(self):
        discussions = [{"notes": [note(1, "reviewer", resolvable=True, resolved=False)]}]
        self.responses[f"{MR}/discussions"] = discussions
        self.responses[MR] = mr(head_pipeline=pipeline("running"))
        watcher = self.watcher()
        self.assertEqual(self.poll(watcher), (None, ""))
        watcher.baseline = False
        discussions[0]["notes"].append(note(2, "me", "done"))
        discussions.append({"notes": [note(3, "reviewer", "why?", position={"new_path": "a.ts", "new_line": 4})]})
        discussions.append({"notes": [{"id": 4, "system": True, "author": {"username": "lead"}, "body": "approved this merge request"}]})
        code, out = self.poll(watcher)
        self.assertIsNone(code)
        self.assertNotIn("note_1", out)
        self.assertNotIn("note_2", out)
        self.assertIn(f"comment from reviewer on a.ts:4: why? {URL}#note_3", out)
        self.assertIn("lead approved this merge request", out)

    def test_restarted_watcher_does_not_repeat_reported_events(self):
        self.responses[f"{MR}/discussions"] = [{"notes": [note(1, "reviewer")]}]
        self.responses[MR] = mr(head_pipeline=pipeline("running"))
        first = self.watcher()
        first.baseline = False
        _, out = self.poll(first)
        self.assertIn("note_1", out)
        first.save()
        self.assertEqual(self.poll(self.watcher()), (None, ""))

    def test_any_change_exits_on_first_event(self):
        self.responses[f"{MR}/discussions"] = [{"notes": [note(1, "reviewer")]}]
        self.responses[MR] = mr(head_pipeline=pipeline("running"))
        watcher = self.watcher(until="any-change")
        watcher.baseline = False
        code, out = self.poll(watcher)
        self.assertEqual(code, 0)
        self.assertIn("note_1", out)

    def test_conflict_needs_action(self):
        self.responses[MR] = mr(has_conflicts=True, head_pipeline=pipeline("running"))
        code, out = self.poll(self.watcher())
        self.assertEqual(code, 1)
        self.assertIn("conflicts with master: merge master into feature/T-1", out)

    def test_target_move_touching_mr_files_is_reported(self):
        self.responses[MR] = mr(head_pipeline=pipeline("running"))
        self.responses[f"{MR}/diffs"] = [{"new_path": "src/a.ts", "old_path": "src/a.ts"}]
        watcher = self.watcher()
        self.poll(watcher)
        watcher.baseline = False
        self.responses[f"{PROJECT}/repository/branches/master"] = {"commit": {"id": "d" * 40}}
        self.responses[f"{PROJECT}/repository/compare"] = {"diffs": [{"new_path": "src/a.ts"}, {"new_path": "b.ts"}]}
        code, out = self.poll(watcher)
        self.assertIsNone(code)
        self.assertIn("master moved to dddddddd and touches files in this MR: src/a.ts", out)

    def test_merged_and_closed(self):
        self.responses[MR] = mr(state="merged")
        self.assertEqual(self.poll(self.watcher())[0], 0)
        self.responses[MR] = mr(state="closed")
        self.assertEqual(self.poll(self.watcher())[0], 1)

    def test_timeout_reports_last_status(self):
        self.responses[MR] = mr(head_pipeline=pipeline("running"))
        watcher = self.watcher(timeout=60)

        def sleep(_):
            self.clock.value += 60

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_:
                watcher.run(10, sleep)
        self.assertEqual(exit_.exception.code, 1)
        self.assertIn("timeout after 1 min: pipeline running on aaaaaaaa", out.getvalue())

    def test_unreachable_gitlab_stops_after_repeated_failures(self):
        def down(endpoint):
            raise mr_wait.ApiError(f"{endpoint}: HTTP 502", True)

        self.responses[MR] = down
        watcher = self.watcher(timeout=0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_:
                watcher.run(10, lambda _: None)
        self.assertEqual(exit_.exception.code, 1)
        self.assertIn("GitLab unreachable for 10 polls", out.getvalue())


class ParseTargetTest(unittest.TestCase):
    def test_accepts_mr_url_with_suffix(self):
        self.assertEqual(
            mr_wait.parse_target("https://git.example/group/sub/repo/-/merge_requests/12/diffs"),
            ("git.example", "group/sub/repo", 12),
        )

    def test_rejects_other_urls(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_:
            mr_wait.parse_target("https://git.example/group/repo/-/issues/3")
        self.assertEqual(exit_.exception.code, 2)


class LockTest(unittest.TestCase):
    def test_second_watcher_of_same_mr_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            handle = mr_wait.lock(Path(tmp), "key")
            self.addCleanup(handle.close)
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_:
                mr_wait.lock(Path(tmp), "key")
            self.assertEqual(exit_.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
