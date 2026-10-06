/**
 * mr-echat — commit + push + создание MR через glab.
 * Если MR для текущей ветки уже есть, может дополнить его описание новыми изменениями.
 *
 * Заменяет agent/prompts/mr-echat.md: все механические шаги (git, glab,
 * файловый I/O, цикл подтверждения title) выполняются детерминированно
 * в коде. Commit title генерируется отдельным complete() по diff. MR description
 * генерируется отдельным запросом к gpt-5.6-luna с полным текстовым snapshot
 * текущей сессии на момент запуска команды.
 *
 * Использование:
 *   /mr-echat [task-branch] [--name=<task-branch>] [--cwd <repo-path>]
 *
 *   task-branch — опционально: название ветки задачи. Если команда запущена
 *   новая feature-ветка создаётся от базовой, task-ветка от текущей feature/T-ветки.
 *   Поддерживаются только feature/T-123 и task/T-124.
 *   --cwd — опционально: git-репозиторий, относительно cwd сессии, абсолютный или через ~/.
 *   --name — опционально: существующая ветка, на которую нужно переключиться,
 *   или имя новой ветки. Новая feature-ветка создаётся от локальной master/main,
 *   новая task-ветка только от текущей родительской feature/T-ветки.
 */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { MrEchatPanel } from "./shared/mr-echat-panel.ts";
import {
  complete,
  type Api,
  type AssistantMessage,
  type Message,
  type Model,
  type ProviderHeaders,
} from "@earendil-works/pi-ai/compat";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TASK_BRANCH_RE = /^(feature|task)\/(T-\d+)$/i;
const FEATURE_BRANCH_RE = /^feature\/T-\d+$/i;
const TASK_TEMPLATE_URL_RE = /https?:\/\/(?:spacehub\.esoft\.tech\/entity\/T-|(?:youtrack|urs)\.esoft\.tech\/issue\/EUTP-)(<[^>]+>|[^\s)<>"']*)/gi;
const TASK_PLACEHOLDER_SUFFIX_RE = /^(?:…|\.\.\.|XXX|<[^>]+>|\{\{[^}]+\}\})?$/i;
const TITLE_MAX_ATTEMPTS = 3;
const MR_DESC_TMP = "/tmp/mr_description.md";
const GENERATION_MODELS = [
  { provider: "openai-codex", id: "gpt-5.6-luna" },
  { provider: "openrouter", id: "openai/gpt-5.6-luna" },
] as const;
const GENERATION_THINKING = "high";
const LARGE_READ_RESULT_CHARS = 12_000;
const LARGE_DIFF_CHARS = 400_000;
const PROGRESS_WIDGET_KEY = "mr-echat-progress";
const PROGRESS_INTERVAL_MS = 1_000;
const BASE_BRANCHES = new Set(["main", "master", "develop", "dev", "stage", "staging"]);
const GENERATED_DIFF_EXCLUDES = [
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
];

const TITLE_SYSTEM_PROMPT = `You are a commit message generator for an EChat project.
Given a git diff, output exactly one commit title.

Commit title rules:
- English, lowercase, imperative mood: add/fix/make/update/remove
- Briefly describes the essence of changes
- Ends with " #T-123"
- Examples from the repo:
  add cross-app text formatting copy-paste #T-145771
  fix chat closing animation on mobile #T-146265
  add invitation links #T-115210
  fix formatting toolbar on Android #T-144804

Output format (strict):
TITLE: <commit title>`;

// ---------------------------------------------------------------------------
// Instructions for the dedicated MR description request
// ---------------------------------------------------------------------------

const MR_DESCRIPTION_STYLE_RULES = `
Style and content rules:
- Write natural, clear Russian for a human reviewer, without bureaucratic language.
- Start with 1–2 sentences describing the user-visible result.
- For a bug fix, explain the cause and why the change removes the symptom.
- Then list the key implementation changes in 2–6 concise bullet points.
- Start each change bullet with an action: "Исправлено", "Добавлено", "Изменено" or "Сохранено".
- Mention affected modules or files only when this helps the reviewer understand the change.
- Describe behavior and purpose, not a line-by-line summary of the diff.
- Do not write vague phrases such as "изменён код", "добавлена логика" or "обновлены файлы" without explaining the result.
- Do not present a plan, hypothesis, abandoned approach or unverified assumption as completed work.
- Include only checks that were actually run. Name the command or scenario and its result.
- If browser, device or manual verification was not performed, say so explicitly.
- Do not duplicate the same fact across sections.

The change summary should follow this shape:
### Краткое описание изменений

<user-visible result and, for a bug fix, its cause>

- <action, behavior and purpose; affected module/file when useful>
- <action, behavior and purpose; affected module/file when useful>
`;

const UPDATE_MR_DESC_PROMPT = `Update an existing GitLab MR description for an EChat project.
Use the preceding session as context about the task, its intent, implementation decisions, and verification.
Given the current MR description and the complete diff of the MR branch against its target branch, output the full updated MR description in Russian.

Rules:
- Keep existing useful facts, section names and order.
- Do not rewrite existing text merely for style.
- Treat the MR as one final change set, not as a sequence of commits or intermediate edits.
- Describe only the net result visible in the complete MR diff against the target branch.
- Do not describe an intermediate change as added and later removed. If a function, file or behavior is absent from the final diff, do not mention its temporary existence or removal.
- When updating an existing description, reconcile it with the final MR diff: remove or rewrite facts that are no longer true instead of preserving a stale history of intermediate changes.
- Add only information supported by the complete MR diff.
- Use session context only to explain intent and checks that actually happened.
- Do not include planned, abandoned, or unverified work from the session.
- Do not duplicate existing items.
- If the description has no "### Краткое описание изменений", create it in place of "На что обратить внимание при ревью и тестировании".
- If that section already exists, preserve its useful items and add only new non-duplicate items.
- Preserve mandatory sections and remove HTML/markdown comments.
- Keep Russian text.
- Do not call tools.

${MR_DESCRIPTION_STYLE_RULES}

Output format (strict):
DESC:
<full updated MR description>`;

const MR_DESC_PROMPT = `Generate an MR description for an EChat project.
Use the preceding session as context about the task, its intent, implementation decisions, and verification.
Given the complete diff of an MR branch against its target branch and an MR template, output exactly the filled MR description in Russian.

MR description rules:
- Preserve the template's section names and order, and fill only its placeholders.
- Treat the MR as one final change set, not as a sequence of commits or intermediate edits.
- Describe only the net result visible in the complete MR diff against the target branch.
- Do not describe an intermediate change as added and later removed. If a function, file or behavior is absent from the final diff, do not mention its temporary existence or removal.
- Treat the complete MR diff as the source of truth for implemented changes.
- Use session context only to explain intent and checks that actually happened; do not quote the conversation.
- Do not include planned, abandoned, or unverified work from the session.
- Replace "На что обратить внимание при ревью и тестировании" with the change summary described below.
- Remove HTML/markdown comments from the template.
- Keep Russian text.
- If no migrations — keep "Нет.".
- Do not call tools.

${MR_DESCRIPTION_STYLE_RULES}

Verified work context:
Use the preceding session only for the user-visible result, confirmed implementation decisions and checks that actually passed. If a detail is not supported by the diff or a completed check, omit it.

Output format (strict):
DESC:
<filled MR description>`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type LogFn = (event: string, details?: Record<string, unknown>) => void;

