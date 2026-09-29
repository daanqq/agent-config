---
name: coding-discipline
description: "Use when implementing, fixing, refactoring, testing, or deleting code (not just text files). Do not use for read-only code reviews. Enforces surgical changes, broad search before deletion/unused claims, and explicit verification."
---

# Coding Discipline

Be surgical: make the smallest correct change that preserves the owning design.

Use this skill when changing code. Do not load it for read-only code reviews. Bias toward code that does not need to exist, but never skip trust-boundary validation, data-loss handling, security, accessibility, or explicitly requested behavior.

## First gate: should code exist?

Before writing code, stop at the first rung that works:

1. No real need: skip it.
2. Existing codebase helper, type, util, or pattern: reuse it.
3. Standard library: use it.
4. Native platform: use it.
5. Already-installed dependency: use it; do not add a dependency for what a few clear lines can do.
6. One line: make it one line.
7. Only then write the minimum code that works.
8. No tautological tests

If a simpler approach exists, push back before implementing the larger one.

Reuse requires evidence. Before adding a non-trivial helper, service method,
component, style token, icon, or library configuration, search the owning
module and its siblings for the same domain concept. Check project UI kits and
the defaults of any installed library involved in the change. Record the
candidate you will reuse, extend, or deliberately reject before writing the
replacement.

Completion criterion: the chosen approach names the existing candidates that
were checked, or states the search scope and that none were found.

## Working loop

1. State the intended behavior change and success criteria; done when both are concrete enough to verify.
2. Read before writing until you can name the owning module, affected immediate callers, local convention to follow, relevant tests or gaps, and the cheapest verification path.
3. For a non-trivial change, ask whether one behavior-preserving move would make the requested edit simpler; done when you either make that move or can explain why direct change is safer.
4. Implement surgically: touch only required code, match local style, and avoid unrelated cleanup.
5. Verify with the cheapest reliable check: focused test, existing test, typecheck, lint, build, or manual reproduction. Follow the `AGENTS.md` verification policy for reusing current evidence and stopping; done when the result is known and reportable.
6. Review the diff for structural regression before final response; for non-trivial changes, use [`QUALITY-GATE.md`](QUALITY-GATE.md).
7. Report what changed, what was verified, and what remains skipped or uncertain.

## Behavioral edge-case gate

For changes to business rules, persistence, permissions, external services,
retries, or user-visible state, run the behavioral questions in
[`QUALITY-GATE.md`](QUALITY-GATE.md) before implementation and again against
the finished diff. Resolve each applicable case in code or report it as an
explicit product decision or risk.

Completion criterion: every applicable behavioral question has an answer based
on the implementation, its callers, and the relevant state boundary.

## Branches

### Deletion or unused claims

Before claiming a symbol, field, route, helper, config key, behavior, or file is unused, dead, safe to delete, or has no external consumers, run a broad search across the relevant codebase.

Completion criterion: repo-wide search where practical, or an explicitly stated narrower scope with reason. Do not infer project-wide absence from one file or one directory. For exhaustive claims, use exhaustive search or paginate results.

### Prefactoring

Prefactor only when it makes the requested change smaller, safer, or more local, and behavior preservation can be verified.

Good candidates:

- Extract duplicated or deeply nested logic into one local helper.
- Move a condition closer to the data it depends on.
- Name a domain concept with an intermediate variable.
- Split parsing, validation, and side effects before adding a case.
- Normalize shape once at a boundary instead of patching every use site.
- Add a narrow test seam before modifying hard-to-reach logic.

Do not prefactor when the direct change is already obvious and safe, behavior preservation cannot be verified, unrelated modules must be touched, or the result would be an abstraction for hypothetical future work.

## Architecture guardrail

Minimal does not mean local-only. A tiny local patch is not acceptable if it makes the design worse.

Prefer a slightly larger behavior-preserving restructure when it removes repeated conditionals, puts logic in the owning module, reuses an existing abstraction correctly, makes the requested behavior a natural extension of the model, or deletes incidental complexity.

## General guardrails

- Resolve routine reversible choices from repository conventions. Follow `AGENTS.md` clarification boundaries when ambiguity materially changes behavior, a public contract, scope, or required permission.
- Surface conflicting patterns; choose one deliberately instead of averaging them.
- Tests should encode intent, not just line coverage.
- Non-trivial logic leaves one minimal runnable check behind. Trivial one-liners need no test.
- Fail loud: never say completed if something was skipped silently; never say tests pass if tests were skipped.
