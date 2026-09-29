---
name: blast-radius
description: Finds behavior outside a diff that a change could break and proves the load-bearing safety fact with the cheapest executable check. Use when asked what a change could break, when reviewing a deceptively small high-risk diff, or before shipping changes to shared state, protocols, lifecycle code, or external boundaries.
license: LICENSE
metadata:
  source: https://github.com/cursor/plugins/tree/57fc467a229cf2853329f19c9e6a9fd83ddc2ea2/pstack/skills/blast-radius
  adapted-for: pi
---

# Blast radius

Find the breakage that a diff and a caller search do not reveal. The deliverable is not a long risk list. It is the one or two facts the change's safety depends on, each proven as far as the available environment allows.

## Evidence ladder

For every load-bearing safety fact, state the highest level reached:

1. **Claim.** A plausible statement with no independent evidence.
2. **Source.** A concrete `file:line`, pinned dependency source, schema, or protocol definition.
3. **Failure trace.** The bad case was followed step by step and shown to reach or not reach the changed behavior.
4. **Executable proof.** An existing test, focused command, or temporary script exercised the real code and failed loud if the fact was false.
5. **Running product.** The matching UI, CLI, service, worker, or integration path reproduced the behavior.

A fact below level 4 remains **UNPROVEN**. Do not round it up because the writeup sounds convincing.

## Workflow

1. **Pin the scope.** Resolve the fixed point, inspect the complete diff and untracked files, and read the applicable repository instructions. Completion: the exact change surface and intended behavior are named.
2. **State the behavior delta.** Explain what now happens differently, including lifecycle, ordering, identity, persistence, compatibility, and error behavior the diff does not spell out. Completion: the changed contract is concrete enough to construct a failure scenario.
3. **Find the safety fact.** Ask what single fact would clear most suspected failures if true. Prefer a narrow invariant over a catalogue of maybes. Completion: one or two falsifiable facts are written down.
4. **Look where grep stops.** Follow relevant callers, but also inspect pinned dependency source, local patches, generated artifacts, wire formats, persisted shapes, old/new version combinations, async teardown, retries, feature flags, and downstream consumers in other packages or languages. Completion: every plausible path around the fact is either traced or named as a gap.
5. **Prove the fact cheaply.** Use the lowest-cost check that reaches the real behavior. In a read-only request, run existing checks or place throwaway scripts under `/tmp`; do not edit repository files. If proof requires a repository change, external write, configured database, or unavailable runtime, stop at the achieved level and mark the fact `UNPROVEN` or `INCONCLUSIVE`.
6. **Judge the risks.** Keep only risks with a credible trigger and consequence. Record checked-and-cleared candidates separately so they do not return as findings.

Use at most one subagent by default and only when the risk surface has a genuine independent slice. The parent verifies its findings. Do not turn a blast-radius review into a broad multi-model ceremony.

## Report

- **Behavior delta.** What changed beyond the obvious diff.
- **Safety fact.** The fact, evidence level, and proof output or `UNPROVEN` status.
- **Confirmed risks.** Trigger, consequence, `file:line`, likelihood, severity, and cheapest detecting check.
- **Cleared risks.** What was investigated and why it is safe.
- **Before merge.** The smallest remaining test or reproduction that would catch the real failure.
- **Gaps.** Anything unavailable or `INCONCLUSIVE`.

Keep the report read-only unless the user explicitly asked to implement fixes. Cite real artifacts and remove private data from anything intended for publication.
