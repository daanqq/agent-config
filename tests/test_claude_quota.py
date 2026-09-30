import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "claude/statusline-quota-refresh.sh"


@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "Requires bash and jq")
class ClaudeQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="claude-quota-test-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        curl.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "assert args[args.index('-H') + 1] == 'Authorization: Bearer ' + os.environ['EXPECTED_KEY']\n"
            "assert args[-1].startswith(os.environ['EXPECTED_BASE'] + '/')\n"
            "with (Path(os.environ['HOME']) / 'requests.txt').open('a') as out:\n"
            "    out.write(args[-1].rsplit('/', 1)[-1] + '\\n')\n"
            "if args[-1].endswith('/auth-files'):\n"
            "    print(json.dumps({'files': [{'provider': 'claude', 'disabled': False, 'name': 'fixture', 'auth_index': '1'}]}))\n"
            "else:\n"
            "    assert args[-1].endswith('/api-call')\n"
            "    request = json.loads(args[args.index('-d') + 1])\n"
            "    assert request['header']['Authorization'] == 'Bearer $TOKEN$'\n"
            "    print(json.dumps({'status_code': 200, 'body': {'five_hour': {'utilization': 25, 'resets_at': '2099-01-01T00:00:00+00:00'}}}))\n",
            encoding="utf-8",
        )
        curl.chmod(0o755)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "CLIPROXY_MANAGEMENT_URL": "https://env.invalid",
            "CLIPROXY_MANAGEMENT_KEY": "fixture-env-key",
            "EXPECTED_BASE": "https://env.invalid/v0/management",
            "EXPECTED_KEY": "fixture-env-key",
        }

    def settings(self, content):
        path = self.home / ".pi/agent/secrets/cliproxy-management.json"
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")

    def run_refresh(self, expected_code=0):
        result = subprocess.run(
            ["bash", str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, expected_code, result.stderr)
        self.assertNotIn("fixture-env-key", result.stdout + result.stderr)
        self.assertNotIn("fixture-file-key", result.stdout + result.stderr)
        text = (self.home / ".cache/claude-statusline/quota.json").read_text()
        self.assertNotIn("fixture-env-key", text)
        self.assertNotIn("fixture-file-key", text)
        self.assertFalse((self.home / ".cache/claude-statusline/refresh.lock").exists())
        return json.loads(text)

    def assert_quota(self):
        cache = self.run_refresh()
        self.assertEqual(cache["totalAccounts"], 1)
        self.assertEqual(cache["accounts"][0]["windows"]["5h"]["remaining"], 75)
        self.assertEqual(cache["errors"], [])
        self.assertEqual((self.home / "requests.txt").read_text().splitlines(), ["auth-files", "api-call"])

    def test_reads_environment_when_file_is_absent(self):
        self.assert_quota()

    def test_file_overrides_environment_as_a_pair(self):
        self.settings(json.dumps({"managementUrl": "https://file.invalid/v0/management/", "managementKey": "fixture-file-key"}))
        self.env.update(EXPECTED_BASE="https://file.invalid/v0/management", EXPECTED_KEY="fixture-file-key")
        self.assert_quota()

    def test_incomplete_environment_fails_without_request(self):
        self.env.pop("CLIPROXY_MANAGEMENT_KEY")
        cache = self.run_refresh(expected_code=1)
        self.assertEqual(cache["errors"], ["Invalid CLIProxyAPI management settings"])
        self.assertFalse((self.home / "requests.txt").exists())

    def test_invalid_file_does_not_fall_back_to_environment(self):
        for content in ("not json", json.dumps({"managementUrl": "https://file.invalid"})):
            with self.subTest(content=content):
                path = self.home / ".pi/agent/secrets/cliproxy-management.json"
                if path.exists():
                    path.write_text(content, encoding="utf-8")
                else:
                    self.settings(content)
                cache = self.run_refresh(expected_code=1)
                self.assertEqual(cache["errors"], ["Invalid CLIProxyAPI management settings"])
                self.assertFalse((self.home / "requests.txt").exists())
                (self.home / ".cache/claude-statusline/quota.json").unlink()


if __name__ == "__main__":
    unittest.main()
