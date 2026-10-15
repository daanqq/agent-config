import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).parents[1]
RUN_CHECK = ROOT / "common/skills/prove-it-works/scripts/run-check.py"


class RunCheckTests(unittest.TestCase):
    def run_check(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(RUN_CHECK), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def log_from(self, result: subprocess.CompletedProcess[str]) -> Path:
        match = re.search(r"^Log: (.+)$", result.stdout, re.MULTILINE)
        self.assertIsNotNone(match, result.stdout)
        assert match is not None
        return Path(match.group(1))

    def test_invalid_tail_is_a_diagnostic(self):
        result = self.run_check("--tail", "not-a-number", "--", sys.executable, "-c", "pass")

        self.assertEqual(result.returncode, 2)
        self.assertIn("non-negative integer", result.stderr)
        self.assertNotIn("Result: PASS", result.stdout)

    def test_help_succeeds_without_a_command_separator(self):
        result = self.run_check("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("usage:", result.stdout)

    def test_success_reports_status_and_private_log(self):
        result = self.run_check(
            "--",
            sys.executable,
            "-u",
            "-c",
            "print('stdout'); print('stderr', file=__import__('sys').stderr)",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Status: 0", result.stdout)
        self.assertIn("Result: PASS", result.stdout)
        log = self.log_from(result)
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(log.parent.stat().st_mode), 0o700)
        self.assertEqual(log.read_text(), "stdout\nstderr\n")

    def test_failure_keeps_status_and_complete_log(self):
        command = (
            "import sys; "
            "[print(f'line-{i}') for i in range(120)]; "
            "print('stderr-final', file=sys.stderr); sys.exit(7)"
        )
        result = self.run_check("--tail", "3", "--", sys.executable, "-u", "-c", command)

        self.assertEqual(result.returncode, 7)
        self.assertIn("Status: 7", result.stdout)
        self.assertIn("Result: FAIL", result.stdout)
        self.assertIn("line-119", result.stdout)
        self.assertIn("stderr-final", result.stdout)
        log = self.log_from(result)
        complete = log.read_text()
        self.assertIn("line-0\n", complete)
        self.assertIn("line-119\n", complete)
        self.assertIn("stderr-final\n", complete)
        self.assertGreater(len(complete.splitlines()), 100)

    def test_missing_log_does_not_replace_command_status(self):
        command = "import os,sys; os.unlink(os.readlink('/proc/self/fd/1')); sys.exit(7)"
        result = self.run_check("--", sys.executable, "-c", command)

        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("unable to read output log", result.stderr)
        log = self.log_from(result)
        self.assertFalse(log.exists())
        self.assertIn("Status: 7", result.stdout)

    @unittest.skipUnless(os.name == "posix" and Path("/dev/full").exists(), "requires Linux /dev/full")
    def test_report_flush_failure_does_not_replace_command_status(self):
        for expected_status in (0, 7):
            with self.subTest(expected_status=expected_status), open("/dev/full", "wb") as full:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(RUN_CHECK),
                        "--",
                        sys.executable,
                        "-c",
                        f"import sys; sys.exit({expected_status})",
                    ],
                    stdout=full,
                    stderr=subprocess.PIPE,
                    text=True,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    check=False,
                )

            self.assertEqual(result.returncode, expected_status, result.stderr)
            self.assertIn("unable to flush report output", result.stderr)
            self.assertIn("log", result.stderr)

    def test_broken_stdout_pipe_does_not_replace_command_status(self):
        runner = subprocess.Popen(
            [sys.executable, str(RUN_CHECK), "--", sys.executable, "-c", "import sys; sys.exit(7)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert runner.stdout is not None
        assert runner.stderr is not None
        runner.stdout.close()
        error = runner.stderr.read()
        runner.stderr.close()
        runner.wait(timeout=5)

        self.assertEqual(runner.returncode, 7, error)
        self.assertIn("unable to", error)

    def test_arguments_are_literal_and_paths_with_spaces_are_supported(self):
        with tempfile.TemporaryDirectory(prefix="run check ") as raw:
            child = Path(raw) / "child with spaces.py"
            child.write_text(
                "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            arguments = ["a;b", "$(not-expanded)", str(child), "two words"]
            result = self.run_check(
                "--",
                sys.executable,
                str(child),
                *arguments,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = self.log_from(result)
            self.assertEqual(json.loads(log.read_text()), arguments)

    def test_direct_child_signal_maps_to_shell_status(self):
        result = self.run_check(
            "--",
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
        )

        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertIn(f"Status: {128 + signal.SIGTERM}", result.stdout)
        self.assertIn("Result: FAIL", result.stdout)

    def test_runner_interruption_stays_nonzero_when_child_exits_zero(self):
        with tempfile.TemporaryDirectory() as raw:
            ready = Path(raw) / "ready"
            command = (
                "import signal, sys, time; "
                "signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
                "open(sys.argv[1], 'w').close(); "
                "time.sleep(30)"
            )
            runner = subprocess.Popen(
                [
                    sys.executable,
                    str(RUN_CHECK),
                    "--",
                    sys.executable,
                    "-u",
                    "-c",
                    command,
                    str(ready),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "child did not start")
                runner.send_signal(signal.SIGINT)
                output, error = runner.communicate(timeout=5)
            finally:
                if runner.poll() is None:
                    runner.send_signal(signal.SIGTERM)
                    runner.wait(timeout=5)

            self.assertEqual(runner.returncode, 130, error)
            self.assertIn("Status: 130", output)

    @unittest.skipUnless(os.name == "posix" and Path("/proc").exists(), "requires Linux process groups")
    def test_runner_signal_stops_background_descendant(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ready = root / "ready"
            command = 'sleep 30 & echo "$!" > "$1"; wait'
            runner = subprocess.Popen(
                [
                    sys.executable,
                    str(RUN_CHECK),
                    "--",
                    "sh",
                    "-c",
                    command,
                    "run-check-test",
                    str(ready),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            child_pid = None
            child_start_time = None
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "shell did not start")
                child_pid = int(ready.read_text())
                child_start_time = self._pid_start_time(child_pid)
                runner.send_signal(signal.SIGINT)
                output, error = runner.communicate(timeout=5)

                deadline = time.monotonic() + 3
                while self._pid_is_live(child_pid) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(self._pid_is_live(child_pid), "background descendant is still live")
            finally:
                if runner.poll() is None:
                    runner.send_signal(signal.SIGTERM)
                    try:
                        runner.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        runner.kill()
                        runner.wait()
                if (
                    child_pid is not None
                    and child_start_time is not None
                    and self._pid_start_time(child_pid) == child_start_time
                    and self._pid_is_live(child_pid)
                ):
                    os.kill(child_pid, signal.SIGKILL)

            self.assertEqual(runner.returncode, 130, error)
            self.assertIn("Status: 130", output)

    @staticmethod
    def _pid_start_time(pid: int) -> str | None:
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()
        except FileNotFoundError:
            return None
        return fields[19]

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()
        except FileNotFoundError:
            return False
        return fields[0] != "Z"

    def test_runner_signal_is_forwarded_to_child_group(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ready = root / "ready"
            stopped = root / "stopped"
            command = (
                "import os, signal, sys, time\n"
                "ready, stopped = sys.argv[1:]\n"
                "def stop(signum, frame):\n"
                "    open(stopped, 'w').close(); os._exit(128 + signum)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "signal.signal(signal.SIGINT, stop)\n"
                "open(ready, 'w').write(str(os.getpid()))\n"
                "while True: time.sleep(1)\n"
            )
            runner = subprocess.Popen(
                [
                    sys.executable,
                    str(RUN_CHECK),
                    "--",
                    sys.executable,
                    "-u",
                    "-c",
                    command,
                    str(ready),
                    str(stopped),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "child did not start")
                child_pid = int((root / "ready").read_text() or "0")
                runner.send_signal(signal.SIGTERM)
                output, error = runner.communicate(timeout=5)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if runner.poll() is None:
                    runner.send_signal(signal.SIGTERM)
                    try:
                        runner.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        runner.kill()
                        runner.wait()
                if child_pid is not None:
                    try:
                        os.killpg(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            self.assertEqual(runner.returncode, 128 + signal.SIGTERM, error)
            self.assertTrue(stopped.exists())
            self.assertIn(f"Status: {128 + signal.SIGTERM}", output)

    def test_start_error_is_failure_and_has_a_log(self):
        result = self.run_check("--", str(Path("does not exist")))

        self.assertEqual(result.returncode, 127)
        self.assertIn("unable to start command", result.stderr)
        log = self.log_from(result)
        self.assertIn("unable to start command", log.read_text())
        self.assertIn("Status: 127", result.stdout)
        self.assertIn("Result: FAIL", result.stdout)


if __name__ == "__main__":
    unittest.main()
