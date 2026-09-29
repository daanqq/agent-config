---
name: show-me-your-work
description: Keeps a compact, reviewable TSV decision trail for long-running, multi-phase, delegated, or unattended work. Use when the user will review the work after a pause, when hypotheses or pivots must remain auditable, or when another skill needs a canonical evidence log.
license: LICENSE
metadata:
  source: https://github.com/cursor/plugins/tree/57fc467a229cf2853329f19c9e6a9fd83ddc2ea2/pstack/skills/show-me-your-work
  adapted-for: pi
---

# Show me your work

Keep one append-only decision trail so a reviewer can reconstruct what was chosen, why, on what evidence, and with what result without reading the whole transcript.

Use this only when the trail will be read. A short local change does not need one.

## Start the trail

Default path: `.audit/<task-slug>.tsv` in the working repository. Use `/tmp/<task-slug>-decisions.tsv` for read-only investigations or disposable work. Do not edit ignore rules or commit the trail unless the user asked for it or the task explicitly requires an auditable repository artifact.

The header lives in [`references/decision-log-template.tsv`](references/decision-log-template.tsv):

```text
ts	phase	decision	why	evidence	result
```

Append through:

```bash
<skill-dir>/scripts/log.sh <logfile> <phase> <decision> <why> <evidence> <result>
```

The helper stamps UTC time, keeps every cell on one line, and prevents spreadsheet formula execution in generated or user-provided cells.

## What earns a row

Log only a decision or checkpoint that changes how a reviewer understands the run:

- a scope or design fork;
- a hypothesis accepted or rejected;
- a verified unit completed;
- a pivot, revert, or abandoned approach;
- a blocker or `INCONCLUSIVE` result;
- a verification gate corrected because its signal was wrong.

Evidence is a pointer, not a paragraph: a command and captured output path, commit, MR, `file:line`, test name, trace, screenshot, or generated artifact.

Use plain results such as `VERIFIED`, `NOT VERIFIED`, `INCONCLUSIVE`, `reverted`, `tests green`, or `open`. Never record an intended future action as if it happened.

A run is one agent conversation, including later turns and summaries. A pickup, replacement agent, or new chat starts a new run. When a run appends to a log that already has rows, its first row uses phase `start`; if another run has written since, use another `start` row before resuming. The row identifies the earlier timestamp range that this run did not write, and its evidence identifies the current run, such as an agent or session id. Reserve phase `start` for this purpose.

## Rules

- One row records one decision or checkpoint.
- Append new rows; do not rewrite history to make the run look cleaner.
- Keep cells single-line and concise.
- Prefer reproducible evidence over a self-report.
- Delegated work earns a row only after the parent inspects the artifact.
- External writes, publication, push, merge, ticket updates, and destructive cleanup remain subject to the active AGENTS.md confirmation rules.

## Audit before handoff

1. Read the active Pi transcript from `PI_SESSION_FILE` when available. For a past session, use Pond narrowly by session or topic and read the end where conclusions may have changed.
2. Identify this run's row ranges. They begin at this run's `start` rows, or at the first row when this run created the log, and end at another run's next `start` row.
3. Check each row in those ranges maps to a real action and every evidence pointer resolves.
4. Add missing pivots or retractions that shaped the result.
5. Append a correction or superseding row when the log disagrees with the work. Do not delete earlier canonical rows to improve the story. Do not audit another run's rows unless this run's own evidence proves one wrong.
6. For high-stakes unattended work, use one fresh reviewer if the current subagent budget allows it. The reviewer audits the trail and evidence, not the implementation from scratch.

## Handoff

Report the trail path, the final verified predicate, any `INCONCLUSIVE` rows, and the next action. If the trail was committed, say why it belongs in the change set. Otherwise leave it local and untracked.
