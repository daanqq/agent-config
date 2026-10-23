import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "claude/hooks/reply-language.go"
HOOK_COMMAND = '"$HOME/.local/libexec/agent-config/reply-language"'

ENGLISH = ("The merge and the push both finished without conflicts, and the branch is now "
           "up to date with the remote. I checked the working tree afterwards and found "
           "nothing left to commit, so the task can be considered complete. Please let me "
           "know if you want me to open a merge request as the next step. ") * 2
RUSSIAN = ("Слияние и отправка завершились без конфликтов, ветка совпадает с удалённой. "
           "После этого я проверил рабочее дерево: коммитить больше нечего, задача выполнена. ") * 3
CODE = "```ts\n" + "const value = computeSomethingVeryLongName(argument);\n" * 20 + "```"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": block} if isinstance(block, str) else block for block in blocks]}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "На русском тоже бывает"}]}}


class ReplyLanguageHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="reply-language-test-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.hook = cls.directory / "reply-language"
        cls.build_env = {**os.environ, "CGO_ENABLED": "0", "GOTOOLCHAIN": "local",
                         "GOPROXY": "off", "GOSUMDB": "off"}
        subprocess.run(["go", "build", "-trimpath", "-o", str(cls.hook), str(SOURCE)],
                       env=cls.build_env, check=True, capture_output=True, text=True, timeout=120)

    def write_transcript(self, entries):
        path = self.directory / f"transcript-{len(list(self.directory.iterdir()))}.jsonl"
        path.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries))
        return path

    def invoke(self, entries=None, **overrides):
        payload = {"hook_event_name": "Stop", "session_id": "s1", "stop_hook_active": False,
                   "cwd": "/nonexistent"}
        if entries is not None:
            payload["transcript_path"] = str(self.write_transcript(entries))
        payload.update(overrides)
        return subprocess.run([str(self.hook)], input=json.dumps(payload),
                              text=True, capture_output=True, timeout=5)

    def assertBlocks(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        decision = json.loads(result.stdout)
        self.assertEqual(set(decision), {"decision", "reason"})
        self.assertEqual(decision["decision"], "block")
        self.assertIn("по-русски", decision["reason"])

    def assertPasses(self, result):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_english_reply_to_russian_user_blocks(self):
        self.assertBlocks(self.invoke([user("Сделай merge и push"), assistant(ENGLISH)]))

    def test_russian_reply_passes(self):
        self.assertPasses(self.invoke([user("Сделай merge и push"), assistant(RUSSIAN)]))

    def test_code_only_reply_passes(self):
        self.assertPasses(self.invoke([user("Покажи код"), assistant(CODE)]))

    def test_inline_code_urls_and_paths_are_ignored(self):
        noise = ("`" + "someIdentifierWithManyLetters " * 20 + "` "
                 + "https://example.com/" + "abcdefghij" * 30 + " "
                 + "/home/user/" + "directory/" * 30 + "file.ts")
        self.assertPasses(self.invoke([user("Где это?"), assistant("Вот: " + noise)]))
        self.assertPasses(self.invoke([user("Где это?"), assistant(noise)]))

    def test_short_reply_passes(self):
        self.assertPasses(self.invoke([user("Готово?"), assistant("Done. The push succeeded.")]))

    def test_one_russian_sentence_with_large_code_block_passes(self):
        reply = "Вот исправление.\n\n" + CODE + "\n\n" + ENGLISH
        self.assertPasses(self.invoke([user("Исправь"), assistant(reply)]))
        reply = "Вот исправление.\n\n" + CODE
        self.assertPasses(self.invoke([user("Исправь"), assistant(reply)]))

    def test_unclosed_fence_hides_the_rest(self):
        self.assertPasses(self.invoke([user("Исправь"), assistant("```\n" + ENGLISH)]))

    def test_english_prose_around_code_blocks_blocks(self):
        reply = ENGLISH + "\n" + CODE + "\n" + ENGLISH
        self.assertBlocks(self.invoke([user("Исправь"), assistant(reply)]))

    def test_english_user_message_passes(self):
        self.assertPasses(self.invoke([user("Please merge and push"), assistant(ENGLISH)]))

    def test_last_real_user_message_decides(self):
        self.assertPasses(self.invoke([user("Сделай push"), user("Now explain it"), assistant(ENGLISH)]))
        self.assertBlocks(self.invoke([user("Explain it"), user("А теперь по-русски"), assistant(ENGLISH)]))

    def test_system_inserts_are_not_user_messages(self):
        inserts = [
            {**user("Русский текст служебной вставки"), "isMeta": True},
            user("<system-reminder>Русский текст напоминания</system-reminder>"),
            user("<task-notification>Задача завершена</task-notification>"),
            user("<local-command-stdout>Готово</local-command-stdout>"),
            user("<command-name>/clear</command-name><command-message>clear</command-message>"),
            tool_result(),
            {**user("Русская сводка компакта"), "isCompactSummary": True},
            {**user("Русский вопрос субагента"), "isSidechain": True},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "<system-reminder>Привет</system-reminder>"}]}},
        ]
        for insert in inserts:
            with self.subTest(insert=insert):
                self.assertPasses(self.invoke([user("Merge it please"), insert, assistant(ENGLISH)]))
        self.assertBlocks(self.invoke([
            user("Сделай merge"), user("<system-reminder>English reminder</system-reminder>"),
            assistant(ENGLISH)]))

    def test_user_text_blocks_and_command_arguments_count(self):
        blocks = {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "<system-reminder>English</system-reminder>"},
            {"type": "text", "text": "Сделай push"}]}}
        self.assertBlocks(self.invoke([blocks, assistant(ENGLISH)]))
        command = user("<command-message>how</command-message><command-name>/how</command-name>"
                       "<command-args>как это работает</command-args>")
        self.assertBlocks(self.invoke([command, assistant(ENGLISH)]))

    def test_final_reply_is_text_after_last_tool_result(self):
        tool_use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}
        thinking = {"type": "thinking", "thinking": "Русские мысли " * 40}
        self.assertBlocks(self.invoke([
            user("Сделай push"), assistant(RUSSIAN, tool_use), tool_result(),
            assistant(thinking), assistant(ENGLISH)]))
        self.assertPasses(self.invoke([
            user("Сделай push"), assistant(ENGLISH, tool_use), tool_result(),
            assistant(thinking), assistant(RUSSIAN)]))

    def test_sidechain_assistant_text_is_ignored(self):
        sidechain = {**assistant(ENGLISH), "isSidechain": True}
        self.assertPasses(self.invoke([user("Сделай push"), assistant(RUSSIAN), sidechain]))

    def test_last_assistant_message_field_takes_precedence(self):
        self.assertBlocks(self.invoke([user("Сделай push")], last_assistant_message=ENGLISH))
        self.assertPasses(self.invoke([user("Сделай push"), assistant(ENGLISH)],
                                      last_assistant_message=RUSSIAN))

    def test_stop_hook_active_passes(self):
        self.assertPasses(self.invoke([user("Сделай push"), assistant(ENGLISH)], stop_hook_active=True))

    def test_broken_or_missing_transcript_passes(self):
        self.assertPasses(self.invoke(transcript_path=str(self.directory / "missing.jsonl")))
        self.assertPasses(self.invoke(transcript_path=str(self.directory)))
        self.assertPasses(self.invoke())
        broken = self.directory / "broken.jsonl"
        broken.write_text("not json\n{\n[]\n")
        self.assertPasses(self.invoke(transcript_path=str(broken)))
        empty = self.directory / "empty.jsonl"
        empty.write_text("")
        self.assertPasses(self.invoke(transcript_path=str(empty)))
        # Garbage lines are skipped; valid entries around them still count.
        mixed = self.directory / "mixed.jsonl"
        mixed.write_text("garbage\n" + json.dumps(user("Сделай push"), ensure_ascii=False) + "\n{\n"
                         + json.dumps(assistant(ENGLISH)) + "\ntruncated")
        self.assertBlocks(self.invoke(transcript_path=str(mixed)))

    def test_transcript_without_user_message_passes(self):
        self.assertPasses(self.invoke([assistant(ENGLISH)]))

    def test_hook_input_boundary(self):
        entries = [user("Сделай push"), assistant(ENGLISH)]
        for overrides in ({"hook_event_name": "SubagentStop"}, {"hook_event_name": "PreToolUse"},
                          {"hook_event_name": None}, {"stop_hook_active": "yes"},
                          {"transcript_path": 12}, {"transcript_path": ""},
                          {"last_assistant_message": 12}):
            with self.subTest(overrides=overrides):
                self.assertPasses(self.invoke(entries, **overrides))
        for payload in ("not json", "[]", "null", "{}", "{} {}", ""):
            result = subprocess.run([str(self.hook)], input=payload,
                                    text=True, capture_output=True, timeout=5)
            self.assertPasses(result)

    def test_settings_register_compiled_stop_hook(self):
        settings = json.loads((ROOT / "claude/settings.json").read_text())
        handlers = [handler for group in settings["hooks"]["Stop"] for handler in group["hooks"]]
        self.assertEqual(sum(handler["command"] == HOOK_COMMAND for handler in handlers), 1)

    def test_install_builds_native_hook_and_preserves_it_on_build_failure(self):
        with tempfile.TemporaryDirectory(prefix="reply-language-install-test-") as directory:
            home = Path(directory) / "home with spaces"
            home.mkdir()
            env = {**self.build_env, "GOCACHE": os.environ.get(
                "GOCACHE", str(Path.home() / ".cache/go-build")), "HOME": str(home)}
            command = ["make", "install-hooks", f"HOME={home}"]
            result = subprocess.run(command, cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            binary = home / ".local/libexec/agent-config/reply-language"
            self.assertTrue(os.access(binary, os.X_OK))
            before = binary.read_bytes()
            transcript = Path(directory) / "transcript.jsonl"
            transcript.write_text(json.dumps(user("Сделай push"), ensure_ascii=False) + "\n"
                                  + json.dumps(assistant(ENGLISH)) + "\n")
            result = subprocess.run(HOOK_COMMAND, shell=True, env=env, input=json.dumps({
                "hook_event_name": "Stop", "stop_hook_active": False,
                "transcript_path": str(transcript),
            }), capture_output=True, text=True, timeout=5)
            self.assertBlocks(result)
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
