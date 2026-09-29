from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Sequence
import json
import os
import shlex
import sys

from .core import (
    ReviewError,
    cleanup_workspace,
    prepare_local,
    prepare_mr,
    resolve_repo_override,
)


DEFAULT_REPO_ROOT = Path(os.environ.get("ECHAT_REVIEW_REPOS_ROOT", "/home/user/echat/reviews"))
DEFAULT_WORKSPACE_ROOT = Path(os.environ.get("ECHAT_WORKSPACE_ROOT", "/home/user/echat"))
DEFAULT_OUTPUT_ROOT = Path(
    os.environ.get("MR_REVIEW_OUTPUT_ROOT", str(Path.home() / ".cache" / "echat-mr-review" / "jobs"))
)
DEFAULT_LOCK_ROOT = Path(
    os.environ.get("MR_REVIEW_LOCK_ROOT", str(Path.home() / ".cache" / "echat-mr-review" / "locks"))
)
DEFAULT_YOUTRACK_URL = "https://urs.esoft.tech/api/user/youtrack/v1/issues"


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="review_prepare.py",
        description="Prepare exact EChat review context for GitLab MRs or local Git changes.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="prepare review artifacts")
    kinds = prepare.add_subparsers(dest="kind", required=True)

    mr = kinds.add_parser("mr", help="fetch GitLab MR heads into isolated worktrees")
    mr.add_argument("urls", nargs="+", help="GitLab merge request URL(s)")
    mr.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT, help="directory containing reusable review clones")
    mr.add_argument("--repo", action="append", default=[], metavar="NAME=PATH", help="override a source clone by repo name or project path")
    mr.add_argument("--remote", default="origin", help="Git remote containing MR and target refs (default: origin)")
    mr.add_argument("--target", default="master", help="target branch fallback when metadata is unavailable")
    mr.add_argument("--gitlab-metadata-file", type=Path, help="offline/test JSON metadata object or keyed mapping")
    token_group = mr.add_mutually_exclusive_group()
    token_group.add_argument("--gitlab-token", help="GitLab token; prefer env/file because argv may be visible")
    token_group.add_argument("--gitlab-token-file", type=Path, help="read GitLab token from a file")
    mr.add_argument("--gitlab-token-env", default="GITLAB_TOKEN", help="token environment variable (default: GITLAB_TOKEN)")
    _add_common_prepare_options(mr)

    local = kinds.add_parser("local", help="prepare review context from local repositories")
    local.add_argument("repos", nargs="+", help="repository paths or names under --workspace-root")
    local.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT, help="base directory for bare repository names")
    local.add_argument("--base", help="base ref; auto-detects origin/master/main/stage/develop when omitted")
    local.add_argument("--scope", choices=("branch", "working-tree", "all"), default="all")
    _add_common_prepare_options(local)

    cleanup = commands.add_parser("cleanup", help="safely remove a generated workspace and its worktrees")
    cleanup.add_argument("workspace", type=Path, help="workspace directory or manifest.json")
    cleanup.add_argument("--dry-run", action="store_true", help="validate and print the cleanup plan without deleting")
    return parser


def _add_common_prepare_options(parser: ArgumentParser) -> None:
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help="parent directory for generated workspaces")
    parser.add_argument("--lock-root", type=Path, default=DEFAULT_LOCK_ROOT, help="directory for cross-process repository locks")
    parser.add_argument("--related-task", action="append", default=[], help="related EUTP task ID; repeatable")
    extra = parser.add_mutually_exclusive_group()
    extra.add_argument("--extra-info", default="", help="additional review/task context")
    extra.add_argument("--extra-info-file", type=Path, help="read additional context from a UTF-8 file")
    pora = parser.add_mutually_exclusive_group()
    pora.add_argument("--pora-session", help="PORA session; prefer env/file because argv may be visible")
    pora.add_argument("--pora-session-file", type=Path, help="read PORA session from a file")
    parser.add_argument("--pora-session-env", default="PORA_SESSION", help="session environment variable (default: PORA_SESSION)")
    parser.add_argument("--youtrack-base-url", default=DEFAULT_YOUTRACK_URL)
    parser.add_argument("--network-timeout", type=float, default=15, help="HTTP/glab timeout in seconds")
    parser.add_argument("--offline", action="store_true", help="disable GitLab API, glab, and YouTrack HTTP requests")


def _read_optional_file(path: Path | None, label: str) -> str | None:
    if path is None:
        return None
    try:
        return path.expanduser().read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ReviewError(f"Cannot read {label} file {path}: {error}") from error


def _secret(explicit: str | None, file_path: Path | None, env_name: str) -> str | None:
    value = explicit or _read_optional_file(file_path, "secret") or os.environ.get(env_name)
    return value.strip() if value and value.strip() else None


def _extra_info(args: Namespace) -> str:
    if args.extra_info_file:
        try:
            return args.extra_info_file.expanduser().read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ReviewError(f"Cannot read extra-info file {args.extra_info_file}: {error}") from error
    return args.extra_info.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "cleanup":
            result = cleanup_workspace(args.workspace, dry_run=args.dry_run)
        else:
            pora_session = _secret(args.pora_session, args.pora_session_file, args.pora_session_env)
            common = {
                "output_root": args.output_root,
                "lock_root": args.lock_root,
                "pora_session": pora_session,
                "youtrack_base_url": args.youtrack_base_url,
                "related_task_ids": args.related_task,
                "additional_information": _extra_info(args),
                "network_timeout": args.network_timeout,
                "offline": args.offline,
            }
            if args.kind == "local":
                result = prepare_local(
                    args.repos,
                    workspace_root=args.workspace_root,
                    base_ref=args.base,
                    scope=args.scope,
                    **common,
                )
            else:
                gitlab_token = _secret(args.gitlab_token, args.gitlab_token_file, args.gitlab_token_env)
                result = prepare_mr(
                    args.urls,
                    repo_root=args.repo_root,
                    repo_overrides=resolve_repo_override(args.repo),
                    remote=args.remote,
                    fallback_target=args.target,
                    gitlab_token=gitlab_token,
                    metadata_file=args.gitlab_metadata_file,
                    **common,
                )
            result["cleanup_command"] = (
                f"python3 {shlex.quote(str(Path(__file__).resolve().parents[1] / 'review_prepare.py'))} "
                f"cleanup {shlex.quote(result['workspace'])}"
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ReviewError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
