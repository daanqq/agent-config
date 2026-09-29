# Critic prompt

Use this template for a read-only architectural critic after the parent has produced a factual explanation.

```text
Review the architecture of the described subsystem. Work read-only and form your judgment from the code, not from the explanation's tone.

Question and intended behavior:
{QUESTION}

Factual explanation:
{EXPLANATION}

Relevant files:
{FILES}

Critique rubric:
{RUBRIC}

Report architectural findings only. Skip line-level bugs, formatting, and preferences. For each finding provide:

- Severity: structural, concern, or observation.
- Components and exact code evidence.
- The architectural problem.
- Concrete cost to changeability, testability, correctness, or reader load.
- The smallest plausible direction that addresses the demonstrated problem.

An empty findings list is valid. Do not edit files.
```
