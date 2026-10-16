---
name: ambition
description: Rewrite a task into a deeper, wider brief before any work starts.
disable-model-invocation: true
metadata:
  source: https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/
---

# Ambition

Turn the task into a brief for a _deeper_ version of it, not a bigger one. Take the task from the arguments, or from the current conversation when there are none. This skill only writes the brief: it does not start the work or change project files. Execution starts when the user approves parts of the brief.

Keep the user's stated outcome fixed. Depth and range change how the task is done; altitude, which changes the outcome itself, runs only when the user explicitly asks for it.

## 1. Ground

Read enough of the real material (code, data, logs, traces, existing tests and checks) to name concrete sources and instruments rather than generic ones. Done when every source, tool, or access the brief relies on is either observed in the environment or marked as missing.

## 2. Depth

Answer each question for this task:

- **Expert delta.** What would the best practitioner do here that the task does not ask for? A change of method, not of vocabulary.
- **Rawest material.** The lowest-level source to start from: raw logs, profiles, production data, the protocol spec, instead of summaries or someone's description.
- **Instruments.** The specific methods and tools that practitioner would use: profiler, heap snapshot, database query, property-based test, statistical model.
- **Belief under test.** The assumption the task rests on ("the slowness is rendering", "users drop off at onboarding") and how to try to falsify it against the raw material.
- **Outside judge.** An executable check that would prove the result without the model grading itself. Rank it with the evidence levels in [`prove-it-works`](../prove-it-works/SKILL.md).

When the task has a measurable target, add a _stretch target_ an order of magnitude past the stated one (5s → 200ms) and what would have to be true to reach it. The brief must require reporting the number actually reached and must not accept "impossible" without evidence.

## 3. Range

1. Restate the deliverable as a verb: what it does for whom. Not "a settings page" but "let someone change system behaviour quickly and without fear".
2. From the verb, assemble a _crew_ of 2-4 disciplines that would improve the result, including one _red team_ whose job is to break it. Give each a concrete action it performs, not a voice to write in: what a security reviewer does is enumerate trust boundaries, not sound like one.
3. Mark crew members whose work is independent enough to run as subagents.

## 4. Altitude (only on explicit request)

Climb 2-3 levels by asking what should happen after the task is done ("fix this crash" → "keep the app crash-free"), and let the user pick a level. For the chosen level, list the setup that would let the work run without a human in the loop: data access, mappings (for example app version → commit), environments to reproduce and verify. Altitude fits outcome-driven work, not creative work.

## 5. Brief

Present:

- **Rewritten prompt.** Pasteable as a new task, opening with the intent: a deeper version of the task, not a bigger one. It names the rawest material, the instruments, the crew actions, and the outside judge.
- **Now / later.** Anything that widens scope (new dependencies, public API changes, refactors, new systems or services) goes under _later_ and needs its own approval.
- **Prerequisites.** Missing access, data, or tools, each with what would provide it.

Done when every element of the rewritten prompt sits under _now_ with a judge that can check it, or under _later_. Then stop and ask which parts to run.
