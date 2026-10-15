#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse


def glab_api(host: str, endpoint: str) -> Any:
    result = subprocess.run(
        ["glab", "api", "--hostname", host, endpoint],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print(result.stderr.strip() or "glab api failed", file=sys.stderr)
        raise SystemExit(result.returncode)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"glab api returned invalid JSON for {endpoint}: {error}") from error


def expect_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"Unexpected GitLab API schema: {context} must be an object")
    return value


def expect_non_empty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise SystemExit(
            f"Unexpected GitLab API schema: {context} must be a non-empty string"
        )
    return value


def parse_mr_url(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    marker = "/-/merge_requests/"
    if parsed.scheme not in {"http", "https"} or marker not in parsed.path:
        raise SystemExit("Expected a GitLab merge request URL")

    project_path, iid_part = parsed.path.strip("/").split(marker, 1)
    try:
        iid = int(iid_part.split("/", 1)[0])
    except ValueError as error:
        raise SystemExit("Merge request IID is not a number") from error

    return parsed.hostname or "", project_path, iid


def fetch_discussions(host: str, project_id: str, iid: int) -> list[dict[str, Any]]:
    discussions: list[dict[str, Any]] = []
    page = 1

    while True:
        batch = glab_api(
            host,
            f"projects/{project_id}/merge_requests/{iid}/discussions"
            f"?per_page=100&page={page}",
        )
        if not isinstance(batch, list) or not all(
            isinstance(discussion, dict) for discussion in batch
        ):
            raise SystemExit(
                "Unexpected GitLab API schema: discussions page must be a list of objects"
            )
        discussions.extend(batch)
        if len(batch) < 100:
            return discussions
        page += 1


def is_resolved(notes: list[dict[str, Any]]) -> bool:
    resolvable = [note for note in notes if note.get("resolvable")]
    return bool(resolvable) and all(note.get("resolved") for note in resolvable)


def normalize_discussion(
    discussion: dict[str, Any], mr_url: str
) -> dict[str, Any] | None:
    notes = [note for note in discussion.get("notes", []) if not note.get("system")]
    if not notes or is_resolved(notes):
        return None

    root = notes[0]
    position = root.get("position") or {}
    path = position.get("new_path") or position.get("old_path")
    line = position.get("new_line") or position.get("old_line")

    return {
        "discussion_id": discussion.get("id"),
        "individual_note": discussion.get("individual_note", False),
        "path": path,
        "line": line,
        "note_url": f"{mr_url}#note_{root.get('id')}",
        "notes": [
            {
                "id": note.get("id"),
                "author": (note.get("author") or {}).get("username"),
                "body": note.get("body", ""),
                "created_at": note.get("created_at"),
            }
            for note in notes
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch GitLab MR metadata and unresolved review discussions"
    )
    parser.add_argument("mr_url")
    parser.add_argument(
        "--output",
        type=Path,
        help="write validated JSON to this file and print a concise summary",
    )
    args = parser.parse_args()

    host, project_path, iid = parse_mr_url(args.mr_url)
    project_id = quote(project_path, safe="")
    mr = expect_dict(
        glab_api(host, f"projects/{project_id}/merge_requests/{iid}"),
        "merge request",
    )
    web_url = expect_non_empty_string(mr.get("web_url"), "merge request web_url")
    source_branch = expect_non_empty_string(
        mr.get("source_branch"), "merge request source_branch"
    )
    target_branch = expect_non_empty_string(
        mr.get("target_branch"), "merge request target_branch"
    )
    sha = expect_non_empty_string(mr.get("sha"), "merge request sha")
    diff_refs = expect_dict(mr.get("diff_refs"), "merge request diff_refs")
    for field in ("base_sha", "head_sha", "start_sha"):
        expect_non_empty_string(diff_refs.get(field), f"merge request diff_refs.{field}")

    discussions = fetch_discussions(host, project_id, iid)

    unresolved = []
    for discussion in discussions:
        normalized = normalize_discussion(discussion, web_url)
        if normalized:
            unresolved.append(normalized)

    output = {
        "host": host,
        "project_path": project_path,
        "repo_name": project_path.rsplit("/", 1)[-1],
        "iid": iid,
        "title": mr.get("title"),
        "state": mr.get("state"),
        "source_branch": source_branch,
        "target_branch": target_branch,
        "web_url": web_url,
        "sha": sha,
        "diff_refs": diff_refs,
        "unresolved_discussions": unresolved,
    }
    serialized = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
        print(
            f"MR !{iid}: {source_branch} -> {target_branch} @ {sha}; "
            f"unresolved discussions: {len(unresolved)}; output: {args.output}"
        )
    else:
        sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
