---
name: review-plan-gpt
description: Get an independent second-opinion review of the current implementation plan from a GPT model via the pi agent CLI. Use when the user invokes /review-plan-gpt.
disable-model-invocation: true
argument-hint: "[model=openai-codex/gpt-6.1-sol] [thinking=high] [extra focus]"
---

Run a read-only plan review through `pi`, then triage its remarks for the user. Never revise the plan from the review yourself: the output of this skill is a proposal.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6.1-sol`. Check unknown ids with `pi --list-models <search>`.
- `thinking=<level>`: default `high` (`off|minimal|low|medium|high|xhigh|max`).
- Any remaining text is an extra review focus.

## 2. Write the brief

Take the latest implementation plan from this conversation: the most recent message or messages that lay it out. If there is none, stop and tell the user.

Before writing the brief, turn the problem and the requester's constraints into 3–6 checkable success criteria. Keep them to yourself for triage; they never go into the brief, so the reviewer's judgement stays unanchored.

Write the brief to a temp file (`mktemp /tmp/review-plan-gpt.XXXXXX.md`). The reviewer judges the plan cold: give it the problem and the plan, never how the plan was produced.

- Repository path(s) to check the plan against.
- The problem: ticket requirement or the user's request, as close to the source wording as possible.
- Constraints fixed by the requester, stated as requirements without rationale.
- The plan, as it currently stands, including its own justifications.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files; verify the plan's factual claims against the code before judging the approach; assess freely whether the plan solves the problem and whether a simpler or safer route exists; name the alternative approaches considered and why each was rejected or preferred; say explicitly when nothing significant is found. Answer in Russian.

Leave out the conversation's history: files explored, alternatives discarded, confidence, earlier plan versions, the user's corrections (only their resulting constraints).

Done when a reader with only the brief and the repository could judge the plan without guessing the problem, and nothing in it reveals how the plan was reached or the success criteria.

## 3. Run pi in background

Run from the repository root with `run_in_background: true`:

```bash
pi -p --no-session --model "$MODEL" --thinking "$THINKING" --tools read,bash @"$BRIEF"
```

stdout contains only the agent's final answer. Do not poll; wait for the completion notification.

## 4. Triage

Check every remark against the code and the agreed constraints before judging it. Score the plan and each alternative the reviewer names against the success criteria, criterion by criterion; an alternative that beats the plan on some criterion is a remark in its own right. Report to the user:

- **Стоит учесть**: confirmed gaps or errors in the plan, with the proposed plan change.
- **Спорно**: real trade-offs or needs the user's decision, with your view.
- **Отклонить**: false positives or contradictions of agreed constraints, with the evidence.

Done when every remark sits in exactly one group with its reason. Then stop and wait for the user to choose what to change in the plan. Delete the brief file.
