---
name: review-deepseek
description: Review the task implementation discussed in the current session with DeepSeek.
disable-model-invocation: true
---

# Review with DeepSeek

Build a self-contained prompt from the current session: include the task requirements, repository path, implementation scope, and relevant changed files or diff bounds. Ask for a read-only code review that reports concrete defects, regressions, and missing requirements first, with file and line references, and states explicitly when no findings remain.

Spawn one subagent with `harness: pi`, `model: openrouter/deepseek/deepseek-v4.1-flash`, `reasoning_effort: high`, and that prompt. Then call `subagent_wait` for its id and return the review to the user.
