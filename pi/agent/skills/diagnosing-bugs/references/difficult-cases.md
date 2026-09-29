# Difficult debugging cases

Use these techniques when the short diagnosis path leaves a concrete uncertainty. Choose the next experiment by the evidence it can add, not by completing every technique below.

## Competing explanations

Keep a ranked set of plausible hypotheses when more than one fits the evidence. For each, name an observation that would support or reject it. Test the most informative affordable prediction first. Share a domain-sensitive assumption with the user without blocking unrelated authorized work. There is no required number of hypotheses.

## Reproduction and minimization

Choose a check that reaches the reported failure through the owning interface. Existing tests, local CLI or HTTP calls, browser interactions, captured-trace replay, and isolated harnesses are possible starting points. For replay, remove credentials and inspect possible side effects before execution.

Reduce inputs or setup when doing so makes the cause easier to isolate or the regression check easier to maintain. Stop minimizing when the remaining scenario distinguishes the cause and is practical to run; proving every element indispensable is unnecessary.

Improve speed or determinism when repeated runs would otherwise dominate the investigation. Preserve the failure signal. A slow real reproduction can be more useful than a fast check of a different behavior.

## Intermittent failures

Record the observed failure rate and conditions. Use a bounded number of repetitions, fixed seeds, controlled scheduling, or isolated stress tests to distinguish hypotheses. Select the run budget from observed frequency, cost, and risk rather than a fixed iteration count. A clean run is not proof of absence; report the sample size and uncertainty.

Instrumented timing or injected delays can help locate a race, but verify conclusions against the original conditions when practical. Run stress checks only in a safe isolated environment.

## Historical and performance regressions

Compare known-good and failing versions or configurations when both are available. Use `git bisect run` only when a reliable signal and suitable good/bad bounds make it cheaper than focused inspection. Run bisection in an isolated task-owned checkout and preserve the user's working tree.

For performance, measure the reported operation under comparable workload and environment conditions. Use timings, profiles, or traces to identify the bottleneck before changing it. Query plans and database-backed measurements remain subject to `AGENTS.md` database permissions.

## Human-assisted checks

When only the user can exercise the affected path, request the smallest interaction or redacted artifact that distinguishes the remaining hypotheses. The optional [HITL template](../scripts/hitl-loop.template.sh) can structure repeated human-assisted checks when useful; it is not required for a one-off observation.

## Stop or continue

Continue while the next safe experiment can materially narrow the cause or verify the fix. Stop when the relevant evidence satisfies the task, or when further progress requires unavailable information or permission. Report unresolved hypotheses and the next discriminating check rather than starting broader testing without a reason.