type CommandArgs = {
  taskBranch?: string;
  name?: string;
  cwd?: string;
};

type SessionSnapshot = {
  sessionId: string;
  text: string;
};

type SessionGenerationState = {
  active: boolean;
};

type GenerationAuth = {
  apiKey: string;
  headers?: ProviderHeaders;
};

function textContent(content: any): string {
  const parts = Array.isArray(content) ? content : [content];
  return parts
    .map((part: any) => typeof part === "string" ? part : part?.type === "text" ? part.text : "")
    .filter((text: unknown): text is string => typeof text === "string")
    .join("\n")
    .trim();
}

function assistantMessageText(message: any): string {
  return message?.role === "assistant" ? textContent(message.content) : "";
}

class WorkflowCancelled extends Error {}

type WorkflowContext = ExtensionCommandContext & {
  panel?: MrEchatPanel;
  runSignal: AbortSignal;
};

/** В TUI прогресс остаётся внутри панели; в других режимах используется widget. */
async function withProgress<T>(
  ctx: WorkflowContext,
  message: string,
  operation: (signal?: AbortSignal) => Promise<T>,
  cancellable = false,
): Promise<T> {
  if (ctx.panel) {
    const progressSignal = ctx.panel.progress(message, cancellable);
    const signal = progressSignal ? AbortSignal.any([ctx.runSignal, progressSignal]) : ctx.runSignal;
    try {
      const result = await operation(signal);
      if (progressSignal?.aborted) ctx.ui.notify("Генерация отменена", "info");
      return result;
    } finally {
      ctx.panel.progress(undefined);
    }
  }

  let dotCount = 1;
  const render = () => ctx.ui.setWidget(PROGRESS_WIDGET_KEY, [`${message}${".".repeat(dotCount)}`], { placement: "aboveEditor" });
  render();

  const timer = setInterval(() => {
    dotCount = dotCount % 3 + 1;
    render();
  }, PROGRESS_INTERVAL_MS);
  timer.unref?.();

  try {
    return await operation(ctx.runSignal);
  } finally {
    clearInterval(timer);
    ctx.ui.setWidget(PROGRESS_WIDGET_KEY, undefined);
  }
}

/**
 * Подготовить текстовый snapshot сессии для отдельной модели.
 * Thinking, tool calls и изображения не нужны для описания MR. Большие read
 * results намеренно пропускаются, чтобы контекст не превращался в дамп файлов.
 */
function captureSessionSnapshot(ctx: any): SessionSnapshot {
  const sections: string[] = [];
  const entries = ctx.sessionManager?.getBranch?.() ?? [];

  for (const entry of entries) {
    if (entry?.type === "compaction" || entry?.type === "branch_summary") {
      const summary = typeof entry.summary === "string" ? entry.summary.trim() : "";
      if (summary) sections.push(`[SESSION SUMMARY]\n${summary}`);
      continue;
    }

    if (entry?.type === "custom_message") {
      const content = textContent(entry.content);
      if (content) sections.push(`[SESSION MESSAGE]\n${content}`);
      continue;
    }

    if (entry?.type !== "message") continue;
    const message = entry.message;
    const role = message?.role;
    if (role === "user") {
      const content = textContent(message.content);
      if (content) sections.push(`[USER]\n${content}`);
    } else if (role === "assistant") {
      const content = assistantMessageText(message);
      if (content) sections.push(`[ASSISTANT]\n${content}`);
    } else if (role === "toolResult") {
      const content = textContent(message.content);
      if (!content) continue;
      if (message.toolName === "read" && content.length > LARGE_READ_RESULT_CHARS) {
        sections.push("[TOOL RESULT: read]\n[large read output omitted]");
      } else {
        sections.push(`[TOOL RESULT: ${message.toolName || "unknown"}]\n${content}`);
      }
    } else if (role === "bashExecution") {
      const command = typeof message.command === "string" ? message.command : "";
      const output = typeof message.output === "string" ? message.output : "";
      const content = [command && `Command: ${command}`, output && `Output:\n${output}`].filter(Boolean).join("\n");
      if (content) sections.push(`[BASH EXECUTION]\n${content}`);
    }
  }

  return {
    sessionId: String(ctx.sessionManager?.getSessionId?.() ?? ""),
    text: sections.join("\n\n") || "[empty session]",
  };
}

/** Разобрать позиционную ветку, --name и опциональную рабочую директорию. */
function parseCommandArgs(raw: string): CommandArgs {
  const parts = raw.trim().split(/\s+/).filter(Boolean);
  let taskBranch: string | undefined;
  let name: string | undefined;
  let cwd: string | undefined;

  for (let index = 0; index < parts.length; index++) {
    const part = parts[index];
    if (part === "--cwd") {
      cwd = parts[++index];
      if (!cwd) throw new Error("После --cwd нужно указать путь к репозиторию");
    } else if (part.startsWith("--cwd=")) {
      cwd = part.slice("--cwd=".length);
      if (!cwd) throw new Error("После --cwd= нужно указать путь к репозиторию");
    } else if (part === "--name") {
      name = parts[++index];
      if (!name) throw new Error("После --name нужно указать название ветки");
    } else if (part.startsWith("--name=")) {
      name = part.slice("--name=".length);
      if (!name) throw new Error("После --name= нужно указать название ветки");
    } else if (part.startsWith("-")) {
      throw new Error(`Неизвестный аргумент: ${part}`);
    } else if (!taskBranch) {
      taskBranch = part;
    } else {
      throw new Error(`Лишний аргумент: ${part}`);
    }
  }

  if (taskBranch && name) {
    throw new Error("Нельзя одновременно указывать позиционную ветку и --name");
  }

  return { taskBranch, name, cwd };
}

/** Не писать содержимое MR в лог вместе с аргументами glab. */
function sanitizeExecArgs(args: string[]): string[] {
  const sanitized = [...args];
  const descriptionIndex = sanitized.indexOf("--description");
  if (descriptionIndex >= 0 && descriptionIndex + 1 < sanitized.length) {
    sanitized[descriptionIndex + 1] = `<redacted:${sanitized[descriptionIndex + 1].length} chars>`;
  }
  return sanitized;
}

