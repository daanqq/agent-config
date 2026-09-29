#!/usr/bin/env python3

import argparse
import json
import os
import re
import shlex
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


MR_PATH = re.compile(r"^/(?P<project>.+)/-/merge_requests/(?P<iid>[1-9][0-9]*)/?$")
TOKEN_NAMES = ("GITLAB_TOKEN", "GITLAB_ACCESS_TOKEN", "OAUTH_TOKEN", "EUTP_TOKEN")
TOKEN_ASSIGNMENT = re.compile(
    rf"^\s*(?:export\s+)?(?P<name>{'|'.join(TOKEN_NAMES)})=(?P<value>.+?)\s*$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load GitLab merge request branch context as JSON."
    )
    parser.add_argument("mr_url")
    return parser.parse_args()


def request_json(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "PRIVATE-TOKEN": token,
            "User-Agent": "claude-code-fix-gitlab-mr-conflicts",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
            context=ssl.create_default_context(),
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitLab API returned HTTP {error.code}: {message}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"GitLab API request failed: {error.reason}") from error


def load_token() -> str:
    for name in TOKEN_NAMES:
        if token := os.environ.get(name):
            return token

    zshrc = Path.home() / ".zshrc"
    try:
        lines = zshrc.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeError(f"Cannot read {zshrc}: {error}") from error

    assignments = {}
    for line in lines:
        match = TOKEN_ASSIGNMENT.fullmatch(line)
        if not match:
            continue
        try:
            values = shlex.split(match.group("value"), comments=True, posix=True)
        except ValueError as error:
            raise RuntimeError(f"Invalid token assignment in {zshrc}: {error}") from error
        if len(values) != 1 or not values[0]:
            raise RuntimeError(f"Invalid token assignment in {zshrc}")
        assignments[match.group("name")] = values[0]

    for name in TOKEN_NAMES:
        if token := assignments.get(name):
            return token

    raise RuntimeError(f"GitLab token is not set in the environment or {zshrc}")


def project_context(project: dict) -> dict:
    return {
        "id": project["id"],
        "name": project["name"],
        "path": project["path"],
        "path_with_namespace": project["path_with_namespace"],
        "ssh_url_to_repo": project["ssh_url_to_repo"],
        "http_url_to_repo": project["http_url_to_repo"],
        "web_url": project["web_url"],
    }


def main() -> int:
    args = parse_args()
    token = load_token()

    parsed = urllib.parse.urlparse(args.mr_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("MR URL must use HTTP or HTTPS")
    if parsed.query or parsed.fragment:
        raise RuntimeError("MR URL must not contain a query or fragment")

    match = MR_PATH.fullmatch(parsed.path)
    if not match:
        raise RuntimeError("URL does not match /<project>/-/merge_requests/<iid>")

    origin = f"{parsed.scheme}://{parsed.netloc}"
    api = f"{origin}/api/v4"
    project_path = urllib.parse.unquote(match.group("project"))
    project_id = urllib.parse.quote(project_path, safe="")
    iid = int(match.group("iid"))

    mr = request_json(f"{api}/projects/{project_id}/merge_requests/{iid}", token)
    source_project = request_json(f"{api}/projects/{mr['source_project_id']}", token)
    target_project = request_json(f"{api}/projects/{mr['target_project_id']}", token)

    result = {
        "gitlab_origin": origin,
        "api_url": api,
        "mr_url": mr["web_url"],
        "mr_iid": mr["iid"],
        "mr_id": mr["id"],
        "state": mr["state"],
        "draft": mr.get("draft", False),
        "source_branch": mr["source_branch"],
        "target_branch": mr["target_branch"],
        "sha": mr["sha"],
        "source_project": project_context(source_project),
        "target_project": project_context(target_project),
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
