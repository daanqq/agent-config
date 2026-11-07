#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
import urllib.parse


MR_PATH = re.compile(r"^/(?P<project>.+)/-/merge_requests/(?P<iid>[1-9][0-9]*)/?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load GitLab merge request branch context as JSON."
    )
    parser.add_argument("mr_url")
    return parser.parse_args()


# glab keeps its own login; agent processes do not inherit the token exported by ~/.zshrc.
def gitlab_get(host: str, endpoint: str) -> dict:
    try:
        completed = subprocess.run(
            ["glab", "api", "--hostname", host, endpoint],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("glab is not installed or not in PATH") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"glab api {endpoint} timed out") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-500:]
        raise RuntimeError(f"glab api {endpoint} failed (exit {completed.returncode}): {detail}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"glab api {endpoint} returned non-JSON output") from error
    if not isinstance(data, dict):
        raise RuntimeError(f"glab api {endpoint} returned {type(data).__name__}, expected an object")
    return data


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

    host = parsed.netloc
    mr = gitlab_get(host, f"projects/{project_id}/merge_requests/{iid}")
    source_project = gitlab_get(host, f"projects/{mr['source_project_id']}")
    target_project = gitlab_get(host, f"projects/{mr['target_project_id']}")

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
