---
name: tdd
description: Test-driven development for features and fixes. Use when the user requests test-first work or red-green-refactor; integration tests alone do not imply TDD.
---

# Test-Driven Development

TDD is the red → green loop. Use the rules below to choose meaningful behavior tests and an appropriate public boundary. Consult supporting examples when a test-design decision needs them; follow `AGENTS.md` for verification scope, evidence reuse, and stopping.

When exploring the codebase, read `CONTEXT.md` (if it exists) so test names and interface vocabulary match the project's domain language, and respect ADRs in the area you're touching.

## What a good test is

Tests verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't. A good test reads like a specification: "user can checkout with valid cart" tells you exactly what capability exists, and it survives refactors because it doesn't care about internal structure.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for mocking guidelines.

## Seams: where tests go

A **seam** is the public boundary you test at: the interface where you observe behavior without reaching inside. Tests live at seams, never against internals.

Choose the narrowest existing public boundary that exercises the requested behavior, using the owning code and repository tests. Record the boundary and intended observable result in working notes, then proceed without routine confirmation. Ask when the expected contract is genuinely disputed or the choice would materially change scope or a public interface; continue independent authorized work while awaiting an answer.

When the shape of that interface is itself in question, read [codebase-design](../codebase-design/SKILL.md) for the interface and module-design vocabulary. Consult it as reference rather than starting a separate design workflow.

## Anti-patterns

- **Implementation-coupled**: mocks internal collaborators, tests private methods, or verifies through a side channel (querying the database instead of using the interface). The tell: the test breaks when you refactor but behavior hasn't changed.
- **Tautological**: the assertion recomputes the expected value the way the code does (`expect(add(a, b)).toBe(a + b)`, a snapshot derived by hand the same way, a constant asserted equal to itself), so it passes by construction and can never disagree with the code. Expected values must come from an independent source of truth: a known-good literal, a worked example, the spec.
- **Horizontal slicing**: writing all tests first, then all implementation. Bulk tests verify _imagined_ behavior: you test the _shape_ of things rather than user-facing behavior, the tests go insensitive to real changes, and you commit to test structure before understanding the implementation. Work in **vertical slices** instead: one test → one implementation → repeat, each test a **tracer bullet** that responds to what the last cycle taught you.

## Rules of the loop

- **Red before green.** Write the failing test first, then only enough code to pass it. Don't anticipate future tests or add speculative features.
- **One slice at a time.** One seam, one test, one minimal implementation per cycle.
- **Refactoring is not part of the loop.** It belongs to the review stage (see the `code-review` skill), not the red → green implementation cycle.
