---
name: typescript-best-practices
description: Applies concrete TypeScript type, boundary, API, and test rules when reading, writing, reviewing, or refactoring .ts and .tsx files. Use to model state honestly, remove unchecked casts, derive types from authoritative schemas, and keep external validation at boundaries.
license: LICENSE
metadata:
  source: https://github.com/cursor/plugins/tree/57fc467a229cf2853329f19c9e6a9fd83ddc2ea2/pstack/skills/typescript-best-practices
  adapted-for: pi
---

# TypeScript best practices

Apply these rules with repository conventions and the existing code's real constraints. The aim is fewer invalid states and clearer boundaries, not maximum type cleverness.

| Rule | Decision |
| --- | --- |
| Discriminated unions | Model variants with one literal discriminant when optional fields or booleans allow contradictory states. |
| Constructive modeling | Choose a representation that makes the important illegal value hard to construct. Use `NonEmpty<T>`, pairs, ranges, or branded primitives only when a real caller otherwise needs a cast, assertion, or repeated guard. |
| Simplest total type | Keep the looser type while all operations remain total. Strengthen inputs or widen outputs only where partiality reaches a caller. |
| `unknown` at external boundaries | Treat parsed JSON, RPC, IPC, storage, environment, and untyped library data as `unknown`; parse or narrow once where it enters. |
| Unchecked casts | Remove `as` casts that merely silence the compiler. A boundary cast is acceptable only after the code validates the full claim or a library limitation makes the assertion unavoidable and locally justified. |
| Narrowing order | Prefer discriminants, `in`, `typeof` or `instanceof`, then an honest type guard. Use an assertion only after those options fail for a concrete reason. |
| Exhaustiveness | Make variant handling fail the build when a new case is unhandled, usually with an inline `never` assignment. |
| `satisfies` | Prefer `satisfies` when a value must conform to a type without widening its literals. |
| Schema-derived types | Derive from generated or authoritative types with `Pick`, `Omit`, `Parameters`, `ReturnType`, `Awaited`, or `typeof` before duplicating a shape. |
| Object parameters | Prefer an object when positional arguments are easy to swap or the call has several optional settings. Keep positional arguments for small conventional APIs and measured hot paths. |
| Boundary errors | Parse and translate errors at the system edge. Keep internal domain functions typed and direct instead of revalidating the same shape down the call chain. |
| Tests | Test behavior through the owning interface with the narrowest real executable path. Use mocks only for boundaries that cannot run locally or are intentionally isolated. |
| Telemetry | Follow the repository logger and diagnostics conventions. Include stable identifiers and actionable context; do not add ad hoc shipped `console.log` calls. |

Read [`references/patterns.md`](references/patterns.md) when implementing one of these patterns or judging an exception.

## Review posture

- Match the repository's established discriminant, brand, error, and schema conventions before inventing another.
- Flag a type issue only when it enables a real invalid state, hides boundary uncertainty, forces assertions, or spreads knowledge across callers.
- Prefer a small local improvement over a type-system rewrite unrelated to the requested change.
- Do not weaken a truthful runtime possibility merely to obtain a narrower type.
- When a framework or generated API forces a cast, keep it at one boundary and explain the non-obvious reason if the code cannot make it evident.
