---
name: review-gpt
description: Get an independent second-opinion code review of the current task's changes from a GPT model via the pi agent CLI. Use when the user invokes /review-gpt.
disable-model-invocation: true
argument-hint: "[model=openai-codex/gpt-6-astra] [thinking=medium] [extra focus]"
---

Run a read-only review through `pi`, then triage its findings for the user. Never apply fixes from the review yourself: the output of this skill is a proposal.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6-astra`. Check unknown ids with `pi --list-models <search>`.
- `thinking=<level>`: default `medium` (`off|minimal|low|medium|high|xhigh|max`).
- Any remaining text is an extra review focus.

## 2. Write the brief

Write the brief to a temp file (`mktemp /tmp/review-gpt.XXXXXX.md`). The reviewer sees nothing of this conversation, so the brief must stand alone:

- Repository path(s) and how to see the change: base ref / commit range, or "uncommitted working tree" (`git diff`, `git status`). For multiple repositories, list each.
- Goal of the change: ticket id and its requirement, in your own summary.
- Agreed constraints and deliberate decisions, so they are not reported as defects.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files; inspect the diff and surrounding code; report findings ordered by severity, each with `file:line`, the problem, why it matters, and a suggested fix; say explicitly when nothing significant is found. Answer in Russian.

Done when a reader with only the brief and the repository could review the change without guessing its intent.

## 3. Run pi in background

Run from the repository root with `run_in_background: true`:

```bash
pi -p --no-session --model "$MODEL" --thinking "$THINKING" --tools read,bash @"$BRIEF"
```

stdout contains only the agent's final answer. Do not poll; wait for the completion notification.

## 4. Triage

Verify every finding against the actual code before judging it. Report to the user:

- **Стоит исправить**: confirmed problems, with the proposed change.
- **Спорно**: real trade-offs or needs the user's decision, with your view.
- **Отклонить**: false positives or contradictions of agreed decisions, with the evidence.

Done when every finding sits in exactly one group with its reason. Then stop and wait for the user to choose what to fix. Delete the brief file.
