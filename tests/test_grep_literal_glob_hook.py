import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "claude/hooks/grep-literal-glob.go"
HOOK_COMMAND = '"$HOME/.local/libexec/agent-config/grep-literal-glob"'


class GrepLiteralGlobHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="grep-hook-test-")
        cls.addClassCleanup(temporary.cleanup)
        cls.hook = Path(temporary.name) / "grep-literal-glob"
        cls.build_env = {**os.environ, "CGO_ENABLED": "0", "GOTOOLCHAIN": "local",
                         "GOPROXY": "off", "GOSUMDB": "off"}
        subprocess.run(["go", "build", "-trimpath", "-o", str(cls.hook), str(SOURCE)],
                       env=cls.build_env, check=True, capture_output=True, text=True, timeout=120)

    def invoke(self, command=None, **overrides):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": command}, "cwd": "/nonexistent"}
        payload.update(overrides)
        return subprocess.run([str(self.hook)], input=json.dumps(payload),
                              text=True, capture_output=True, timeout=5)

    def check_commands(self, commands, blocked):
        for command in commands:
            with self.subTest(command=command):
                result = self.invoke(command)
                self.assertEqual(result.returncode, 2 if blocked else 0, result.stderr)
                self.assertEqual(result.stdout, "")
                if blocked:
                    self.assertIn("Quote", result.stderr)
                    self.assertIn("rg -g", result.stderr)
                else:
                    self.assertEqual(result.stderr, "")

    def test_literal_option_globs_block(self):
        self.check_commands([
            "grep -R --include=*.json foo .",
            "grep --exclude *.md foo .",
            "grep --include=foo?.tsx foo .",
            "grep --include=файл?.tsx foo .",
            "grep --include=😀*.json foo .",
            r"grep --include=\ud800*.json foo .",
            "grep --exclude=[ab].txt foo .",
            "grep --include='prefix'*.json foo .",
            "grep '--include='*.json foo .",
            "grep --exclude=\\**.md foo .",
            "cd /tmp && grep --include=*.tsx foo . | head; true",
            "echo ok; /usr/bin/grep --exclude=*.md foo .",
            "grep \\\n --include=*.json foo .",
            "grep --include=*.json foo . # comment",
            "grep --include foo#?.md foo .",
            "grep --include=*.md foo <<'EOF'\ntext\nEOF\n",
            "cat <<EOF\nignored\nEOF\ngrep --include=*.md foo .",
        ], True)

    def test_quotes_and_escapes_allow(self):
        self.check_commands([
            "grep --include='*.json' foo .",
            "grep --include='файл?.json' foo .",
            'grep --exclude "*.md" foo .',
            "grep '--include=*.json' foo .",
            "grep --include=\\*.json foo .",
            "grep --exclude=foo\\?.md foo .",
            "grep --include=\\[ab\\].txt foo .",
            "grep --include='['ab']'.txt foo .",
            "grep --include=\\*'?.json' foo .",
            "grep --include='a'\\*.json foo .",
            'grep --include="a\\\"*.json" foo .',
            'grep --include="a\\\\*.json" foo .',
            "grep --include='a\n*.json' foo .",
        ], False)

    def test_mentions_and_unrelated_globs_allow(self):
        self.check_commands([
            "echo grep --include=*.json",
            "printf '%s' 'grep --include=*.json'",
            'python3 -c "print(\'grep --include=*.json\')"',
            "python3 -c 'print(\"grep --include=*.json\")'",
            "# grep --include=*.json\necho ok",
            "echo ok # grep --include=*.json",
            "grep pattern *.json",
            "rg -g *.json foo",
            "grep --include=plain.json foo .",
            "grep --include=[abc foo .",
            "grep -- --include=*.json",
            "grep -e --include=*.json .",
            "grep --regexp --exclude=*.md .",
            "grep --file --include=*.json .",
            "grep -ne --include=*.json .",
            "grep foo > --include=*.json",
            "grep foo <<< 'grep --include=*.json'",
        ], False)

    def test_heredocs_are_opaque(self):
        self.check_commands([
            "python3 <<'PY'\ngrep --include=*.json\nPY\n",
            "cat <<EOF\ngrep --include=*.json\n$(grep --exclude=*.md)\nEOF\n",
            'cat <<"EOF" # header\ngrep --include=*.json\nEOF\n',
            "cat <<\\EOF\ngrep --include=*.json\nEOF\n",
            "cat <<'КОНЕЦ'\ngrep --include=*.json\nКОНЕЦ\n",
            "cat <<-EOF\n\tgrep --include=*.json\n\tEOF\n",
            "cat <<A <<'B'\ngrep --include=*.json\nA\ngrep --exclude=*.md\nB\n",
        ], False)
        self.check_commands([
            "cat <<A <<B\nignored\nA\nignored\nB\ngrep --include=*.json x",
        ], True)

    def test_unsupported_or_dynamic_input_fails_open(self):
        self.check_commands([
            "grep --include=$PATTERN*.md x",
            "grep --include=${PATTERN}*.md x",
            "echo $(grep --include=*.md x)",
            "echo `grep --include=*.md x`",
            "(grep --include=*.md x)",
            "sh -c 'grep --include=*.md x'",
            "env LC_ALL=C grep --include=*.md x",
            "grep --include='*.md x",
            "cat <<EOF\ngrep --include=*.md x\n",
        ], False)

    def test_hook_input_boundary(self):
        for overrides in ({"tool_name": "Read"}, {"hook_event_name": "PostToolUse"},
                          {"tool_input": None}, {"tool_input": []},
                          {"tool_input": {"command": 12}}):
            with self.subTest(overrides=overrides):
                result = self.invoke("grep --include=*.md x", **overrides)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        for payload in ("not json", "[]", "null", "{}", "{} {}",
                        '{"HOOK_EVENT_NAME":"PreToolUse","tool_name":"Bash",'
                        '"tool_input":{"command":"grep --include=*.md x"}}'):
            result = subprocess.run([str(self.hook)], input=payload,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_lone_surrogates_cannot_close_heredocs_early(self):
        self.check_commands([
            "cat <<'\ud800'\n\ufffd\ngrep --include=*.json x .\n\ud800\n",
            "cat <<'\ufffd'\n\ud800\ngrep --include=*.json x .\n\ufffd\n",
            "grep --include=\ud800*.json x .",
            "grep --include=\udc00*.json x .",
        ], False)

    def test_commands_are_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "must-not-exist"
            for command in (f"touch {target}; grep --include=*.md x",
                            f"touch {target}; grep --include='*.md' x"):
                self.invoke(command)
                self.assertFalse(target.exists())

    def test_settings_use_compiled_hook(self):
        settings = json.loads((ROOT / "claude/settings.json").read_text())
        handlers = [handler for group in settings["hooks"]["PreToolUse"]
                    if group["matcher"] == "Bash" for handler in group["hooks"]]
        self.assertEqual(sum(handler["command"] == HOOK_COMMAND for handler in handlers), 1)

    def test_install_builds_native_hook_and_preserves_it_on_build_failure(self):
        with tempfile.TemporaryDirectory(prefix="grep-install-test-") as directory:
            home = Path(directory) / "home with spaces"
            home.mkdir()
            env = {**self.build_env, "GOCACHE": os.environ.get(
                "GOCACHE", str(Path.home() / ".cache/go-build")), "HOME": str(home)}
            command = ["make", "install-hooks", f"HOME={home}"]
            result = subprocess.run(command, cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            binary = home / ".local/libexec/agent-config/grep-literal-glob"
            self.assertTrue(os.access(binary, os.X_OK))
            before = binary.read_bytes()
            result = subprocess.run(HOOK_COMMAND, shell=True, env=env, input=json.dumps({
                "hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": "grep --include=*.json x ."},
            }), capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            tools = Path(directory) / "tools"
            tools.mkdir()
            compiler = tools / "go"
            compiler.write_text("#!/bin/sh\necho 'fixture build failure' >&2\nexit 23\n")
            compiler.chmod(0o755)
            result = subprocess.run(command, cwd=ROOT,
                                    env={**env, "PATH": f"{tools}:{env['PATH']}"},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fixture build failure", result.stderr)
            self.assertEqual(binary.read_bytes(), before)
            self.assertEqual(list(binary.parent.glob(".*")), [])


if __name__ == "__main__":
    unittest.main()