async function withTiming<T>(
  log: LogFn,
  event: string,
  details: Record<string, unknown>,
  operation: () => Promise<T>,
): Promise<T> {
  const startedAt = Date.now();
  log(`${event}:start`, details);
  try {
    const result = await operation();
    log(`${event}:end`, { durationMs: Date.now() - startedAt });
    return result;
  } catch (error: any) {
    log(`${event}:error`, { durationMs: Date.now() - startedAt, error: error?.message ?? String(error) });
    throw error;
  }
}

/** Выполнить запрос основной моделью или той же моделью через OpenRouter. */
async function completeWithFallback(
  ctx: any,
  event: string,
  log: LogFn,
  request: (model: Model<Api>, auth: GenerationAuth) => Promise<AssistantMessage>,
  signal?: AbortSignal,
): Promise<AssistantMessage | null> {
  const failures: string[] = [];

  for (let index = 0; index < GENERATION_MODELS.length; index++) {
    if (signal?.aborted) return null;
    const candidate = GENERATION_MODELS[index];
    const label = `${candidate.provider}/${candidate.id}`;
    const model = ctx.modelRegistry.find(candidate.provider, candidate.id);

    if (!model) {
      failures.push(`${label}: модель не найдена`);
    } else {
      try {
        const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
        if (!auth.ok || !auth.apiKey) {
          failures.push(`${label}: нет авторизации`);
        } else {
          const response = await withTiming(log, event, { model: label }, () => request(model, auth));
          if (signal?.aborted || response.stopReason === "aborted") return null;
          if (response.stopReason !== "error") return response;

          failures.push(`${label}: ${response.errorMessage || "ошибка запроса"}`);
        }
      } catch (error: any) {
        if (signal?.aborted) return null;
        failures.push(`${label}: ${error?.message ?? String(error)}`);
      }
    }

    if (signal?.aborted) return null;
    const fallback = GENERATION_MODELS[index + 1];
    if (fallback) {
      const fallbackLabel = `${fallback.provider}/${fallback.id}`;
      log(`${event}:fallback`, {
        failedModel: label,
        fallbackModel: fallbackLabel,
        reason: failures[failures.length - 1],
      });
      ctx.ui.notify(
        `Модель ${label} недоступна, пробую ${fallbackLabel}`,
        "warning",
      );
    }
  }

  log(`${event}:all-providers-failed`, { failures });
  ctx.ui.notify(`Все модели генерации недоступны: ${failures.join("; ")}`, "error");
  return null;
}

/** Вытащить ровно один T-ID из канонического имени ветки. */
function extractTaskId(branch: string): string | null {
  return TASK_BRANCH_RE.exec(branch)?.[2]?.toUpperCase() ?? null;
}

function branchKind(branch: string): "feature" | "task" | null {
  const kind = TASK_BRANCH_RE.exec(branch)?.[1]?.toLowerCase();
  return kind === "feature" || kind === "task" ? kind : null;
}

/** Найти последнее сообщение коммита по этой задаче в текущей ветке. */
async function getPreviousCommitTitle(exec: ExecFn, taskId: string): Promise<string | null> {
  const result = await exec("git", ["log", "-n", "1", "--no-merges", "--format=%s", "--fixed-strings", `--grep=${taskId}`]);
  const title = result.stdout.trim();
  return result.code === 0 && title ? title : null;
}

