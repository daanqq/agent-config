from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "fetch_eutp.py"
SPEC = importlib.util.spec_from_file_location("fetch_eutp", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_eutp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_eutp)


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class ExtractIdTests(unittest.TestCase):
    def test_extracts_from_url_case_insensitively(self) -> None:
        value = "https://youtrack.esoft.tech/issue/eutp-12345/details"
        self.assertEqual(fetch_eutp.extract_eutp_id(value), "EUTP-12345")

    def test_allows_same_id_repeated_in_text(self) -> None:
        value = "Issue EUTP-42 mirrors https://host/issue/eutp-42"
        self.assertEqual(fetch_eutp.extract_eutp_id(value), "EUTP-42")

    def test_rejects_missing_id(self) -> None:
        with self.assertRaises(fetch_eutp.InputError):
            fetch_eutp.extract_eutp_id("EUTP-no-number")

    def test_rejects_multiple_distinct_ids(self) -> None:
        with self.assertRaises(fetch_eutp.InputError):
            fetch_eutp.extract_eutp_id("Compare EUTP-1 and EUTP-2")


class SessionTests(unittest.TestCase):
    def test_explicit_session_wins_over_environment(self) -> None:
        session = fetch_eutp.resolve_session(
            explicit="explicit-secret",
            session_file=None,
            from_stdin=False,
            environ={"PORA_SESSION": "environment-secret"},
        )
        self.assertEqual(session, "explicit-secret")

    def test_reads_session_from_file_without_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session"
            path.write_text("file-secret\n", encoding="utf-8")
            session = fetch_eutp.resolve_session(
                explicit=None,
                session_file=str(path),
                from_stdin=False,
                environ={},
            )
        self.assertEqual(session, "file-secret")

    def test_reads_session_from_stdin(self) -> None:
        session = fetch_eutp.resolve_session(
            explicit=None,
            session_file=None,
            from_stdin=True,
            environ={},
            stdin=io.StringIO("stdin-secret\n"),
        )
        self.assertEqual(session, "stdin-secret")

    def test_rejects_non_utf8_session_file_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session"
            path.write_bytes(b"\xff")
            with self.assertRaises(fetch_eutp.CredentialError):
                fetch_eutp.resolve_session(
                    explicit=None,
                    session_file=str(path),
                    from_stdin=False,
                    environ={},
                )

    def test_rejects_multiline_session(self) -> None:
        with self.assertRaises(fetch_eutp.CredentialError):
            fetch_eutp.resolve_session(
                explicit="first\nsecond",
                session_file=None,
                from_stdin=False,
                environ={},
            )


