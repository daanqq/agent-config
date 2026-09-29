from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


TOOL_NAME = "echat-mr-review"
SCHEMA_VERSION = 1
TASK_RE = re.compile(r"\b(EUTP-\d+)\b", re.IGNORECASE)
MAX_HTTP_RESPONSE_BYTES = 10 * 1024 * 1024
SCOPE_CONTRACT = (
    "Review only changes selected by each target's path, merge_base, head_ref, and scope. "
    "Other files may be read for context, but findings must be caused by an in-scope changed "
    "line or an explicitly listed untracked file."
)


class ReviewError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class MrRef:
    url: str
    scheme: str
    host: str
    project_path: str
    repo: str
    iid: int

    @property
    def key(self) -> str:
        return f"{self.host}/{self.project_path}!{self.iid}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_mr_url(url: str) -> MrRef:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReviewError(f"Invalid GitLab MR URL: {url}")
    match = re.fullmatch(r"/(.+)/-/merge_requests/(\d+)/?", parsed.path)
    if not match:
        raise ReviewError(f"Expected GitLab .../-/merge_requests/<iid> URL: {url}")
    project_path = urllib.parse.unquote(match.group(1)).strip("/")
    parts = project_path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ReviewError(f"Unsafe GitLab project path: {project_path}")
    return MrRef(
        url=url,
        scheme=parsed.scheme,
        host=parsed.netloc,
        project_path=project_path,
        repo=parts[-1],
        iid=int(match.group(2)),
    )


def extract_task_id(text: str) -> str | None:
    match = TASK_RE.search(text or "")
    return match.group(1).upper() if match else None


def extract_task_ids(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        for match in TASK_RE.finditer(value or ""):
            task_id = match.group(1).upper()
            if task_id not in found:
                found.append(task_id)
    return found


def _run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(args), cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False
        )
    except FileNotFoundError as error:
        raise ReviewError(f"Command not found: {args[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ReviewError(f"Command timed out after {timeout:g}s: {' '.join(args)}") from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ReviewError(f"Command failed ({result.returncode}): {' '.join(args)}\n{detail}")
    return result


def git(repo: Path, *args: str, timeout: float = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repo), *args], timeout=timeout, check=check)


def git_text(repo: Path, *args: str, timeout: float = 60) -> str:
    return git(repo, *args, timeout=timeout).stdout.strip()


def _nul_list(text: str) -> list[str]:
    return [value for value in text.split("\0") if value]


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def assert_git_repo(repo: Path) -> Path:
    resolved = repo.expanduser().resolve()
    if not resolved.exists():
        raise ReviewError(f"Repository does not exist: {resolved}")
    result = git(resolved, "rev-parse", "--git-dir", check=False)
    if result.returncode != 0:
        raise ReviewError(f"Not a Git repository: {resolved}")
    return resolved


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return slug or "repo"


def _lock_key(repo: Path) -> str:
    digest = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:16]
    return f"{_safe_slug(repo.name)}-{digest}"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def repo_lock(lock_root: Path, repo: Path, timeout: float = 120, stale_after: float = 600) -> Iterator[None]:
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_dir = lock_root / f"{_lock_key(repo)}.lock"
    nonce = secrets.token_hex(12)
    owner = {"pid": os.getpid(), "host": socket.gethostname(), "nonce": nonce, "created_at": utc_now()}
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock_dir.mkdir()
        except FileExistsError:
            stale = False
            try:
                age = time.time() - lock_dir.stat().st_mtime
                current = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
                live_local_owner = current.get("host") == socket.gethostname() and _pid_alive(int(current.get("pid", 0)))
                stale = age > stale_after and not live_local_owner
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                stale = time.time() - lock_dir.stat().st_mtime > stale_after
            if stale:
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                raise ReviewError(f"Timed out waiting for repository lock: {repo}")
            time.sleep(0.2)
            continue
        try:
            (lock_dir / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
        except OSError as error:
            shutil.rmtree(lock_dir, ignore_errors=True)
            raise ReviewError(f"Cannot initialize repository lock {lock_dir}: {error}") from error
        break
    try:
        yield
    finally:
        try:
            current = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
            if current.get("nonce") == nonce:
                shutil.rmtree(lock_dir)
        except (OSError, json.JSONDecodeError):
            pass


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


class Workspace:
    def __init__(self, output_root: Path, kind: str, lock_root: Path):
        output_root = output_root.expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.workspace_id = f"review-{stamp}-{secrets.token_hex(4)}"
        self.root = output_root / self.workspace_id
        self.root.mkdir(mode=0o700)
        self.marker = self.root / ".echat-mr-review-workspace"
        self.marker.write_text(self.workspace_id + "\n", encoding="utf-8")
        self.manifest_path = self.root / "manifest.json"
        self.manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tool": TOOL_NAME,
            "workspace_id": self.workspace_id,
            "kind": kind,
            "created_at": utc_now(),
            "root": str(self.root),
            "lock_root": str(lock_root.expanduser().resolve()),
            "worktrees": [],
            "artifacts": {},
        }
        self.save()

    def save(self) -> None:
        _atomic_json(self.manifest_path, self.manifest)

    def record_worktree(self, source_repo: Path, worktree: Path, refs: Sequence[str]) -> None:
        self.manifest["worktrees"].append(
            {"source_repo": str(source_repo), "path": str(worktree), "refs": list(refs)}
        )
        self.save()

    def record_artifacts(self, context_json: Path, context_markdown: Path) -> None:
        self.manifest["artifacts"] = {
            "review_context_json": str(context_json),
            "review_context_markdown": str(context_markdown),
        }
        self.save()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReviewError(f"Cannot read JSON from {path}: {error}") from error