/** Получить MR-шаблон с подставленной SpaceHub-ссылкой. */
function readTemplate(cwd: string, taskId: string): string {
  const tmplPath = `${cwd}/.gitlab/merge_request_templates/Default.md`;
  const text = fs.readFileSync(tmplPath, "utf-8");
  return text.replace(TASK_TEMPLATE_URL_RE, (url: string, suffix: string) => {
    if (/^\d+(?:[?#].*)?$/.test(suffix)) return url;
    if (TASK_PLACEHOLDER_SUFFIX_RE.test(suffix)) return `https://spacehub.esoft.tech/entity/${taskId}`;
    throw new Error(`Не удалось разрешить плейсхолдер задачи в MR-шаблоне: ${url}`);
  });
}

/** Аргументы git diff с исключением generated-файлов из текста для LLM. */
function diffArgs(...args: string[]): string[] {
  return ["diff", ...args, "--", ".", ...GENERATED_DIFF_EXCLUDES.map((p) => `:(exclude,glob)${p}`)];
}

/** Определить, какой diff использовать, и получить его. */
async function getDiff(exec: ExecFn): Promise<string> {
  const cached = await exec("git", diffArgs("--cached", "--name-only"));
  const unstaged = await exec("git", diffArgs("--name-only"));

  const hasCached = cached.stdout.trim().length > 0;
  const hasUnstaged = unstaged.stdout.trim().length > 0;

  if (hasCached) {
    const diff = await exec("git", diffArgs("--cached"));
    return diff.stdout;
  }
  // staged пуст — анализируем всё unstaged
  const diff = await exec("git", diffArgs());
  return diff.stdout;
}

type ExistingMr = { ref: string; url: string; targetBranch: string | null };

type ParentBranchCandidate = { branch: string; distance: number };

function normalizeRemoteBranch(ref: string): string {
  return ref.replace(/^origin\//, "");
}

/** Найти родительскую feature/T-ветку по истории Git. */
async function getParentTaskBranch(exec: ExecFn, branch: string, log: LogFn): Promise<string | null> {
  const refsResult = await exec("git", ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]);
  if (refsResult.code !== 0) return null;

  const refs = [...new Set(refsResult.stdout.trim().split("\n").filter(Boolean))];
  const candidates = refs.filter((ref) => {
    const normalized = normalizeRemoteBranch(ref);
    return ref !== "origin/HEAD" && normalized !== branch && FEATURE_BRANCH_RE.test(normalized);
  });
  log("parent-branch:candidates", { totalRemoteRefs: refs.length, candidateCount: candidates.length });
  if (candidates.length === 0) return null;

  const originHead = (await exec("git", ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])).stdout.trim();
  const defaultRefs = [originHead, "origin/main", "origin/master", "origin/develop", "origin/dev", "origin/stage", "origin/staging", "main", "master", "develop", "dev", "stage", "staging"].filter(Boolean);
  let defaultMergeBase: string | null = null;
  for (const ref of defaultRefs) {
    const exists = await exec("git", ["rev-parse", "--verify", "--quiet", ref]);
    if (exists.code !== 0) continue;
    const base = await exec("git", ["merge-base", "HEAD", ref]);
    if (base.code === 0 && base.stdout.trim()) {
      defaultMergeBase = base.stdout.trim();
      break;
    }
  }

  const matches: ParentBranchCandidate[] = [];
  for (const ref of candidates) {
    const base = await exec("git", ["merge-base", "HEAD", ref]);
    const mergeBase = base.stdout.trim();
    if (base.code !== 0 || !mergeBase || mergeBase === defaultMergeBase) continue;

    if (defaultMergeBase) {
      const isAfterDefault = await exec("git", ["merge-base", "--is-ancestor", defaultMergeBase, mergeBase]);
      if (isAfterDefault.code !== 0) continue;
    }

    const distanceResult = await exec("git", ["rev-list", "--count", `${mergeBase}..HEAD`]);
    const distance = Number(distanceResult.stdout.trim());
    if (distanceResult.code !== 0 || !Number.isFinite(distance)) continue;
    matches.push({ branch: normalizeRemoteBranch(ref), distance });
  }

  matches.sort((a, b) => a.distance - b.distance || a.branch.localeCompare(b.branch));
  const nearest = matches[0];
  const tied = nearest && matches.some((candidate) => candidate.distance === nearest.distance && candidate.branch !== nearest.branch);
  const selected = tied ? null : nearest?.branch ?? null;
  log("parent-branch:selected", { selected, matchCount: matches.length, tied: Boolean(tied) });
  return selected;
}

/** Найти MR для текущей ветки. */
async function getExistingMr(exec: ExecFn, branch: string): Promise<ExistingMr | null> {
  const result = await exec("glab", ["mr", "list", "--source-branch", branch, "--output", "json"]);
  if (result.code !== 0 || !result.stdout.trim() || result.stdout.trim() === "[]") return null;

  try {
    const mrs = JSON.parse(result.stdout);
    if (!Array.isArray(mrs) || mrs.length === 0) return null;
    const mr = mrs[0];
    const url = mr.web_url || mr.webUrl || mr.url;
    const ref = String(mr.iid || mr.id || url || "");
    const targetBranch = typeof mr.target_branch === "string" ? mr.target_branch : null;
    return url && ref ? { ref, url, targetBranch } : null;
  } catch {
    return null;
  }
}

/** Получить текущее описание MR. */
async function getMrDescription(exec: ExecFn, mrRef: string): Promise<string | null> {
  const result = await exec("glab", ["mr", "view", mrRef, "--output", "json", "--jq", ".description"]);
  if (result.code !== 0) return null;

  return result.stdout.trim();
}

/** Получить diff всех изменений ветки относительно target branch существующего MR. */
async function getBranchDiff(exec: ExecFn, targetBranch: string | null): Promise<string> {
  if (!targetBranch) return "";

  await exec("git", ["fetch", "--quiet", "origin", targetBranch]);
  const remoteTarget = `origin/${targetBranch}`;
  const remoteDiff = await exec("git", diffArgs(`${remoteTarget}...HEAD`));
  if (remoteDiff.code === 0) return remoteDiff.stdout;

  const localDiff = await exec("git", diffArgs(`${targetBranch}...HEAD`));
  return localDiff.code === 0 ? localDiff.stdout : "";
}

/** Получить username текущего glab-пользователя. */
async function getGlabUser(exec: ExecFn): Promise<string | null> {
  try {
    const result = await exec("glab", ["api", "user"]);
    if (result.code === 0) {
      const user = JSON.parse(result.stdout);
      return user.username || null;
    }
  } catch {
    // glab не настроен или ошибка
  }
  return null;
}

/**
 * Обновить origin/<branch> и проверить, есть ли в удалённой ветке коммиты,
 * которых нет в локальном HEAD. Обновлённый ref также служит безопасной
 * точкой ожидания для последующего --force-with-lease.
 */
async function remoteHasCommitsMissingLocally(exec: ExecFn, branch: string): Promise<boolean> {
  const remoteRef = `refs/remotes/origin/${branch}`;
  const fetchResult = await exec("git", [
    "fetch",
    "--quiet",
    "origin",
    `+refs/heads/${branch}:${remoteRef}`,
  ]);
  if (fetchResult.code !== 0) return false;

  const missingResult = await exec("git", ["rev-list", "--count", `HEAD..${remoteRef}`]);
  const missingCount = Number(missingResult.stdout.trim());
  return missingResult.code === 0 && Number.isFinite(missingCount) && missingCount > 0;
}

/** Тип для exec-обёртки с фиксированным cwd. */
type ExecFn = (cmd: string, args: string[], opts?: Record<string, unknown>) => Promise<{ stdout: string; stderr?: string; code: number }>;

/** Последний текстовый ответ агента из текущей ветки сессии. */
function getLastAgentResponse(ctx: any): string | null {
  const entries = ctx.sessionManager?.getBranch?.() ?? [];
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (entry?.type !== "message" || entry.message?.role !== "assistant") continue;
    const content = entry.message.content;
    const text = (Array.isArray(content) ? content : [content])
      .map((part: any) => typeof part === "string" ? part : part?.type === "text" ? part.text : "")
      .filter(Boolean)
      .join("\n")
      .trim();
    if (text) return text;
  }
  return null;
}

/** Проверить выбранную директорию. Без явного пути при необходимости найти дочерний репозиторий. */
async function ensureGitRepo(
  pi: ExtensionAPI,
  ctx: WorkflowContext,
  requestedCwd?: string,
): Promise<string | null> {
  const sessionCwd = ctx.cwd || process.cwd();
  const expandedCwd = requestedCwd?.replace(/^~(?=$|[\\/])/, os.homedir());
  const cwd = expandedCwd ? path.resolve(sessionCwd, expandedCwd) : sessionCwd;

  if (requestedCwd) {
    try {
      if (!fs.statSync(cwd).isDirectory()) throw new Error("not a directory");
    } catch {
      ctx.ui.notify(`Директория не найдена: ${cwd}`, "error");
      return null;
    }
  }

  // Проверяем, является ли текущая папка git-репозиторием
  const check = await pi.exec("git", ["rev-parse", "--show-toplevel"], { cwd, signal: ctx.runSignal });
  if (check.code === 0) {
    return check.stdout.trim() || cwd;
  }

  if (requestedCwd) {
    ctx.ui.notify(`Не git-репозиторий: ${cwd}`, "error");
    return null;
  }

  // Не репозиторий — ищем дочерние папки с .git
  const lsResult = await withProgress(ctx, "Текущая папка не git-репозиторий. Ищу дочерние", () =>
    pi.exec("bash", ["-c", 'for d in */; do [ -d "$d/.git" ] && echo "${d%/}"; done'], { cwd, signal: ctx.runSignal }),
  );
  const dirs = lsResult.stdout.trim().split("\n").filter(Boolean);

  if (dirs.length === 0) {
    ctx.ui.notify("Не найдено git-репозиториев в дочерних папках", "error");
    return null;
  }

  if (dirs.length === 1) {
    // Один репозиторий — используем без вопроса
    const selected = path.resolve(cwd, dirs[0]);
    ctx.ui.notify(`Автовыбор: ${dirs[0]}`, "info");
    return selected;
  }

  // Несколько — даём выбрать
  const selected = await ctx.ui.select("Выбери git-репозиторий", dirs);
  if (!selected) {
    return null; // пользователь отменил
  }

  return path.resolve(cwd, selected);
}

/** Вызвать LLM для генерации commit title. */
async function generateTitle(
  ctx: any,
  taskId: string,
  diff: string,
  lastAgentResponse: string | null,
  log: LogFn,
  progressMessage = "Генерирую заголовок коммита",
): Promise<string | null> {
  const diffBlock = diff;
  // ponytail: diff без ограничения, проблема — если модель не влезает в контекст
  if (diffBlock.length > LARGE_DIFF_CHARS) {
    ctx.ui.notify(`Diff большой (${diffBlock.length} символов). Модель может не справиться.`, "warning");
  }

  const userMessage: Message = {
    role: "user",
    content: [{ type: "text", text: [`Task: ${taskId}`, lastAgentResponse && `Last agent response:\n${lastAgentResponse}`, `Git diff:`, diffBlock].filter(Boolean).join("\n\n") }],
    timestamp: Date.now(),
  };

  const response = await withProgress(ctx, progressMessage, (signal) =>
    completeWithFallback(ctx, "llm:title", log, (model, auth) =>
      complete(
        model,
        { systemPrompt: TITLE_SYSTEM_PROMPT, messages: [userMessage] },
        { apiKey: auth.apiKey, headers: auth.headers, reasoningEffort: GENERATION_THINKING, signal },
      ),
      signal,
    ),
    true,
  );
  if (!response) return null;

  const text = response.content
    .filter((c: any): c is { type: "text"; text: string } => c.type === "text")
    .map((c: any) => c.text)
    .join("\n");

  const titleMatch = text.match(/^TITLE:\s*(.+?)$/m);
  if (!titleMatch) {
    ctx.ui.notify("LLM вернул ответ не по формату. TITLE: не найден.", "error");
    return null;
  }

  return titleMatch[1].trim();
}

/** Вызвать отдельную модель, не добавляя prompt и ответ генератора в основную сессию. */
async function generateDescriptionWithModel(
  ctx: any,
  prompt: string,
  sessionSnapshot: SessionSnapshot,
  generationState: SessionGenerationState,
  event: string,
  log: LogFn,
  signal?: AbortSignal,
): Promise<string | null> {
  if (generationState.active) {
    ctx.ui.notify("Генерация описания MR уже выполняется", "error");
    return null;
  }

  const userMessage: Message = {
    role: "user",
    content: [{ type: "text", text: prompt }],
    timestamp: Date.now(),
  };

  try {
    generationState.active = true;
    const response = await completeWithFallback(ctx, event, log, (model, auth) =>
      ctx.modelRegistry.streamSimple(
        model,
        {
          systemPrompt: [
            ctx.getSystemPrompt(),
            "You generate precise GitLab merge request descriptions. Do not call tools.",
          ].join("\n\n"),
          messages: [userMessage],
        },
        {
          apiKey: auth.apiKey,
          headers: auth.headers,
          reasoning: GENERATION_THINKING,
          sessionId: sessionSnapshot.sessionId,
          cacheRetention: "short",
          signal,
        },
      ).result(),
      signal,
    );
    if (!response) return null;

    const text = response.content
      .filter((part: any): part is { type: "text"; text: string } => part.type === "text")
      .map((part: { type: "text"; text: string }) => part.text)
      .join("\n")
      .trim();

    if (!text) ctx.ui.notify("Модель не вернула текст описания MR", "error");
    return text || null;
  } finally {
    generationState.active = false;
  }
}

/** Вызвать LLM для генерации MR description после выбора commit title. */
async function generateDescription(
  ctx: any,
  taskId: string,
  diff: string,
  template: string,
  sessionSnapshot: SessionSnapshot,
  generationState: SessionGenerationState,
  log: LogFn,
): Promise<string | null> {
  if (diff.length > LARGE_DIFF_CHARS) {
    ctx.ui.notify(`Diff большой (${diff.length} символов). Модель может не справиться.`, "warning");
  }

  const prompt = [
    MR_DESC_PROMPT,
    "Session snapshot at the moment /mr-echat started:",
    sessionSnapshot.text,
    `Task: ${taskId}`,
    "Template:",
    template,
    "Git diff:",
    diff,
  ].join("\n\n");

  const text = await withProgress(ctx, "Генерирую описание MR", (signal) =>
    generateDescriptionWithModel(ctx, prompt, sessionSnapshot, generationState, "llm:description", log, signal),
    true,
  );
  if (!text) return null;

  const descMatch = text.match(/^DESC:\s*([\s\S]*)$/m);
  if (!descMatch) {
    ctx.ui.notify("LLM вернул ответ не по формату. DESC: не найден.", "error");
    return null;
  }
  return descMatch[1].trim();
}

/** Составить описание существующего MR по его текущему описанию и итоговому diff ветки. */
async function generateUpdatedDescription(
  ctx: any,
  taskId: string,
  currentDescription: string,
  diff: string,
  sessionSnapshot: SessionSnapshot,
  generationState: SessionGenerationState,
  log: LogFn,
): Promise<string | null> {
  const prompt = [
    UPDATE_MR_DESC_PROMPT,
    "Session snapshot at the moment /mr-echat started:",
    sessionSnapshot.text,
    `Task: ${taskId}`,
    "Current MR description:",
    currentDescription,
    "Complete MR diff against target branch:",
    diff,
  ].join("\n\n");

  const text = await withProgress(ctx, "Обновляю описание существующего MR", (signal) =>
    generateDescriptionWithModel(ctx, prompt, sessionSnapshot, generationState, "llm:description-update", log, signal),
    true,
  );
  if (!text) return null;

  const descMatch = text.match(/^DESC:\s*([\s\S]*)$/m);
  if (!descMatch) {
    ctx.ui.notify("LLM вернул ответ не по формату. DESC: не найден.", "error");
    return null;
  }
  return descMatch[1].trim();
}

/** Цикл подтверждения commit title.
 *  Принимает уже сгенерированный первый вариант, чтобы избежать лишнего вызова complete(). */
async function confirmTitle(
  ctx: any,
  taskId: string,
  firstTitle: string,
  previousTitle: string | null,
  generateAnother: () => Promise<string | null>,
): Promise<string | null> {
  let title = firstTitle;
  let attempts = 1;

  while (true) {
    if (previousTitle) {
      const action = await ctx.ui.select("Заголовок коммита", [
        `Использовать сгенерированный: ${title}`,
        `Использовать существующий: ${previousTitle}`,
        "Сгенерировать другой вариант",
        "Ввести вручную",
      ]);
      if (!action) return null;
      if (action.startsWith("Использовать сгенерированный")) return title;
      if (action.startsWith("Использовать существующий")) return previousTitle;
      if (action === "Ввести вручную") {
        const manual = await ctx.ui.input("Введи название коммита (без #T-123):");
        if (manual) return `${manual.trim()} #${taskId}`;
        return null;
      }
    } else {
      const action = await ctx.ui.select("Заголовок коммита", [
        `Использовать сгенерированный: ${title}`,
        "Сгенерировать другой вариант",
        "Ввести вручную",
      ]);
      if (!action) return null;
      if (action.startsWith("Использовать сгенерированный")) return title;
      if (action === "Ввести вручную") {
        const manual = await ctx.ui.input("Введи название коммита (без #T-123):");
        if (manual) return `${manual.trim()} #${taskId}`;
        return null;
      }
    }

    if (attempts >= TITLE_MAX_ATTEMPTS) {
      const manual = await ctx.ui.input("Введи название коммита (без #T-123):");
      if (manual) return `${manual.trim()} #${taskId}`;
      return null;
    }

    const nextTitle = await generateAnother();
    if (!nextTitle) return null;
    title = nextTitle;
    attempts++;
  }
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
  const generationState: SessionGenerationState = { active: false };
  type RunState = { controller: AbortController; panel?: MrEchatPanel };
  let activeRun: RunState | undefined;

  pi.on("session_shutdown", () => {
    activeRun?.controller.abort();
    activeRun?.panel?.dispose();
  });

  const runWithPanel = async (
    commandCtx: ExtensionCommandContext,
    execute: (ctx: WorkflowContext) => Promise<void>,
  ) => {
    if (activeRun) {
      commandCtx.ui.notify("Предыдущая команда mr-echat ещё выполняется", "warning");
      return;
    }
    const run: RunState = { controller: new AbortController() };
    activeRun = run;
    try {
      await commandCtx.waitForIdle();
      run.controller.signal.throwIfAborted();
      if (commandCtx.mode !== "tui") {
        await execute({ ...commandCtx, runSignal: run.controller.signal });
        return;
      }
      await commandCtx.ui.custom<void>((tui, theme, keybindings, done) => {
        const panel = new MrEchatPanel(tui, theme, keybindings);
        run.panel = panel;
        let lastNotification: { message: string; type?: "info" | "warning" | "error" } | undefined;
        const ui = {
          ...commandCtx.ui,
          select: (title: string, options: string[]) => panel.select(title, options),
          input: (title: string, placeholder?: string) => panel.input(title, placeholder),
          confirm: async (title: string, message: string) => {
            const choice = await panel.select(`${title}. ${message}`, ["Да", "Нет"]);
            if (choice === undefined) throw new WorkflowCancelled();
            return choice === "Да";
          },
          notify: (message: string, type?: "info" | "warning" | "error") => {
            lastNotification = { message, type };
            panel.notify(message, type);
          },
        };
        // Дать Pi установить панель и фокус до начала асинхронного сценария.
        setImmediate(() => {
          void execute({ ...commandCtx, ui, panel, runSignal: run.controller.signal })
            .then(() => panel.finish())
            .then(() => {
              done();
              if (lastNotification && !run.controller.signal.aborted) {
                commandCtx.ui.notify(lastNotification.message, lastNotification.type);
              }
            })
            .catch((error: unknown) => {
              commandCtx.ui.notify(`Ошибка mr-echat: ${error instanceof Error ? error.message : String(error)}`, "error");
              done();
            });
        });
        return panel;
      });
    } catch (error: unknown) {
      if (!run.controller.signal.aborted) {
        commandCtx.ui.notify(`Ошибка mr-echat: ${error instanceof Error ? error.message : String(error)}`, "error");
      }
    } finally {
      activeRun = undefined;
    }
  };

  pi.on("tool_call", () => {
    if (!generationState.active) return;
    return { block: true, reason: "MR description generation must not call tools" };
  });

  pi.on("input", (_event, ctx) => {
    if (!generationState.active) return;
    ctx.ui.notify("Дождись завершения генерации описания MR", "warning");
    return { action: "handled" };
  });

  pi.registerCommand("mr-echat", {
    description: "Commit + push + создать MR через glab; [ветка] [--name=ветка] [--cwd путь]",
    handler: (args, commandCtx) => runWithPanel(commandCtx, async (ctx) => {
      const log: LogFn = () => {};
      log("run:start", { cwd: ctx.cwd || process.cwd(), args: args.trim() });
      try {
        if (generationState.active) {
          ctx.ui.notify("Предыдущая генерация описания MR ещё выполняется", "warning");
          return;
        }
        const { taskBranch, name, cwd: requestedCwd } = parseCommandArgs(args);
        const lastAgentResponse = getLastAgentResponse(ctx);
        const sessionSnapshot = captureSessionSnapshot(ctx);

        // 0. Определить рабочую директорию (git-репозиторий)
        const repoDir = await ensureGitRepo(pi, ctx, requestedCwd);
        if (!repoDir) return;
        log("repo:selected", { repoDir, explicit: Boolean(requestedCwd) });
        ctx.panel?.setContext(path.basename(repoDir));

        // Обёртка pi.exec с фиксированным cwd
        const exec: ExecFn = async (cmd, args, opts) => {
          const commandStartedAt = Date.now();
          const safeArgs = sanitizeExecArgs(args);
          log("exec:start", { cmd, args: safeArgs });
          try {
            ctx.runSignal.throwIfAborted();
            const result = await pi.exec(cmd, args, { ...opts, cwd: repoDir, signal: ctx.runSignal });
            log("exec:end", {
              cmd,
              args: safeArgs,
              durationMs: Date.now() - commandStartedAt,
              code: result.code,
              stdoutChars: result.stdout.length,
              stderrChars: result.stderr?.length ?? 0,
            });
            return result;
          } catch (error: any) {
            log("exec:error", {
              cmd,
              args: safeArgs,
              durationMs: Date.now() - commandStartedAt,
              error: error?.message ?? String(error),
            });
            throw error;
          }
        };

        // 1. Проверить выбранную ветку до переключения или создания.
        let branchResult = await exec("git", ["branch", "--show-current"]);
        if (branchResult.code !== 0 || !branchResult.stdout.trim()) {
          ctx.ui.notify("Не удалось определить текущую ветку", "error");
          return;
        }
        let branch = branchResult.stdout.trim();
        let createdTaskParent: string | null = null;
        const requestedBranch = name ?? taskBranch;
        if (requestedBranch && !TASK_BRANCH_RE.test(requestedBranch)) {
          ctx.ui.notify(`Ожидалось точное имя feature/T-123 или task/T-123: ${requestedBranch}`, "error");
          return;
        }
        if (requestedBranch && requestedBranch !== branch) {
          const validBranch = await exec("git", ["check-ref-format", "--branch", requestedBranch]);
          if (validBranch.code !== 0) {
            ctx.ui.notify(`Некорректное название ветки: ${requestedBranch}`, "error");
            return;
          }

          const localBranch = await exec("git", ["show-ref", "--verify", "--quiet", `refs/heads/${requestedBranch}`]);
          const remoteBranch = localBranch.code === 0
            ? null
            : await exec("git", ["show-ref", "--verify", "--quiet", `refs/remotes/origin/${requestedBranch}`]);

          let switchArgs: string[];
          let base = branch;
          if (localBranch.code === 0) {
            switchArgs = ["switch", requestedBranch];
          } else if (remoteBranch?.code === 0) {
            switchArgs = ["switch", "--track", "-c", requestedBranch, `origin/${requestedBranch}`];
          } else {
            if (branchKind(requestedBranch) === "task") {
              if (!FEATURE_BRANCH_RE.test(branch)) {
                ctx.ui.notify("Новая task/T-ветка создаётся только от текущей родительской feature/T-ветки", "error");
                return;
              }
              createdTaskParent = branch;
            } else if (name) {
              const master = await exec("git", ["show-ref", "--verify", "--quiet", "refs/heads/master"]);
              const main = master.code === 0 ? null : await exec("git", ["show-ref", "--verify", "--quiet", "refs/heads/main"]);
              if (master.code !== 0 && main?.code !== 0) {
                ctx.ui.notify("Не найдена локальная master/main — не могу создать новую feature-ветку", "error");
                return;
              }
              base = master.code === 0 ? "master" : "main";
            } else if (!BASE_BRANCHES.has(branch)) {
              ctx.ui.notify("Новую feature/T-ветку нужно создавать от базовой ветки", "error");
              return;
            }
            switchArgs = ["switch", "-c", requestedBranch, base];
          }

          const switchResult = await exec("git", switchArgs);
          if (switchResult.code !== 0) {
            ctx.ui.notify(`Не удалось выбрать ветку ${requestedBranch}: ${switchResult.stderr || switchResult.stdout}`, "error");
            return;
          }
          branch = requestedBranch;
          ctx.ui.notify(
            localBranch.code === 0 || remoteBranch?.code === 0
              ? `Выбрана ветка ${branch}`
              : `Создана ветка ${branch} от ${base}`,
            "info",
          );
        }

        ctx.panel?.setContext(path.basename(repoDir), branch);

        // 2. Проверить каноническое имя ветки и извлечь T-ID.
        const taskId = extractTaskId(branch);
        const kind = branchKind(branch);
        if (!taskId || !kind) {
          ctx.ui.notify(`Ожидалось точное имя feature/T-123 или task/T-123: ${branch}`, "error");
          return;
        }

        // 3. Проверить существующий MR до генерации описания
        const existingMr = await getExistingMr(exec, branch);
        if (kind === "task" && existingMr && !FEATURE_BRANCH_RE.test(existingMr.targetBranch ?? "")) {
          ctx.ui.notify("MR задачи должен быть направлен в родительскую feature/T-ветку; текущий target не изменён", "error");
          return;
        }

        // 4. Получить diff
        const diff = await getDiff(exec);
        if (!diff.trim()) {
          if (!existingMr) {
            ctx.ui.notify("Нет изменений для коммита", "error");
            return;
          }

          const currentDescription = await getMrDescription(exec, existingMr.ref);
          if (currentDescription === null) {
            ctx.ui.notify("Не удалось прочитать текущее описание MR", "error");
            return;
          }

          const branchDiff = await getBranchDiff(exec, existingMr.targetBranch);
          if (!branchDiff.trim()) {
            ctx.ui.notify("Нет локальных изменений и не удалось получить diff ветки MR", "error");
            return;
          }

          ctx.panel?.setSteps(["Обновление описания MR"]);
          const updatedDescription = await generateUpdatedDescription(
            ctx,
            taskId,
            currentDescription,
            branchDiff,
            sessionSnapshot,
            generationState,
            log,
          );
          if (!updatedDescription) return;
          const updateResult = await withProgress(ctx, "Сохраняю описание MR", () =>
            exec("glab", ["mr", "update", existingMr.ref, "--description", updatedDescription]),
          );
          if (updateResult.code !== 0) {
            ctx.ui.notify(`Ошибка glab mr update: ${updateResult.stderr}`, "error");
            return;
          }
          ctx.ui.notify(`Описание MR обновлено по изменениям ветки: ${existingMr.url}`, "info");
          return;
        }

        // 5. Подготовить MR-шаблон, но описание генерировать только после выбора title
        let description: string | null = null;
        let template: string | null = null;
        let updateExistingMrDescription = false;
        const previousTitle = await getPreviousCommitTitle(exec, taskId);
        let targetBranch: string | null = null;
        if (!existingMr && kind === "task") {
          targetBranch = createdTaskParent ?? await getParentTaskBranch(exec, branch, log);
          if (!targetBranch) {
            ctx.ui.notify("Не удалось однозначно определить родительскую feature/T-ветку; MR не создан", "error");
            return;
          }
        }

        if (!existingMr) {
          try {
            template = readTemplate(repoDir, taskId);
          } catch (error: unknown) {
            ctx.ui.notify(`Ошибка MR-шаблона: ${error instanceof Error ? error.message : String(error)}`, "error");
            return;
          }
        }

        // 6. Определить commit title
        let commitTitle: string;
        const titleChoices = previousTitle
          ? [`Использовать существующее сообщение: ${previousTitle}`, "Сгенерировать название коммита", "Ввести своё"]
          : ["Сгенерировать название коммита", "Ввести своё"];
        const titleAction = await ctx.ui.select("Заголовок коммита", titleChoices);
        if (!titleAction) {
          ctx.ui.notify("Команда mr-echat отменена", "info");
          return;
        }

        if (titleAction.startsWith("Использовать существующее")) {
          commitTitle = previousTitle!;
        } else if (titleAction === "Ввести своё") {
          const manual = await ctx.ui.input("Введи название коммита (без #T-123):");
          if (!manual) {
            ctx.ui.notify("Заголовок коммита не задан — отмена", "warning");
            return;
          }
          commitTitle = `${manual.trim()} #${taskId}`;
        } else {
          const firstTitle = await generateTitle(ctx, taskId, diff, lastAgentResponse, log);
          if (!firstTitle) return;
          const confirmed = await confirmTitle(ctx, taskId, firstTitle, previousTitle, async () =>
            generateTitle(ctx, taskId, diff, lastAgentResponse, log, "Генерирую другой вариант"),
          );
          if (!confirmed) {
            ctx.ui.notify("Заголовок коммита не задан — отмена", "warning");
            return;
          }
          commitTitle = confirmed;
        }

        const titleText = commitTitle.replace(/(?<![A-Z0-9_-])#?(?:T-\d+|EUTP-\d+)(?![A-Z0-9_])/gi, " ").trim().replace(/\s+/g, " ");
        if (!titleText) {
          ctx.ui.notify("Название коммита содержит только ID задачи — отмена", "error");
          return;
        }
        commitTitle = `${titleText} #${taskId}`;
        ctx.panel?.setResult(commitTitle);
        const steps = ["· Описание MR", "· Commit", "· Push", "· MR"];
        ctx.panel?.setSteps(steps);
        if (existingMr) {
          updateExistingMrDescription = await ctx.ui.confirm("MR уже существует", "Дополнить описание MR новыми изменениями?");
        } else {
          description = await generateDescription(
            ctx,
            taskId,
            diff,
            template!,
            sessionSnapshot,
            generationState,
            log,
          );
          if (!description) return;
          fs.writeFileSync(MR_DESC_TMP, description, "utf-8");
        }

        steps[0] = existingMr
          ? updateExistingMrDescription ? "· Описание MR после push" : "✓ Описание MR без изменений"
          : "✓ Описание MR подготовлено";
        steps[1] = "⠋ Commit";
        ctx.panel?.setSteps(steps);

        // 7. Commit + push
        const cachedCheck = await exec("git", ["diff", "--cached", "--name-only"]);
        const hasCached = cachedCheck.stdout.trim().length > 0;
        const unstagedCheck = await exec("git", ["diff", "--name-only"]);
        const hasUnstaged = unstagedCheck.stdout.trim().length > 0;

        if (!hasCached && hasUnstaged) {
          // Добавляем всё unstaged
          const addResult = await withProgress(ctx, "Добавляю все изменения", () => exec("git", ["add", "-A"]));
          if (addResult.code !== 0) {
            ctx.ui.notify(`Ошибка git add: ${addResult.stderr}`, "error");
            return;
          }
        } else if (!hasCached) {
          ctx.ui.notify("Нет изменений для коммита", "error");
          return;
        }

        const commitResult = await withProgress(ctx, "Создаю коммит", () =>
          exec("git", ["commit", "-m", commitTitle]),
        );
        if (commitResult.code !== 0) {
          ctx.ui.notify(`Ошибка git commit: ${commitResult.stderr}`, "error");
          return;
        }

        steps[1] = "✓ Коммит создан";
        steps[2] = "⠋ Push";
        ctx.panel?.setSteps(steps);
        let pushResult = await withProgress(ctx, "Отправляю изменения", () =>
          exec("git", ["push", "-u", "origin", "HEAD"]),
        );
        if (pushResult.code !== 0 && await withProgress(ctx, "Проверяю удалённую ветку", () =>
          remoteHasCommitsMissingLocally(exec, branch),
        )) {
          const forceAction = await ctx.ui.select(
            "Удалённая ветка содержит коммиты, которых нет локально. Выполнить push with lease?",
            ["Нет", "Да — push --force-with-lease"],
          );
          if (forceAction !== "Да — push --force-with-lease") {
            ctx.ui.notify("Push отменён: удалённая ветка не перезаписана", "warning");
            return;
          }

          ctx.panel?.setSteps(steps);
          pushResult = await withProgress(ctx, "Отправляю изменения с force-with-lease", () =>
            exec("git", ["push", "--force-with-lease", "-u", "origin", "HEAD"]),
          );
        }
        if (pushResult.code !== 0) {
          ctx.ui.notify(`Ошибка git push: ${pushResult.stderr || pushResult.stdout}`, "error");
          return;
        }
        steps[2] = "✓ Изменения отправлены";
        steps[3] = existingMr ? "✓ MR существует" : "⠋ Создание MR";
        ctx.panel?.setSteps(steps);
        ctx.ui.notify("Запушено ✓", "info");
        if (!existingMr) {
          log("mr-creation:prepare:start");
        }

        // 8. Если MR уже был — при необходимости обновить описание и выйти
        if (existingMr) {
          if (updateExistingMrDescription) {
            steps[0] = "⠋ Обновление описания MR";
            ctx.panel?.setSteps(steps);
            const currentDescription = await getMrDescription(exec, existingMr.ref);
            if (currentDescription === null) {
              ctx.ui.notify("Не удалось прочитать текущее описание MR", "error");
              return;
            }
            const branchDiff = await getBranchDiff(exec, existingMr.targetBranch);
            if (!branchDiff.trim()) {
              ctx.ui.notify("Не удалось получить полный diff ветки MR", "error");
              return;
            }
            const updatedDescription = await generateUpdatedDescription(
              ctx,
              taskId,
              currentDescription,
              branchDiff,
              sessionSnapshot,
              generationState,
              log,
            );
            if (!updatedDescription) return;
            const updateResult = await withProgress(ctx, "Сохраняю описание MR", () =>
              exec("glab", ["mr", "update", existingMr.ref, "--description", updatedDescription]),
            );
            if (updateResult.code !== 0) {
              ctx.ui.notify(`Ошибка glab mr update: ${updateResult.stderr}`, "error");
              return;
            }
            steps[0] = "✓ Описание MR обновлено";
            ctx.panel?.setSteps(steps);
            ctx.ui.notify("Описание MR обновлено ✓", "info");
          }
          ctx.ui.notify(`MR уже существует: ${existingMr.url}`, "info");
          return;
        }

        // 9. Создать MR
        log("mr-creation:user:start");
        const descContent = description ?? fs.readFileSync(MR_DESC_TMP, "utf-8");
        const username = await withProgress(ctx, "Готовлю создание MR", async () => {
          const username = await getGlabUser(exec);
          log("mr-creation:user:end", { usernameFound: Boolean(username) });
          return username;
        });
        log("mr-creation:parent-branch:end", { targetBranch, branchKind: kind });

        const mrArgs = [
          "mr", "create",
          "--title", commitTitle,
          "--description", descContent,
          "--yes",
        ];
        if (username) {
          mrArgs.push("--assignee", username);
        }
        if (targetBranch) {
          mrArgs.push("--target-branch", targetBranch);
        }

        log("mr-creation:glab-create:start", { targetBranch, hasAssignee: Boolean(username) });
        const createResult = await withProgress(
          ctx,
          targetBranch ? `Создаю MR в ${targetBranch}` : "Создаю MR",
          () => exec("glab", mrArgs),
        );
        log("mr-creation:glab-create:end", { code: createResult.code });

        if (createResult.code !== 0) {
          ctx.ui.notify(`Ошибка glab mr create: ${createResult.stderr}`, "error");
          return;
        }

        steps[3] = "✓ MR создан";
        ctx.panel?.setSteps(steps);

        // 10. Вывести результат
        const webUrlMatch = createResult.stdout.match(/https:\/\/gitlab\.[^\s]+/);
        if (webUrlMatch) {
          ctx.ui.notify(`MR: ${webUrlMatch[0]}`, "info");
        } else {
          ctx.ui.notify(`MR создан. Вывод:\n${createResult.stdout.slice(0, 500)}`, "info");
        }
      } catch (err: any) {
        log("run:error", { error: err?.message ?? String(err) });
        if (err instanceof WorkflowCancelled) {
          ctx.ui.notify("Команда mr-echat отменена", "info");
        } else if (!ctx.runSignal.aborted) {
          ctx.ui.notify(`Ошибка mr-echat: ${err.message}`, "error");
        }
      } finally {
        log("run:end");
      }
    }),
  });
}
