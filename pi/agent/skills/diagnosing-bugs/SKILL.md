---
name: diagnosing-bugs
description: Diagnose bugs and performance regressions from symptoms, code, and focused checks. Use for debugging requests or reports of broken, failing, or slow behavior.
---

# Diagnosing bugs

Match the investigation to the symptom and available evidence. Follow the active `AGENTS.md` rules for read-only work, temporary artifacts, database access, external writes, and cleanup. A diagnosis request does not authorize a fix to working files.

## Working path

1. Establish the exact symptom, expected behavior, and relevant environment. Read the nearest owning code, callers, and available error output. Consult `CONTEXT.md` or local ADRs when domain terms or design constraints affect the diagnosis.
2. Form an evidence-based hypothesis and choose the cheapest check that can distinguish it from a plausible alternative. Source inspection may be enough to identify an obvious defect; an executable reproduction is not a prerequisite for reasoning.
3. When a safe environment is available, reproduce the symptom through the relevant interface. Prefer existing tests, a focused CLI invocation, a local HTTP request, or a browser interaction. Check that the observation detects the reported failure, not merely successful execution.
4. If a fix is authorized, make the necessary change and verify the requested behavior. Add a regression test when it can exercise the real failure through a useful existing boundary. Prefer observing it fail before the fix and pass afterward; document any missing baseline or unavailable test path.
5. Report the cause supported by evidence, the checks performed, and any remaining uncertainty. Reuse evidence for the current artifact under the verification policy in `AGENTS.md`; repeat a check when the relevant code or observation conditions change.

When the environment or permission needed to reproduce is unavailable, continue useful source analysis. Separate observations from hypotheses, explain what remains unverified, and identify the smallest missing artifact or safe check that would resolve it. Ask only for information that materially changes the diagnosis; do not request production access as a workaround.

Completion: the diagnosis is supported by the available evidence and its limits are explicit. For an authorized fix, the relevant check passes or the remaining verification blocker is reported. A source-based hypothesis without runtime evidence must not be presented as a reproduced or verified fix.

## Difficult cases

Read [references/difficult-cases.md](references/difficult-cases.md) when the initial check is inconclusive, causes compete, reproduction is intermittent, or a performance or historical regression needs measurement. Use only the techniques that resolve the current uncertainty.

## Evidence and instrumentation

- Redact credentials, auth headers, and sensitive payload fields before showing commands, output, or captured artifacts. Keep credentials in environment variables rather than command text.
- Tie each probe to a prediction. Prefer debugger inspection or targeted logs over broad logging; compare one relevant variable at a time when testing causality.
- Add temporary instrumentation only within the authorized scope. Give debug logs a unique prefix so they can be found and removed before delivery.
- For performance claims, compare a relevant baseline and changed behavior under comparable conditions. A faster unrelated command does not prove the reported regression is fixed.
- Remove instrumentation added by this task. Clean up only task-owned temporary artifacts whose ownership is verified; preserve user data and report anything retained.
