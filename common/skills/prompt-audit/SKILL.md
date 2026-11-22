---
name: prompt-audit
description: Audit and prune agent instruction files (AGENTS.md, CLAUDE.md, GEMINI.md, local rules, project skills) for stale references, contradictions, environment caches, model no-ops, and context bloat. Use when asked to audit, trim, or optimize project agent context.
---

Read-only audit of a project's agent instruction files. Produce a prioritized report and proposed unified diffs; do not modify instruction files unless the user explicitly asks to apply changes.

Read [`../writing-for-agents/SKILL.md`](../writing-for-agents/SKILL.md) before proposing rewrites or disclosure splits.

## Process

### 1. Inventory active context

Find every instruction file in the target workspace:

- Always-loaded instruction files at repo root and nested directories: `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, `GEMINI.md`, `.gemini/GEMINI.md`, `.claude/rules/**`, `.agents/rules/**`, `.cursor/rules/**`.
- Project-local skills and custom commands: `.agents/skills/*/SKILL.md`, `.claude/skills/*/SKILL.md`, `.claude/commands/**`, `.pi/skills/*/SKILL.md`, `.gemini/skills/*/SKILL.md`.
- Disclosed references linked directly (one hop) from always-loaded files, to separate always-loaded context load from on-demand pointers.
- Global harness files (`~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md`, `~/.pi/agent/AGENTS.md`) read strictly to catch cross-layer duplication or contradictions. Do not propose edits to global files unless asked.

Record each file's path, loading tier (`always-loaded`, `scoped-nested`, `pointer-only`, `global-ref`), line count, and byte size.

Completion criterion: every instruction file and local skill in the workspace is accounted for with path, tier, and size.

### 2. Verify every claim against the repository

Inspect the real codebase before flagging any line. Check referenced paths, directories, scripts, package managers, runtime versions, build/test commands, and helper names against the actual repo tree and authoritative configs (`package.json`, `Makefile`, `pyproject.toml`, `go.mod`, lockfiles, CI configs, `.nvmrc`, linter configs).

Evaluate every always-loaded line and skill description across six passes, ordered by severity:

1. **Stale references & sediment**: paths, directories, scripts, flags, helpers, or architecture claims that no longer exist or contradict the current codebase.
   - Verify via file search or reading the referenced config/script.
   - Action: `delete` dead claims or `update` to the real target.
2. **Contradictions & duplication**: rules that conflict within a file, between root and nested files, or with global instructions; the same rule restated in multiple places instead of a single source of truth.
   - Verify by quoting both conflicting or duplicate sites (`file:line`).
   - Action: resolve to one authoritative location and delete duplicates.
3. **Environment cache**: facts the agent can read in one cheap lookup from authoritative files (stack list, Node/Python version, obvious directory tree, standard scripts or formatter/linter rules already enforced by tooling).
   - Verify by naming the authoritative file that already states the fact (`package.json`, `.eslintrc`, `tsconfig.json`, etc.).
   - Action: `delete` unless lookup is genuinely expensive or misleading.
4. **Model no-ops & prompt fossils**: directives modern reasoning/coding models (Gemini 4 Neon, Claude, GPT-5/Codex) already follow by default or control via native settings:
   - Reasoning/effort mantras (`Think hard`, `Be thorough`, `Step by step`, `Keep going until it's done`) where native thinking depth (`thinking_level` / effort) governs reasoning and text mantras add noise or burn thinking tokens.
   - Aggressive shouting (`CRITICAL:`, `IMPORTANT: always`, `NEVER EVER`) where calm rules or checkable criteria work better.
   - Legacy anti-tool bias or formatting workarounds written for older models.
   - Action: `delete` the entire sentence rather than trimming words; replace fuzzy quality wishes with checkable commands or explicit invariants if needed.
5. **Sprawl & disclosure candidates**: branch-specific procedures, subsystem details, or long examples sitting in an always-loaded root file that only apply to some tasks.
   - Verify that the block is not needed on every turn.
   - Action: `disclose` into a sibling doc, nested directory `AGENTS.md`, or local skill behind a one-line context pointer stating what it is and when to open it.
6. **Weak pointers & fuzzy bounds**: skill descriptions or doc pointers that waste tokens on synonyms or body restatements, or workflow steps ending on uncheckable bounds (`make sure it works`, `clean code`).
   - Action: tighten pointers (front-loaded trigger, one trigger per distinct branch) and sharpen bounds into checkable criteria.

Completion criterion: every always-loaded file and project skill description has been checked line by line against the repo and all six passes, and every candidate finding carries concrete evidence.

### 3. Protect load-bearing lines

Before finalizing any deletion, test whether removing the line could cause a real failure the repo and tooling do not prevent. Explicitly preserve:

- Unwritten invariants and hidden external consumers (for example, a legacy folder still serving another client).
- Non-obvious safety, data, or environment boundaries.
- Custom verification, build, or migration commands that differ from standard defaults.
- Deliberate deviations from framework or language conventions.

If a line looks stale or redundant but cannot be proven safe to drop from the codebase, mark it `needs confirmation` instead of proposing silent deletion.

### 4. Produce the report and diffs

Output in this order:

1. **Context budget summary**: table of always-loaded files with current lines/bytes, proposed lines/bytes, and net reduction.
2. **Prioritized findings**: grouped by pass (1 to 6). Each finding uses `file:line`, quoted text, evidence from the repo/config, and action (`delete`, `disclose`, `rewrite`, `update`, `needs confirmation`). Drop any finding without concrete evidence.
3. **Kept (load-bearing)**: brief list of key rules intentionally preserved and why.
4. **Proposed diffs**: clean unified diff per affected file (and any newly proposed disclosed file if splitting).
5. **Next step**: ask which proposed edits the user wants applied.
