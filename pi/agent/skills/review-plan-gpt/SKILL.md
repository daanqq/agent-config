---
name: review-plan-gpt
description: Get an independent cold second-opinion review of the current implementation plan from a GPT model, then triage the remarks without rewriting the plan.
disable-model-invocation: true
---

Run a read-only plan review through a Pi subagent, then triage its remarks for the user. Never revise the plan from the review yourself: the output of this skill is a proposal.

Invoke with `/skill:review-plan-gpt [model=<id>] [thinking=<level>] [extra focus]`, or `$review-plan-gpt` with the same options through the local skill-dollar extension. Parse options from the user request accompanying the loaded skill.

## 1. Parse arguments

- `model=<id>`: default `openai-codex/gpt-6-astra`. Check unknown ids with `pi --list-models <search>`.
- `thinking=<level>`: default `medium` (`off|minimal|low|medium|high|xhigh|max`).
- Any remaining text is an extra review focus.

Read `../subagents/SKILL.md` before spawning. This skill's explicit model and thinking defaults override the general model-selection defaults; user-provided options override this skill's defaults.

## 2. Build the reviewer prompt

Take the latest implementation plan from this conversation: the most recent message or messages that lay it out. If there is none, stop and tell the user.

Before building the prompt, turn the problem and the requester's constraints into 3-6 checkable success criteria. Keep them to yourself for triage; they never go into the prompt, so the reviewer's judgement stays unanchored.

The reviewer judges the plan cold: give it the problem and the plan, never how the plan was produced. Build a self-contained prompt containing:

- Repository path(s) to check the plan against.
- The problem: ticket requirement or the user's request, as close to the source wording as possible.
- Constraints fixed by the requester, stated as requirements without rationale.
- The plan, as it currently stands, including its own justifications.
- Extra focus from the arguments.
- Instructions: read-only, do not modify files, rewrite the plan, or implement changes; verify the plan's factual claims against the code before judging the approach; assess freely whether the plan solves the problem and whether a simpler or safer route exists; name the alternative approaches considered and why each was rejected or preferred; say explicitly when nothing significant is found. Answer in Russian.

Leave out the conversation's history: files explored, alternatives discarded, confidence, earlier plan versions, the user's corrections (only their resulting constraints).

Done when a reader with only the prompt and the repository could judge the plan without guessing the problem, and nothing in it reveals how the plan was reached or the success criteria. Pass the prompt directly to the tool; no temporary brief file is needed.

## 3. Spawn the reviewer

Call `subagent_spawn` once with:

- `prompt`: the complete reviewer prompt.
- `name`: `review-plan-gpt`.
- `harness`: `pi`.
- `working_dir`: the absolute repository root, or the primary repository root when reviewing multiple repositories.
- `model`: the parsed model id.
- `reasoning_effort`: the parsed thinking level.

Results arrive automatically. Do not poll or immediately wait. Continue useful read-only parent work, such as checking the plan against the private success criteria without passing those criteria to the reviewer. Call `subagent_wait({ ids: [id] })` only when you cannot proceed without the result, using the id returned by the spawn.

## 4. Triage

Check every remark against the code and the agreed constraints before judging it. Score the plan and each alternative the reviewer names against the success criteria, criterion by criterion; an alternative that beats the plan on some criterion is a remark in its own right. Report to the user in Russian, grouping remarks as:

- **Worth considering**: confirmed gaps or errors in the plan, with the proposed plan change.
- **Debatable**: real trade-offs or needs the user's decision, with your view.
- **Reject**: false positives or contradictions of agreed constraints, with the evidence.

Done when every remark sits in exactly one group with its reason. If there are no significant remarks, say so explicitly. Then stop and wait for the user to choose what to change in the plan. Do not rewrite the plan or implement changes.