def _fetch_json(request: urllib.request.Request, *, timeout: float, label: str) -> dict[str, Any]:
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_HTTP_RESPONSE_BYTES:
                        raise ReviewError(f"{label} response exceeds the size limit")
                except ValueError:
                    pass
            body = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
        raise ReviewError(f"{label} request failed: {error}") from error
    if len(body) > MAX_HTTP_RESPONSE_BYTES:
        raise ReviewError(f"{label} response exceeds the size limit")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewError(f"{label} response is not valid UTF-8 JSON: {error}") from error
    if not isinstance(data, dict):
        raise ReviewError(f"{label} response is not a JSON object")
    return data


def load_gitlab_metadata(path: Path | None, ref: MrRef) -> dict[str, Any] | None:
    if path is None:
        return None
    data = _load_json(path)
    if isinstance(data, dict) and any(key in data for key in ("target_branch", "source_branch", "title")):
        return data
    if isinstance(data, dict):
        items = data.get("items", data)
        if isinstance(items, dict):
            for key in (ref.url, ref.key, f"{ref.project_path}!{ref.iid}", f"{ref.repo}!{ref.iid}"):
                value = items.get(key)
                if isinstance(value, dict):
                    return value
    raise ReviewError(f"No GitLab metadata entry for {ref.key} in {path}")