class FetchTests(unittest.TestCase):
    def test_fetch_uses_expected_url_cookie_and_timeout(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["cookie"] = request.get_header("Cookie")
            captured["timeout"] = timeout
            return FakeResponse(b'{"id":"EUTP-7","title":"Test"}')

        payload = fetch_eutp.fetch_issue(
            "EUTP-7",
            "top-secret",
            timeout=2.5,
            opener=opener,
        )

        self.assertEqual(payload["title"], "Test")
        self.assertEqual(
            captured["url"],
            "https://urs.esoft.tech/api/user/youtrack/v1/issues/EUTP-7",
        )
        self.assertEqual(captured["cookie"], "pora-gatekeeper-session=top-secret")
        self.assertEqual(captured["timeout"], 2.5)

    def test_rejects_non_json_response(self) -> None:
        with self.assertRaises(fetch_eutp.ResponseError):
            fetch_eutp.fetch_issue(
                "EUTP-7",
                "secret",
                opener=lambda request, timeout: FakeResponse(b"not-json"),
            )

    def test_rejects_wrong_issue_payload(self) -> None:
        body = json.dumps({"id": "EUTP-8", "title": "Wrong"}).encode()
        with self.assertRaises(fetch_eutp.ResponseError):
            fetch_eutp.fetch_issue(
                "EUTP-7",
                "secret",
                opener=lambda request, timeout: FakeResponse(body),
            )

    def test_rejects_json_error_object_without_issue_fields(self) -> None:
        body = json.dumps({"error": "unauthorized"}).encode()
        with self.assertRaises(fetch_eutp.ResponseError):
            fetch_eutp.fetch_issue(
                "EUTP-7",
                "secret",
                opener=lambda request, timeout: FakeResponse(body),
            )

    def test_reports_http_status_without_response_body(self) -> None:
        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        with self.assertRaisesRegex(fetch_eutp.FetchError, "HTTP 401"):
            fetch_eutp.fetch_issue("EUTP-7", "secret", opener=opener)

    def test_rejects_oversized_response(self) -> None:
        with self.assertRaises(fetch_eutp.ResponseError):
            fetch_eutp.fetch_issue(
                "EUTP-7",
                "secret",
                opener=lambda request, timeout: FakeResponse(b"{}", headers={"Content-Length": "3"}),
                max_response_bytes=2,
            )


class FormattingTests(unittest.TestCase):
    def sample_payload(self) -> dict:
        return {
            "id": "EUTP-99",
            "title": "Pipe | title",
            "state": {"name": "Open"},
            "assignee": {"fullName": "Иван Иванов"},
            "priority": "Major",
            "layer": "Backend",
            "class": "Feature",
            "sprints": [{"name": "Sprint 12"}],
            "estimation": 60,
            "spentTimeMinutes": 15,
            "teams": [{"name": "Platform"}],
            "type": {"name": "Task"},
            "links": {"parent": [{"id": "EUTP-1"}], "related": []},
            "textMd": "Описание задачи",
        }

    def test_normalizes_to_stable_schema(self) -> None:
        context = fetch_eutp.normalize_issue(
            self.sample_payload(), "EUTP-99", extra_context="Контекст пользователя"
        )

        self.assertEqual(context["schema_version"], 2)
        self.assertEqual(context["issue"]["assignee"], "Иван Иванов")
        self.assertEqual(context["issue"]["sprints"], ["Sprint 12"])
        self.assertEqual(context["issue"]["teams"], ["Platform"])
        self.assertEqual(context["issue"]["links"], {"parent": [{"id": "EUTP-1"}]})
        self.assertEqual(context["user_context"], "Контекст пользователя")

    def test_summarizes_large_link_lists_by_default(self) -> None:
        payload = self.sample_payload()
        payload["links"] = {
            "parent": [{"id": "EUTP-1"}],
            "childrens": [{"id": f"EUTP-{index}"} for index in range(25)],
        }

        context = fetch_eutp.normalize_issue(payload, "EUTP-99")

        self.assertEqual(
            context["issue"]["links"]["childrens"],
            {
                "count": 25,
                "sample": [f"EUTP-{index}" for index in range(20)],
                "truncated": True,
            },
        )
        self.assertEqual(context["issue"]["links"]["parent"], [{"id": "EUTP-1"}])
        markdown = fetch_eutp.render_markdown(context)
        self.assertIn('"count":25', markdown)
        self.assertNotIn("EUTP-24", markdown)

    def test_can_include_full_link_lists_explicitly(self) -> None:
        payload = self.sample_payload()
        children = [f"EUTP-{index}" for index in range(25)]
        payload["links"] = {"childrens": children}

        context = fetch_eutp.normalize_issue(payload, "EUTP-99", links_mode="full")

        self.assertEqual(context["issue"]["links"]["childrens"], children)

    def test_markdown_contains_summary_description_and_user_context(self) -> None:
        context = fetch_eutp.normalize_issue(
            self.sample_payload(), "EUTP-99", extra_context="Дополнительный контекст"
        )
        markdown = fetch_eutp.render_markdown(context)

        self.assertIn("## Задача EUTP-99: Pipe | title", markdown)
        self.assertIn("| Заголовок | Pipe \\| title |", markdown)
        self.assertIn("Описание задачи", markdown)
        self.assertIn("### Дополнительная информация пользователя", markdown)
        self.assertIn("Дополнительный контекст", markdown)

    def test_markdown_marks_missing_values(self) -> None:
        context = fetch_eutp.normalize_issue({"id": "EUTP-10"}, "EUTP-10")
        markdown = fetch_eutp.render_markdown(context)

        self.assertIn("| Статус | — |", markdown)
        self.assertIn("(описание отсутствует)", markdown)


if __name__ == "__main__":
    unittest.main()
