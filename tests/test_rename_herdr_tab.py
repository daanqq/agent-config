import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
RENAME_TAB = ROOT / "common/skills/analyze-spacehub-task/scripts/rename-herdr-tab.py"


class RenameHerdrTabTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.calls = self.directory / "calls.json"
        fake_herdr = self.directory / "bin" / "herdr"
        fake_herdr.parent.mkdir()
        fake_herdr.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            f"open({str(self.calls)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        )
        fake_herdr.chmod(fake_herdr.stat().st_mode | stat.S_IXUSR)

    def rename(self, title: str, **environment: str) -> subprocess.CompletedProcess[str]:
        task_json = self.directory / "task.json"
        task_json.write_text(json.dumps({"issue": {"id": "T-123123", "title": title}}))
        env = {
            "PATH": f"{self.directory / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONDONTWRITEBYTECODE": "1",
            **environment,
        }
        return subprocess.run(
            [sys.executable, str(RENAME_TAB), str(task_json)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_renames_calling_tab_with_untrusted_title_as_argv(self):
        result = self.rename("Fix $(rm -rf ~) \"quotes\"\nnext", HERDR_ENV="1", HERDR_TAB_ID="w1:t2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.calls.read_text()),
            ["tab", "rename", "w1:t2", 'T-123123 Fix $(rm -rf ~) "quotes" next'],
        )

    def test_truncates_long_titles(self):
        result = self.rename("Очень длинный заголовок задачи, который не помещается в таб", HERDR_ENV="1", HERDR_TAB_ID="w1:t2")

        self.assertEqual(result.returncode, 0, result.stderr)
        label = json.loads(self.calls.read_text())[-1]
        self.assertEqual(len(label), 40)
        self.assertTrue(label.startswith("T-123123 Очень длинный"))
        self.assertTrue(label.endswith("…"))

    def test_skips_outside_herdr(self):
        result = self.rename("Title", HERDR_TAB_ID="w1:t2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped", result.stdout)
        self.assertFalse(self.calls.exists())

    def test_herdr_failure_is_a_warning(self):
        result = self.rename("Title", HERDR_ENV="1", HERDR_TAB_ID="w1:t2", PATH="/nonexistent")

        self.assertEqual(result.returncode, 0)
        self.assertIn("was not renamed", result.stderr)


if __name__ == "__main__":
    unittest.main()
