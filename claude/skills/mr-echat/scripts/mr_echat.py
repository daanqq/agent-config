#!/usr/bin/env python3
"""Git, GitLab, and pi text-generation mechanics for the mr-echat Claude Code skill."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


EUTP_RE = re.compile(r"EUTP-\d+", re.IGNORECASE)
TITLE_RE = re.compile(r"^.+ #(?P<task>EUTP-\d+)$", re.IGNORECASE)
TASK_TAG_RE = re.compile(r"#?EUTP-\d+", re.IGNORECASE)
RELATED_START = "<!-- mr-echat:related -->"
RELATED_END = "<!-- /mr-echat:related -->"
RELATED_RE = re.compile(rf"\n*{re.escape(RELATED_START)}.*?{re.escape(RELATED_END)}\n*", re.DOTALL)
MR_URL_RE = re.compile(r"/(?P<project>[^/]+)/-/merge_requests/(?P<iid>\d+)")
BASE_BRANCHES = ("main", "master", "develop", "dev", "stage", "staging")
MODEL_DIFF_EXCLUDES = (
    "**/package-lock.json",
    "**/npm-shrinkwrap.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/bun.lockb",
    "**/bun.lock",
    "**/dist/**",
    "**/build/**",
    "**/coverage/**",
    "**/generated/**",
    "**/__generated__/**",
    "**/*.generated.*",
    "**/*.gen.*",
    "**/*.pb.*",
)
PI_MODEL = "openai-codex/gpt-5.6-luna"
PROMPT_PATH = Path(__file__).with_name("generate_prompt.md")
# gpt-5.6-luna has a 272K-token context; two diffs of this size leave room for the rest of the prompt.
MAX_PROMPT_DIFF_CHARS = 250_000


class WorkflowError(RuntimeError):
    pass


def run(
    repo: Path,
    command: Sequence[str],
    *,
    check: bool = True,
    text: bool = True,
    input: str | None = None,
) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(
        list(command),
        cwd=repo,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        check=False,
    )
    if check and result.returncode:
        stderr = result.stderr.strip() if text else result.stderr.decode(errors="replace").strip()
        stdout = result.stdout.strip() if text else result.stdout.decode(errors="replace").strip()
        raise WorkflowError(f"{' '.join(command[:3])} failed: {stderr or stdout}")
    return result


def git(repo: Path, *args: str, check: bool = True, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return run(repo, ("git", *args), check=check, text=text)


def glab(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(repo, ("glab", *args), check=check)


def resolve_repo(raw: str) -> Path:
    requested = Path(raw).expanduser().resolve()
    if not requested.is_dir():
        raise WorkflowError(f"repository directory does not exist: {requested}")
    result = run(requested, ("git", "rev-parse", "--show-toplevel"), check=False)
    if result.returncode:
        raise WorkflowError(f"not a Git repository: {requested}")
    return Path(result.stdout.strip()).resolve()


def current_branch(repo: Path) -> str:
    branch = git(repo, "branch", "--show-current").stdout.strip()
    if not branch:
        raise WorkflowError("detached HEAD is not supported")
    return branch


def select_branch(repo: Path, requested: str | None) -> str:
    branch = current_branch(repo)
    if not requested or requested == branch:
        return branch
    if git(repo, "check-ref-format", "--branch", requested, check=False).returncode:
        raise WorkflowError(f"invalid branch name: {requested}")
    if not git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{requested}", check=False).returncode:
        git(repo, "switch", requested)
    elif not git(repo, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{requested}", check=False).returncode:
        git(repo, "switch", "--track", "-c", requested, f"origin/{requested}")
    else:
        base = next(
            (
                candidate
                for candidate in ("master", "main")
                if not git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}", check=False).returncode
            ),
            None,
        )
        if not base:
            raise WorkflowError("cannot create requested branch: no local master or main branch")
        git(repo, "switch", "-c", requested, base)
    return requested


def task_id_for(branch: str) -> str:
    match = EUTP_RE.search(branch)
    if not match:
        raise WorkflowError(f"branch does not contain an EUTP id: {branch}")
    return match.group(0).upper()


def nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in payload.split(b"\0") if item]


def changed_paths(repo: Path, *args: str) -> list[str]:
    result = git(repo, *args, "-z", text=False)
    return nul_paths(result.stdout)


def is_model_excluded(path: str) -> bool:
    normalized = path.removeprefix("./")
    candidates = (normalized, f"x/{normalized}")
    return any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates for pattern in MODEL_DIFF_EXCLUDES)


def diff_args(*args: str) -> list[str]:
    return [
        "diff",
        *args,
        "--",
        ".",
        *(f":(exclude,glob){pattern}" for pattern in MODEL_DIFF_EXCLUDES),
    ]


def untracked_diff(repo: Path, paths: list[str]) -> str:
    chunks: list[str] = []
    for relative in paths:
        if is_model_excluded(relative):
            continue
        path = repo / relative
        if not path.is_file():
            chunks.append(f"diff --untracked {relative}\n[non-regular file omitted]\n")
            continue
        if path.stat().st_size > 2_000_000:
            chunks.append(f"diff --untracked {relative}\n[file larger than 2 MB omitted]\n")
            continue
        result = git(repo, "diff", "--no-index", "--binary", "--", "/dev/null", relative, check=False)
        if result.returncode not in (0, 1):
            raise WorkflowError(f"cannot render untracked diff for {relative}: {result.stderr.strip()}")
        chunks.append(result.stdout)
    return "\n".join(chunks)


def status_fingerprint(repo: Path) -> str:
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", text=False).stdout
    digest = hashlib.sha256()
    digest.update(current_branch(repo).encode())
    digest.update(b"\0")
    digest.update(git(repo, "rev-parse", "HEAD").stdout.strip().encode())
    digest.update(b"\0")
    digest.update(status)
    digest.update(git(repo, "diff", "--binary", text=False).stdout)
    digest.update(git(repo, "diff", "--cached", "--binary", text=False).stdout)
    for relative in nul_paths(git(repo, "ls-files", "--others", "--exclude-standard", "-z", text=False).stdout):
        path = repo / relative
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def read_template(repo: Path, task_id: str) -> str:
    path = repo / ".gitlab" / "merge_request_templates" / "Default.md"
    if not path.is_file():
        raise WorkflowError(f"merge request template not found: {path}")
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"https?://youtrack\.esoft\.tech/issue/EUTP-(?:[…\.]+|\d+)",
        f"https://youtrack.esoft.tech/issue/{task_id}",
        text,
    )
    if re.search(r"https?://youtrack\.esoft\.tech/issue/EUTP-[…\.]+", text):
        raise WorkflowError("the EUTP placeholder in the MR template was not replaced")
    return text


def existing_mr(repo: Path, branch: str) -> dict[str, Any] | None:
    result = glab(repo, "mr", "list", "--source-branch", branch, "--output", "json")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise WorkflowError(f"glab returned invalid MR JSON: {error}") from error
    if not isinstance(rows, list) or not rows:
        return None
    if len(rows) != 1:
        raise WorkflowError(f"source branch has {len(rows)} merge requests; cannot select one safely")
    row = rows[0]
    url = row.get("web_url") or row.get("webUrl") or row.get("url")
    reference = row.get("iid") or row.get("id") or url
    if not url or not reference:
        raise WorkflowError("existing MR response has no URL or reference")
    return {
        "ref": str(reference),
        "url": str(url),
        "target_branch": row.get("target_branch") or row.get("targetBranch"),
    }


def mr_description(repo: Path, reference: str) -> str:
    return glab(repo, "mr", "view", reference, "--output", "json", "--jq", ".description").stdout.strip()


def previous_title(repo: Path, task_id: str) -> str | None:
    result = git(
        repo,
        "log",
        "-n",
        "1",
        "--no-merges",
        "--format=%s",
        "--fixed-strings",
        f"--grep={task_id}",
        check=False,
    )
    title = result.stdout.strip()
    return title or None


def remote_refs(repo: Path) -> list[str]:
    result = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
    return [line for line in result.stdout.splitlines() if line and line != "origin/HEAD"]


def select_parent_task_branch(repo: Path, branch: str) -> str | None:
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    default_base: str | None = None
    origin_head = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    for ref in (origin_head, *(f"origin/{name}" for name in BASE_BRANCHES), *BASE_BRANCHES):
        if not ref or git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode:
            continue
        base = git(repo, "merge-base", "HEAD", ref, check=False)
        if not base.returncode and base.stdout.strip():
            default_base = base.stdout.strip()
            break

    matches: list[tuple[int, str]] = []
    for ref in remote_refs(repo):
        normalized = ref.removeprefix("origin/")
        if normalized == branch or not EUTP_RE.search(normalized):
            continue
        base_result = git(repo, "merge-base", "HEAD", ref, check=False)
        base = base_result.stdout.strip()
        if base_result.returncode or not base or base in (head, default_base):
            continue
        if default_base and git(repo, "merge-base", "--is-ancestor", default_base, base, check=False).returncode:
            continue
        distance_result = git(repo, "rev-list", "--count", f"{base}..HEAD", check=False)
        if not distance_result.returncode and distance_result.stdout.strip().isdigit():
            matches.append((int(distance_result.stdout.strip()), normalized))
    matches.sort()
    return matches[0][1] if matches else None


def default_target_branch(repo: Path) -> str | None:
    origin_head = git(
        repo,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
        check=False,
    ).stdout.strip()
    if origin_head.startswith("origin/"):
        return origin_head.removeprefix("origin/")
    for branch in BASE_BRANCHES:
        if not git(repo, "rev-parse", "--verify", "--quiet", f"origin/{branch}", check=False).returncode:
            return branch
    return None


def ensure_target_exists(repo: Path, target: str) -> None:
    for ref in (f"refs/remotes/origin/{target}", f"refs/heads/{target}"):
        if not git(repo, "show-ref", "--verify", "--quiet", ref, check=False).returncode:
            return
    result = git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{target}", check=False)
    if result.returncode:
        raise WorkflowError(f"cannot verify target branch {target!r}: {result.stderr.strip()}")
    if not result.stdout.strip():
        raise WorkflowError(f"target branch does not exist on origin: {target}")


def branch_diff(repo: Path, target: str, output: Path) -> None:
    fetch = git(repo, "fetch", "--quiet", "origin", target, check=False)
    remote = f"origin/{target}"
    ref = remote if not fetch.returncode and not git(repo, "rev-parse", "--verify", "--quiet", remote, check=False).returncode else target
    result = git(repo, *diff_args(f"{ref}...HEAD"), check=False)
    if result.returncode:
        raise WorkflowError(f"cannot build branch diff against {target}: {result.stderr.strip()}")
    output.write_text(result.stdout, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def load_state(path: str) -> tuple[Path, dict[str, Any]]:
    state_path = Path(path).expanduser().resolve()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowError(f"cannot read workflow state {state_path}: {error}") from error
    if state.get("schema") != 1:
        raise WorkflowError("unsupported workflow state")
    repo = resolve_repo(str(state.get("repo", "")))
    return repo, state


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    repo = resolve_repo(args.repo)
    branch = select_branch(repo, args.branch)
    task_id = task_id_for(branch)
    staged = changed_paths(repo, "diff", "--cached", "--name-only")
    unstaged = changed_paths(repo, "diff", "--name-only")
    untracked = nul_paths(git(repo, "ls-files", "--others", "--exclude-standard", "-z", text=False).stdout)
    scope = "staged" if staged else "all"
    included = staged if staged else sorted(set(unstaged + untracked))
    mr = existing_mr(repo, branch)
    if not included and not mr:
        raise WorkflowError("no changes to commit and no existing MR to update")

    workspace = Path(tempfile.mkdtemp(prefix=f"claude-mr-echat-{task_id.lower()}-", dir="/tmp"))
    workspace.chmod(0o700)
    model_diff_path = workspace / "model.diff"
    if staged:
        model_diff = git(repo, *diff_args("--cached", "--binary")).stdout
    else:
        model_diff = git(repo, *diff_args("--binary")).stdout + untracked_diff(repo, untracked)
    model_diff_path.write_text(model_diff, encoding="utf-8")

    template_path: Path | None = None
    current_description_path: Path | None = None
    if args.target_branch and git(repo, "check-ref-format", "--branch", args.target_branch, check=False).returncode:
        raise WorkflowError(f"invalid target branch name: {args.target_branch}")
    if mr and args.target_branch and args.target_branch != mr.get("target_branch"):
        raise WorkflowError(
            f"existing MR targets {mr.get('target_branch')!r}, not requested target {args.target_branch!r}"
        )
    target = args.target_branch or (
        mr.get("target_branch") if mr else select_parent_task_branch(repo, branch) or default_target_branch(repo)
    )
    if target:
        ensure_target_exists(repo, str(target))
    branch_diff_path: Path | None = None
    if target:
        branch_diff_path = workspace / "branch.diff"
        branch_diff(repo, str(target), branch_diff_path)
    if mr:
        current_description_path = workspace / "current-description.md"
        current_description_path.write_text(mr_description(repo, mr["ref"]), encoding="utf-8")
    else:
        template_path = workspace / "template.md"
        template_path.write_text(read_template(repo, task_id), encoding="utf-8")

    state_path = workspace / "state.json"
    state = {
        "schema": 1,
        "repo": str(repo),
        "branch": branch,
        "task_id": task_id,
        "head_before": git(repo, "rev-parse", "HEAD").stdout.strip(),
        "fingerprint": status_fingerprint(repo),
        "scope": scope,
        "included_paths": included,
        "preserved_paths": sorted(set((unstaged + untracked) if staged else [])),
        "existing_mr": mr,
        "target_branch": target,
        "workspace": str(workspace),
        "committed_sha": None,
        "pushed": False,
    }
    write_json(state_path, state)
    return {
        **state,
        "state_path": str(state_path),
        "model_diff_path": str(model_diff_path),
        "model_diff_chars": len(model_diff),
        "template_path": str(template_path) if template_path else None,
        "current_description_path": str(current_description_path) if current_description_path else None,
        "branch_diff_path": str(branch_diff_path) if branch_diff_path else None,
        "last_task_commit_title": previous_title(repo, task_id),
    }


def validated_title(path: str, task_id: str) -> str:
    title = Path(path).expanduser().read_text(encoding="utf-8").strip()
    if not title or "\n" in title or "\r" in title:
        raise WorkflowError("commit title must be one non-empty line")
    match = TITLE_RE.fullmatch(title)
    if not match or match.group("task").upper() != task_id.upper():
        raise WorkflowError(f"commit title must end with exactly #{task_id}")
    return title


def normalized_title(raw: str, task_id: str) -> str:
    text = " ".join(TASK_TAG_RE.sub(" ", raw).split())
    if not text:
        raise WorkflowError("commit title is empty")
    return f"{text} #{task_id}"


def prompt_section(name: str, text: str | None) -> str:
    return f"<{name}>\n{(text or '').strip() or '(none)'}\n</{name}>"


def prompt_diff(path: Path) -> str:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if len(text) <= MAX_PROMPT_DIFF_CHARS:
        return text
    return f"{text[:MAX_PROMPT_DIFF_CHARS]}\n[diff truncated: first {MAX_PROMPT_DIFF_CHARS} of {len(text)} characters shown]"


def ask_model(prompt: str, cwd: Path) -> str:
    # Diffs are untrusted, so pi runs without tools and without user or project configuration.
    return run(
        cwd,
        (
            "pi",
            "--print",
            "--no-session",
            "--no-tools",
            "--no-context-files",
            "--no-skills",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-approve",
            "--model",
            PI_MODEL,
        ),
        input=prompt,
    ).stdout


def tagged(text: str, name: str) -> str | None:
    match = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", text, re.DOTALL)
    return match.group(1).strip() if match else None


def split_related(description: str) -> tuple[str, str | None]:
    match = RELATED_RE.search(description)
    if not match:
        return description, None
    body = (description[: match.start()] + "\n\n" + description[match.end() :]).strip()
    return body, match.group(0).strip()


def with_related(description: str, related: str | None) -> str:
    body, _ = split_related(description)
    return f"{body}\n\n{related}" if related else body


def generate(args: argparse.Namespace) -> dict[str, Any]:
    repo, state = load_state(args.state)
    workspace = Path(state["workspace"])
    task_id = state["task_id"]
    title_required = bool(state["included_paths"]) and not args.title
    notes = Path(args.notes_file).expanduser().read_text(encoding="utf-8") if args.notes_file else None
    mr_path = (workspace / "current-description.md") if state.get("existing_mr") else (workspace / "template.md")
    # The related-MR block belongs to `link`; keep it away from the model and carry it over unchanged.
    mr_text, related = split_related(mr_path.read_text(encoding="utf-8"))
    prompt = "\n\n".join(
        (
            PROMPT_PATH.read_text(encoding="utf-8").strip(),
            prompt_section("title_required", "yes" if title_required else "no"),
            prompt_section("last_task_commit_title", previous_title(repo, task_id) if title_required else None),
            prompt_section("pending_paths", "\n".join(state["included_paths"])),
            prompt_section("current_description" if state.get("existing_mr") else "template", mr_text),
            prompt_section("notes", notes),
            prompt_section("branch_diff", prompt_diff(workspace / "branch.diff")),
            prompt_section("pending_diff", prompt_diff(workspace / "model.diff")),
        )
    )
    answer = ask_model(prompt, workspace)
    description = tagged(answer, "description")
    if not description:
        raise WorkflowError(f"{PI_MODEL} returned no <description>: {answer.strip()[:500]}")

    title_path: Path | None = None
    title: str | None = None
    if state["included_paths"]:
        raw_title = args.title or tagged(answer, "title")
        if not raw_title:
            raise WorkflowError(f"{PI_MODEL} returned no <title>: {answer.strip()[:500]}")
        title = normalized_title(raw_title, task_id)
        title_path = workspace / "title.txt"
        title_path.write_text(title + "\n", encoding="utf-8")
    description = with_related(description, related)
    description_path = workspace / "description.md"
    description_path.write_text(description + "\n", encoding="utf-8")
    state["title_path"] = str(title_path) if title_path else None
    state["description_path"] = str(description_path)
    write_json(Path(args.state).expanduser().resolve(), state)
    return {
        "status": "generated",
        "model": PI_MODEL,
        "title": title,
        "title_path": state["title_path"],
        "description": description,
        "description_path": state["description_path"],
    }


def commit(args: argparse.Namespace) -> dict[str, Any]:
    repo, state = load_state(args.state)
    if state.get("committed_sha"):
        raise WorkflowError("this workflow state already recorded a commit")
    if current_branch(repo) != state["branch"] or status_fingerprint(repo) != state["fingerprint"]:
        raise WorkflowError("repository state changed after preparation; prepare and confirm again")
    title = validated_title(args.title_file, state["task_id"])
    if state["scope"] == "all":
        git(repo, "add", "-A")
    expected_tree = git(repo, "write-tree").stdout.strip()
    result = git(repo, "commit", "-m", title, check=False)
    if result.returncode:
        raise WorkflowError(f"git commit failed: {result.stderr.strip() or result.stdout.strip()}")
    state["committed_sha"] = git(repo, "rev-parse", "HEAD").stdout.strip()
    committed_tree = git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    if committed_tree != expected_tree:
        state["scope_mismatch"] = True
        write_json(Path(args.state).expanduser().resolve(), state)
        raise WorkflowError("a Git hook changed the confirmed commit scope; inspect and amend before pushing")
    write_json(Path(args.state).expanduser().resolve(), state)
    return {"status": "committed", "commit": state["committed_sha"], "scope": state["scope"]}


def remote_sha(repo: Path, branch: str) -> str | None:
    result = git(repo, "ls-remote", "--heads", "origin", f"refs/heads/{branch}", check=False)
    if result.returncode or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


def push(args: argparse.Namespace) -> dict[str, Any]:
    repo, state = load_state(args.state)
    if state.get("scope_mismatch"):
        raise WorkflowError("the committed tree does not match the confirmed scope; amend before pushing")
    if not state.get("committed_sha") and status_fingerprint(repo) != state.get("fingerprint"):
        raise WorkflowError("repository state changed after preparation; prepare and confirm again")
    commit_sha = state.get("committed_sha") or state.get("head_before")
    if not commit_sha or git(repo, "rev-parse", "HEAD").stdout.strip() != commit_sha:
        raise WorkflowError("HEAD is not the revision recorded by this workflow")
    if current_branch(repo) != state["branch"]:
        raise WorkflowError("current branch changed after commit")

    branch = state["branch"]
    before = remote_sha(repo, branch)
    command = ["push", "-u", "origin", "HEAD"]
    if args.force_with_lease:
        expected_remote = state.get("force_lease_sha")
        if not expected_remote:
            raise WorkflowError("no confirmed force-with-lease state; run a normal push first")
        if not before:
            raise WorkflowError("remote branch does not exist; force-with-lease is unnecessary")
        command = ["push", f"--force-with-lease=refs/heads/{branch}:{expected_remote}", "-u", "origin", "HEAD"]
    result = git(repo, *command, check=False)
    if result.returncode:
        if not args.force_with_lease and before:
            remote_ref = f"refs/remotes/origin/{branch}"
            fetch = git(
                repo,
                "fetch",
                "--quiet",
                "origin",
                f"+refs/heads/{branch}:{remote_ref}",
                check=False,
            )
            missing = not fetch.returncode and git(
                repo,
                "merge-base",
                "--is-ancestor",
                remote_ref,
                commit_sha,
                check=False,
            ).returncode != 0
            if missing:
                state["force_lease_sha"] = before
                write_json(Path(args.state).expanduser().resolve(), state)
                return {
                    "status": "needs-force-with-lease",
                    "remote_sha": before,
                    "message": "remote branch contains commits absent from local HEAD",
                }
        raise WorkflowError(f"git push failed: {result.stderr.strip() or result.stdout.strip()}")
    after = remote_sha(repo, branch)
    if after != commit_sha:
        raise WorkflowError("remote branch does not point to the committed SHA after push")
    state["pushed"] = True
    write_json(Path(args.state).expanduser().resolve(), state)
    return {"status": "pushed", "commit": commit_sha, "remote_sha": after}


def publish(args: argparse.Namespace) -> dict[str, Any]:
    repo, state = load_state(args.state)
    commit_sha = state.get("committed_sha")
    expected_sha = commit_sha or state.get("head_before")
    if not state.get("pushed"):
        raise WorkflowError("the recorded revision has not been pushed or synchronized")
    if remote_sha(repo, state["branch"]) != expected_sha:
        raise WorkflowError("remote branch changed after push")
    description = Path(args.description_file).expanduser().read_text(encoding="utf-8").strip()
    if not description:
        raise WorkflowError("MR description is empty")

    mr = existing_mr(repo, state["branch"])
    prepared_mr = state.get("existing_mr")
    if bool(mr) != bool(prepared_mr):
        raise WorkflowError("MR create/update operation changed after confirmation; prepare again")
    if mr and prepared_mr and mr["ref"] != prepared_mr["ref"]:
        raise WorkflowError("the existing MR identity changed after confirmation; prepare again")
    if mr:
        result = glab(repo, "mr", "update", mr["ref"], "--description", description)
        state["published"] = True
        state["mr_url"] = mr["url"]
        write_json(Path(args.state).expanduser().resolve(), state)
        return {"status": "updated", "url": mr["url"], "target_branch": mr.get("target_branch"), "output": result.stdout.strip()}

    if not args.title_file:
        raise WorkflowError("--title-file is required when creating an MR")
    title = validated_title(args.title_file, state["task_id"])
    username: str | None = None
    user_result = glab(repo, "api", "user", check=False)
    if not user_result.returncode:
        try:
            username = json.loads(user_result.stdout).get("username")
        except json.JSONDecodeError:
            username = None
    command = ["mr", "create", "--title", title, "--description", description, "--yes"]
    if username:
        command.extend(("--assignee", username))
    if state.get("target_branch"):
        command.extend(("--target-branch", state["target_branch"]))
    result = glab(repo, *command)
    match = re.search(r"https://gitlab\.[^\s]+", result.stdout)
    mr = existing_mr(repo, state["branch"])
    url = match.group(0) if match else mr.get("url") if mr else None
    if not url:
        raise WorkflowError("MR was created but its URL could not be determined")
    state["published"] = True
    state["mr_url"] = url
    write_json(Path(args.state).expanduser().resolve(), state)
    return {"status": "created", "url": url, "target_branch": state.get("target_branch")}


def cleanup(args: argparse.Namespace) -> dict[str, Any]:
    _, state = load_state(args.state)
    state_path = Path(args.state).expanduser().resolve()
    workspace = Path(state.get("workspace", "")).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if workspace.parent != temp_root or not workspace.name.startswith("claude-mr-echat-"):
        raise WorkflowError(f"refusing to remove unowned workspace: {workspace}")
    if state_path.parent != workspace or not state.get("published"):
        raise WorkflowError("refusing cleanup before successful publication")
    shutil.rmtree(workspace)
    return {"status": "cleaned", "workspace": str(workspace)}


def mr_label(url: str) -> str:
    match = MR_URL_RE.search(url)
    return f"{match.group('project')}!{match.group('iid')}" if match else url


def link(args: argparse.Namespace) -> dict[str, Any]:
    mrs: list[tuple[Path, dict[str, Any]]] = []
    for raw in args.repo:
        repo = resolve_repo(raw)
        mr = existing_mr(repo, current_branch(repo))
        if not mr:
            raise WorkflowError(f"no open MR for the current branch of {repo}")
        if any(mr["url"] == other["url"] for _, other in mrs):
            raise WorkflowError(f"MR is listed twice: {mr['url']}")
        mrs.append((repo, mr))
    if len(mrs) < 2:
        raise WorkflowError("linking needs at least two merge requests")

    for repo, mr in mrs:
        others = ", ".join(f"[{mr_label(other['url'])}]({other['url']})" for _, other in mrs if other is not mr)
        related = f"{RELATED_START}\nСвязанные MR: {others}.\n{RELATED_END}"
        glab(repo, "mr", "update", mr["ref"], "--description", with_related(mr_description(repo, mr["ref"]), related))
    return {"status": "linked", "urls": [mr["url"] for _, mr in mrs]}


def ship(args: argparse.Namespace) -> dict[str, Any]:
    _, state = load_state(args.state)
    if not state.get("description_path"):
        raise WorkflowError("no generated description; run generate first")
    title_file = state.get("title_path")
    # A rerun after a failed push or publish must not create a second commit.
    if state["included_paths"] and not state.get("committed_sha"):
        commit(argparse.Namespace(state=args.state, title_file=title_file))
    pushed = push(argparse.Namespace(state=args.state, force_with_lease=args.force_with_lease))
    if pushed["status"] != "pushed":
        return pushed
    published = publish(
        argparse.Namespace(state=args.state, title_file=title_file, description_file=state["description_path"])
    )
    _, state = load_state(args.state)
    cleaned = cleanup(argparse.Namespace(state=args.state))
    return {
        **published,
        "commit": state.get("committed_sha") or state.get("head_before"),
        "committed_paths": state["included_paths"] if state.get("committed_sha") else [],
        "preserved_paths": state["preserved_paths"],
        "removed_workspace": cleaned["workspace"],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--repo", required=True)
    prepare_parser.add_argument("--branch")
    prepare_parser.add_argument("--target-branch")
    commit_parser = sub.add_parser("commit")
    commit_parser.add_argument("--state", required=True)
    commit_parser.add_argument("--title-file", required=True)
    push_parser = sub.add_parser("push")
    push_parser.add_argument("--state", required=True)
    push_parser.add_argument("--force-with-lease", action="store_true")
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("--state", required=True)
    generate_parser.add_argument("--notes-file")
    generate_parser.add_argument("--title")
    ship_parser = sub.add_parser("ship")
    ship_parser.add_argument("--state", required=True)
    ship_parser.add_argument("--force-with-lease", action="store_true")
    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("--state", required=True)
    publish_parser.add_argument("--title-file")
    publish_parser.add_argument("--description-file", required=True)
    cleanup_parser = sub.add_parser("cleanup")
    cleanup_parser.add_argument("--state", required=True)
    link_parser = sub.add_parser("link")
    link_parser.add_argument("--repo", action="append", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "prepare":
            payload = prepare(args)
        elif args.command == "commit":
            payload = commit(args)
        elif args.command == "push":
            payload = push(args)
        elif args.command == "generate":
            payload = generate(args)
        elif args.command == "ship":
            payload = ship(args)
        elif args.command == "link":
            payload = link(args)
        elif args.command == "publish":
            payload = publish(args)
        else:
            payload = cleanup(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except WorkflowError as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
