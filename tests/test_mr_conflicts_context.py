import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "common/skills/fix-gitlab-mr-conflicts/scripts/mr_context.py"

# Fake glab: answers from a JSON map of endpoint -> response and logs every argv.
FAKE_GLAB = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys
    with open(os.environ["GLAB_LOG"], "a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\\n")
    responses = json.load(open(os.environ["GLAB_RESPONSES"]))
    endpoint = sys.argv[-1]
    if endpoint not in responses:
        print("404 Not Found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(responses[endpoint]))
    """
)


def project(project_id, path):
    return {
        "id": project_id,
        "name": path.split("/")[-1],
        "path": path.split("/")[-1],
        "path_with_namespace": path,
        "ssh_url_to_repo": f"git@git.example.test:{path}.git",
        "http_url_to_repo": f"https://git.example.test/{path}.git",
        "web_url": f"https://git.example.test/{path}",
        "extra": "dropped",
    }


MR = {
    "web_url": "https://git.example.test/tidy/tidy-client/-/merge_requests/2698",
    "iid": 2698,
    "id": 9001,
    "state": "opened",
    "source_branch": "feature/EUTP-173968",
    "target_branch": "master",
    "sha": "abc123",
    "source_project_id": 11,
    "target_project_id": 12,
}


class MrConflictsContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mr-context-test-")
        self.root = Path(self.temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        glab = bin_dir / "glab"
        glab.write_text(FAKE_GLAB.format(python=sys.executable))
        glab.chmod(0o755)
        self.log = self.root / "glab.log"
        self.responses = self.root / "responses.json"
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.root),
            "GLAB_LOG": str(self.log),
            "GLAB_RESPONSES": str(self.responses),
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, url, responses):
        self.responses.write_text(json.dumps(responses))
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), url],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_context_comes_from_glab_without_a_token(self):
        result = self.run_script(
            "https://git.example.test/tidy/tidy-client/-/merge_requests/2698",
            {
                "projects/tidy%2Ftidy-client/merge_requests/2698": MR,
                "projects/11": project(11, "fork/tidy-client"),
                "projects/12": project(12, "tidy/tidy-client"),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)
        self.assertEqual(context["gitlab_origin"], "https://git.example.test")
        self.assertEqual(context["api_url"], "https://git.example.test/api/v4")
        self.assertEqual(
            {key: context[key] for key in ("mr_iid", "mr_id", "state", "draft", "source_branch", "target_branch", "sha")},
            {"mr_iid": 2698, "mr_id": 9001, "state": "opened", "draft": False,
             "source_branch": "feature/EUTP-173968", "target_branch": "master", "sha": "abc123"},
        )
        self.assertEqual(context["source_project"]["path_with_namespace"], "fork/tidy-client")
        self.assertEqual(context["target_project"]["path_with_namespace"], "tidy/tidy-client")
        self.assertNotIn("extra", context["source_project"])
        self.assertEqual(
            self.calls(),
            [
                ["api", "--hostname", "git.example.test", "projects/tidy%2Ftidy-client/merge_requests/2698"],
                ["api", "--hostname", "git.example.test", "projects/11"],
                ["api", "--hostname", "git.example.test", "projects/12"],
            ],
        )

    def test_glab_failure_is_reported_with_its_message(self):
        result = self.run_script("https://git.example.test/tidy/tidy-client/-/merge_requests/1", {})
        self.assertEqual(result.returncode, 1)
        self.assertIn("glab api projects/tidy%2Ftidy-client/merge_requests/1 failed (exit 1): 404 Not Found", result.stderr)

    def test_invalid_url_does_not_call_glab(self):
        result = self.run_script("https://git.example.test/tidy/tidy-client/-/issues/1", {})
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_missing_glab_is_a_clear_error(self):
        self.env["PATH"] = "/usr/bin:/bin" if not Path("/usr/bin/glab").exists() else "/nonexistent"
        result = self.run_script("https://git.example.test/tidy/tidy-client/-/merge_requests/1", {})
        self.assertEqual(result.returncode, 1)
        self.assertIn("glab is not installed", result.stderr)


if __name__ == "__main__":
    unittest.main()
