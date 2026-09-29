---
name: subagents
description: Use whenever deciding to delegate to, spawning, prompting, selecting models for, or managing subagents.
---

# Subagents

Each subagent is headless, has its own context window, cannot see the parent conversation,
cannot ask the user, and cannot spawn subagents or workflows. Give every child a self-contained
prompt with paths, constraints, and the expected report.

## Delegation policy

- Use the `pi` harness unless the user requests another harness.
- Do not use more than 2 subagents simultaneously.

## Model selection

For Pi and Codex subagents, choose between
`openai-codex/gpt-5.6-luna` (Luna) and `openai-codex/gpt-6.1-sol` (Sol).

| Model | Speed | Intellect | Price efficiency |
|:------|:-----:|:---------:|:----------------:|
| Luna  |  4/5  |    2/5    |       5/5        |
| Sol   |  2/5  |    4/5    |       2/5        |

Higher price efficiency means lower cost.

- Use Luna by default when the work is bounded and its completion criteria are directly checkable.
- Use Sol when success primarily depends on judgment, synthesis, or resolving ambiguity.
- Use the lowest reasoning effort sufficient for the required depth and confidence.
- Do not exceed `xhigh` for Luna or `medium` for Sol.
- Do not increase reasoning effort to compensate for an unclear prompt
  or an excessively broad scope; refine or split the task instead.
- An explicit user model or reasoning choice overrides these defaults.

## Pi Harness

**Harness:** `pi`
**Prompt nicknames:** “pi”, “pi agent”, “pi coding agent”, “pi subagent”
It inherits the parent model and thinking level when `model` or `reasoning_effort` is omitted.

For an explicit model selection, check `pi --list-models`. Prefer `provider/model-id`;
a bare model id only works when unambiguous.

**Thinking budgets:** `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
These map directly to pi thinking levels.

## Codex Harness

**Harness:** `codex`
**Prompt nicknames:** “codex”, “Codex CLI”, “codex agent”, “codex subagent”
Model names and availability come from the installed Codex configuration.
Do not translate a Pi provider alias into a Codex model name by guesswork.

**Thinking budgets accepted by the extension:** `off`, `minimal`, `low`, `medium`,
`high`, `xhigh`, `max`. Codex maps these to the nearest effort supported by the selected model;
`off`/`minimal` become `minimal`, while `max` becomes the highest extension-supported Codex effort.

Requires the Codex CLI to be installed and authenticated.

## Spawn and Manage

Call `subagent_spawn` with a complete `prompt`, short `name`, chosen `harness`,
and optional `working_dir`, `model`, and `reasoning_effort`.
The active task budget may be lower than the tool limit.

- `subagent_check({ id })`: peek without blocking.
- `subagent_list()`: list all runs.
- `subagent_wait({ ids })`: block only when results are required to proceed.
- `subagent_cancel({ ids })`: stop runs while preserving partial transcripts.
- `/subagents`: inspect or take over a run interactively.

Results return automatically. After spawning, continue useful parent work
instead of immediately waiting.