def fetch_gitlab_metadata(
    ref: MrRef,
    *,
    token: str | None,
    timeout: float,
    offline: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    if offline:
        return None, "GitLab metadata skipped in offline mode"
    project = urllib.parse.quote(ref.project_path, safe="")
    api_url = f"{ref.scheme}://{ref.host}/api/v4/projects/{project}/merge_requests/{ref.iid}"
    headers = {"Accept": "application/json", "User-Agent": f"{TOOL_NAME}/1.0"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    api_error = "unknown error"
    try:
        return _fetch_json(
            urllib.request.Request(api_url, headers=headers),
            timeout=timeout,
            label="GitLab API",
        ), None
    except ReviewError as error:
        api_error = str(error)

    glab = shutil.which("glab")
    if glab:
        result = _run(
            [glab, "api", "--hostname", ref.host, f"/projects/{project}/merge_requests/{ref.iid}"],
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    return data, None
            except json.JSONDecodeError:
                pass
        glab_error = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        return None, f"GitLab API failed ({api_error}); glab fallback failed ({glab_error})"
    return None, f"GitLab API failed ({api_error}); glab is unavailable"


def fetch_task(task_id: str, session: str, base_url: str, timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{urllib.parse.quote(task_id)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cookie": f"pora-gatekeeper-session={session}",
            "User-Agent": f"{TOOL_NAME}/1.0",
        },
    )
    return _fetch_json(request, timeout=timeout, label=f"YouTrack {task_id}")


def preferred_base(repo: Path) -> str:
    candidates = ["origin/HEAD", "origin/master", "origin/main", "origin/stage", "origin/develop", "master", "main", "stage", "develop"]
    for candidate in candidates:
        if git(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}", check=False).returncode == 0:
            return candidate
    raise ReviewError(f"Cannot find a base branch in {repo}; pass --base explicitly")


def merge_base(repo: Path, head: str, base: str) -> str:
    result = git(repo, "merge-base", head, base, check=False)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise ReviewError(f"Cannot resolve merge-base for {head} and {base} in {repo}")
    return value


def repository_state(repo: Path, merge_base_sha: str, head_ref: str, scope: str) -> dict[str, Any]:
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout.rstrip()
    untracked = _nul_list(git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    branch = _nul_list(git(repo, "diff", "--name-only", "-z", f"{merge_base_sha}..{head_ref}", "--").stdout)
    staged = _nul_list(git(repo, "diff", "--cached", "--name-only", "-z", "--").stdout)
    unstaged = _nul_list(git(repo, "diff", "--name-only", "-z", "--").stdout)
    if scope == "branch":
        in_scope = branch
    elif scope == "working-tree":
        in_scope = _unique([*staged, *unstaged, *untracked])
    elif scope == "all":
        in_scope = _unique([*branch, *staged, *unstaged, *untracked])
    else:
        raise ReviewError(f"Unknown scope: {scope}")
    commands: list[str] = []
    quoted_repo = _shell_quote(str(repo))
    if scope in {"branch", "all"}:
        commands.append(f"git -C {quoted_repo} diff --find-renames {merge_base_sha}..{head_ref} --")
    if scope in {"working-tree", "all"}:
        commands.extend(
            [
                f"git -C {quoted_repo} diff --cached --find-renames --",
                f"git -C {quoted_repo} diff --find-renames --",
            ]
        )
    return {
        "status": status,
        "untracked_files": untracked,
        "file_sets": {
            "branch": branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "in_scope": in_scope,
        },
        "review_commands": commands,
    }


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def task_id_from_commits(repo: Path, head_ref: str, base_ref: str) -> str | None:
    result = git(repo, "log", head_ref, "--not", base_ref, "--format=%B", check=False)
    return extract_task_id(result.stdout) if result.returncode == 0 else None


def resolve_repo_override(items: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            raise ReviewError(f"--repo expects NAME=PATH, got: {item}")
        name, raw_path = item.split("=", 1)
        if not name or not raw_path:
            raise ReviewError(f"--repo expects NAME=PATH, got: {item}")
        result[name] = Path(raw_path).expanduser().resolve()
    return result


def _task_loader(
    *, session: str | None, base_url: str, timeout: float, offline: bool, warnings: list[str]
):
    cache: dict[str, dict[str, Any] | None] = {}

    def load(task_id: str | None) -> dict[str, Any] | None:
        if not task_id or not session or offline:
            return None
        if task_id not in cache:
            try:
                cache[task_id] = fetch_task(task_id, session, base_url, timeout)
            except ReviewError as error:
                warnings.append(str(error))
                cache[task_id] = None
        return cache[task_id]

    return load


def _write_context(workspace: Workspace, context: dict[str, Any]) -> dict[str, str]:
    json_path = workspace.root / "review-context.json"
    markdown_path = workspace.root / "review-context.md"
    _atomic_json(json_path, context)
    markdown_path.write_text(render_context_markdown(context), encoding="utf-8")
    workspace.record_artifacts(json_path, markdown_path)
    return {
        "workspace": str(workspace.root),
        "manifest": str(workspace.manifest_path),
        "review_context_json": str(json_path),
        "review_context_markdown": str(markdown_path),
    }


def prepare_local(
    repos: Sequence[str],
    *,
    workspace_root: Path,
    output_root: Path,
    lock_root: Path,
    base_ref: str | None,
    scope: str,
    pora_session: str | None,
    youtrack_base_url: str,
    related_task_ids: Sequence[str],
    additional_information: str,
    network_timeout: float,
    offline: bool,
) -> dict[str, str]:
    workspace = Workspace(output_root, "local", lock_root)
    warnings: list[str] = []
    load_task = _task_loader(
        session=pora_session, base_url=youtrack_base_url, timeout=network_timeout, offline=offline, warnings=warnings
    )
    targets: list[dict[str, Any]] = []
    try:
        for raw_repo in repos:
            candidate = Path(raw_repo).expanduser()
            if not candidate.is_absolute() and not candidate.exists():
                candidate = workspace_root / candidate
            repo = assert_git_repo(candidate)
            source_branch = git_text(repo, "branch", "--show-current") or "DETACHED"
            selected_base = base_ref or preferred_base(repo)
            merge_base_sha = merge_base(repo, "HEAD", selected_base)
            task_id = extract_task_id(source_branch) or task_id_from_commits(repo, "HEAD", selected_base)
            state = repository_state(repo, merge_base_sha, "HEAD", scope)
            targets.append(
                {
                    "kind": "local",
                    "repo": repo.name,
                    "path": str(repo),
                    "source_branch": source_branch,
                    "base_ref": selected_base,
                    "head_ref": "HEAD",
                    "merge_base": merge_base_sha,
                    "scope": scope,
                    "task_id": task_id,
                    "task": load_task(task_id),
                    **state,
                }
            )
        context = _build_context(
            workspace, "local", targets, related_task_ids, load_task, additional_information, warnings
        )
        return _write_context(workspace, context)
    except Exception:
        cleanup_workspace(workspace.root, ignore_errors=True)
        raise


def prepare_mr(
    urls: Sequence[str],
    *,
    repo_root: Path,
    repo_overrides: dict[str, Path],
    output_root: Path,
    lock_root: Path,
    remote: str,
    fallback_target: str,
    gitlab_token: str | None,
    metadata_file: Path | None,
    pora_session: str | None,
    youtrack_base_url: str,
    related_task_ids: Sequence[str],
    additional_information: str,
    network_timeout: float,
    offline: bool,
) -> dict[str, str]:
    refs = [parse_mr_url(url) for url in urls]
    duplicate_keys = [key for key in {ref.key for ref in refs} if sum(item.key == key for item in refs) > 1]
    if duplicate_keys:
        raise ReviewError(f"Duplicate merge request targets: {', '.join(sorted(duplicate_keys))}")
    workspace = Workspace(output_root, "mr", lock_root)
    warnings: list[str] = []
    load_task = _task_loader(
        session=pora_session, base_url=youtrack_base_url, timeout=network_timeout, offline=offline, warnings=warnings
    )
    targets: list[dict[str, Any]] = []
    try:
        for ref in refs:
            source_candidate = repo_overrides.get(ref.project_path) or repo_overrides.get(ref.repo) or repo_root / ref.repo
            source_repo = assert_git_repo(source_candidate)
            metadata = load_gitlab_metadata(metadata_file, ref) if metadata_file else None
            if metadata is None:
                metadata, warning = fetch_gitlab_metadata(
                    ref, token=gitlab_token, timeout=network_timeout, offline=offline
                )
                if warning:
                    warnings.append(f"{ref.key}: {warning}; using target {fallback_target}")
            target_branch = str((metadata or {}).get("target_branch") or fallback_target)
            source_branch = str((metadata or {}).get("source_branch") or f"MR !{ref.iid}")
            target_key = hashlib.sha256(ref.key.encode()).hexdigest()[:12]
            ref_prefix = f"refs/echat-mr-review/{workspace.workspace_id}/target-{target_key}"
            head_fetch_ref = f"{ref_prefix}/head"
            base_fetch_ref = f"{ref_prefix}/base"
            worktree = workspace.root / f"{_safe_slug(ref.repo)}--mr-{ref.iid}-{target_key[:6]}"
            with repo_lock(lock_root, source_repo):
                git(
                    source_repo,
                    "fetch",
                    remote,
                    f"+refs/merge-requests/{ref.iid}/head:{head_fetch_ref}",
                    f"+refs/heads/{target_branch}:{base_fetch_ref}",
                    timeout=120,
                )
                git(source_repo, "worktree", "add", "--detach", str(worktree), head_fetch_ref, timeout=60)
                try:
                    workspace.record_worktree(source_repo, worktree, [head_fetch_ref, base_fetch_ref])
                except Exception:
                    git(source_repo, "worktree", "remove", "--force", str(worktree), check=False)
                    git(source_repo, "worktree", "prune", check=False)
                    git(source_repo, "update-ref", "-d", head_fetch_ref, check=False)
                    git(source_repo, "update-ref", "-d", base_fetch_ref, check=False)
                    raise
            merge_base_sha = merge_base(worktree, "HEAD", base_fetch_ref)
            metadata_text = f"{source_branch}\n{(metadata or {}).get('title', '')}\n{(metadata or {}).get('description', '')}"
            task_id = extract_task_id(metadata_text) or task_id_from_commits(worktree, "HEAD", base_fetch_ref)
            state = repository_state(worktree, merge_base_sha, "HEAD", "branch")
            targets.append(
                {
                    "kind": "mr",
                    "repo": ref.repo,
                    "path": str(worktree),
                    "source_repo": str(source_repo),
                    "source_branch": source_branch,
                    "base_ref": base_fetch_ref,
                    "head_ref": "HEAD",
                    "merge_base": merge_base_sha,
                    "scope": "branch",
                    "status": state["status"],
                    "untracked_files": state["untracked_files"],
                    "file_sets": state["file_sets"],
                    "review_commands": state["review_commands"],
                    "task_id": task_id,
                    "task": load_task(task_id),
                    "mr": {
                        "url": ref.url,
                        "host": ref.host,
                        "project_path": ref.project_path,
                        "iid": ref.iid,
                        "title": (metadata or {}).get("title"),
                        "description": (metadata or {}).get("description"),
                        "source_branch": source_branch,
                        "target_branch": target_branch,
                        "web_url": (metadata or {}).get("web_url") or ref.url,
                    },
                }
            )
        context = _build_context(workspace, "mr", targets, related_task_ids, load_task, additional_information, warnings)
        return _write_context(workspace, context)
    except Exception:
        cleanup_workspace(workspace.root, ignore_errors=True)
        raise


def _build_context(
    workspace: Workspace,
    kind: str,
    targets: list[dict[str, Any]],
    related_task_ids: Sequence[str],
    load_task,
    additional_information: str,
    warnings: list[str],
) -> dict[str, Any]:
    primary_id = targets[0].get("task_id") if targets else None
    primary_task = targets[0].get("task") if targets else None
    related = [{"id": task_id, "task": load_task(task_id)} for task_id in extract_task_ids(related_task_ids)]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "generated_at": utc_now(),
        "kind": kind,
        "workspace": {"id": workspace.workspace_id, "root": str(workspace.root), "manifest": str(workspace.manifest_path)},
        "scope_contract": SCOPE_CONTRACT,
        "targets": targets,
        "primary_task": {"id": primary_id, "task": primary_task},
        "related_tasks": related,
        "additional_information": additional_information,
        "warnings": warnings,
    }


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _task_markdown(task_id: str | None, task: dict[str, Any] | None) -> str:
    if not task_id:
        return "- **ID**: не найден\n- **Данные**: ревью выполняется без сверки с задачей."
    if not task:
        return f"- **ID**: {task_id}\n- **Данные**: не загружены."
    assignee = task.get("assignee") if isinstance(task.get("assignee"), dict) else {}
    sprints = task.get("sprints") if isinstance(task.get("sprints"), list) else []
    sprint = sprints[0] if sprints and isinstance(sprints[0], dict) else {}
    description = str(task.get("textMd") or task.get("description") or "(описание отсутствует)")[:12000]
    return "\n".join(
        [
            f"- **ID**: {_fmt(task.get('id') or task_id)}",
            f"- **Заголовок**: {_fmt(task.get('title') or task.get('summary'))}",
            f"- **Статус**: {_fmt(task.get('state'))}",
            f"- **Приоритет**: {_fmt(task.get('priority'))}",
            f"- **Исполнитель**: {_fmt(assignee.get('fullName'))}",
            f"- **Спринт**: {_fmt(sprint.get('name'))}",
            "",
            "### Описание задачи",
            description,
        ]
    )


def _md_cell(value: Any) -> str:
    return str(value if value not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def render_context_markdown(context: dict[str, Any]) -> str:
    targets = context["targets"]
    lines = [
        "# Review context",
        "",
        "## Targets",
        "",
        "| Kind | Repo | Path | MR | Source branch | Base | Head | Merge base | Scope |",
        "|------|------|------|----|---------------|------|------|------------|-------|",
    ]
    for target in targets:
        mr_url = (target.get("mr") or {}).get("url", "—")
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in (
                    target["kind"], target["repo"], f"`{target['path']}`", mr_url,
                    target["source_branch"], target["base_ref"], target["head_ref"],
                    f"`{target['merge_base']}`", target["scope"],
                )
            )
            + " |"
        )
    lines.extend(["", "## Scope contract", "", context["scope_contract"], "", "## Primary task", ""])
    primary = context["primary_task"]
    lines.append(_task_markdown(primary.get("id"), primary.get("task")))
    if context.get("additional_information"):
        lines.extend(["", "## Additional information", "", context["additional_information"]])
    if context.get("related_tasks"):
        lines.extend(["", "## Related tasks"])
        for related in context["related_tasks"]:
            lines.extend(["", f"### {related['id']}", "", _task_markdown(related["id"], related.get("task"))])
    lines.extend(["", "## Repository state"])
    for target in targets:
        lines.extend(
            [
                "",
                f"### {target['repo']}",
                f"- Kind: {target['kind']}",
                f"- Path: `{target['path']}`",
                f"- Branch: `{target['source_branch']}`",
                f"- Scope: {target['scope']}",
                f"- In-scope files: {len(target['file_sets']['in_scope'])}",
            ]
        )
        if target.get("status"):
            lines.extend(["", "```text", target["status"], "```"])
        if target.get("untracked_files"):
            lines.extend(["", "Untracked files:", *[f"- `{item}`" for item in target["untracked_files"]]])
        if target.get("review_commands"):
            lines.extend(["", "Minimal review commands:", "```sh", *target["review_commands"], "```"])
    if context.get("warnings"):
        lines.extend(["", "## Preparation warnings", "", *[f"- {warning}" for warning in context["warnings"]]])
    return "\n".join(lines) + "\n"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def cleanup_workspace(path: Path, *, dry_run: bool = False, ignore_errors: bool = False) -> dict[str, Any]:
    supplied = path.expanduser().resolve()
    manifest_path = supplied if supplied.name == "manifest.json" else supplied / "manifest.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("tool") != TOOL_NAME or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ReviewError(f"Not a {TOOL_NAME} manifest: {manifest_path}")
    root = Path(str(manifest.get("root", ""))).resolve()
    if manifest_path.parent != root:
        raise ReviewError(f"Manifest root mismatch: {manifest_path}")
    marker = root / ".echat-mr-review-workspace"
    try:
        marker_id = marker.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ReviewError(f"Missing workspace ownership marker: {marker}") from error
    if marker_id != manifest.get("workspace_id") or root == Path(root.anchor) or len(root.parts) < 3:
        raise ReviewError(f"Unsafe workspace ownership data: {root}")
    plan = {"workspace": str(root), "worktrees": [item.get("path") for item in manifest.get("worktrees", [])]}
    if dry_run:
        return plan
    warnings: list[str] = []
    lock_root = Path(str(manifest.get("lock_root"))).expanduser().resolve()
    for item in reversed(manifest.get("worktrees", [])):
        try:
            source_repo = Path(item["source_repo"]).resolve()
            worktree = Path(item["path"]).resolve()
            if not _is_within(worktree, root):
                raise ReviewError(f"Refusing to remove worktree outside workspace: {worktree}")
            expected_prefix = f"refs/echat-mr-review/{manifest['workspace_id']}/"
            refs = [str(ref) for ref in item.get("refs", [])]
            if any(not ref.startswith(expected_prefix) for ref in refs):
                raise ReviewError(f"Refusing to delete unowned Git ref in manifest for {worktree}")
            if source_repo.exists():
                with repo_lock(lock_root, source_repo):
                    result = git(source_repo, "worktree", "remove", "--force", str(worktree), timeout=60, check=False)
                    if result.returncode != 0 and worktree.exists():
                        shutil.rmtree(worktree)
                    git(source_repo, "worktree", "prune", check=False)
                    for ref in refs:
                        git(source_repo, "update-ref", "-d", ref, check=False)
            elif worktree.exists():
                shutil.rmtree(worktree)
                warnings.append(f"Source repository missing; removed files but could not prune Git metadata: {source_repo}")
        except Exception as error:
            if not ignore_errors:
                raise
            warnings.append(str(error))
    try:
        shutil.rmtree(root)
    except OSError:
        if not ignore_errors:
            raise
    return {**plan, "warnings": warnings}
