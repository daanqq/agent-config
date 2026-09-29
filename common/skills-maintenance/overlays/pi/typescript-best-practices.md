# `typescript-best-practices` semantic overlay

## Preserve

- Keep automatic invocation for reading, writing, reviewing, or refactoring TypeScript and TSX.
- Apply concrete local rules directly without requiring separate Cursor principle skills.
- Preserve boundary validation, schema-derived types, honest state modeling, narrowing hierarchy, cast avoidance, exhaustive unions, object arguments where appropriate, real tests, and structured telemetry.
- Retain and update the local `references/patterns.md` examples, the bundled license, and Pi metadata.

## Replace or omit from upstream

- Remove `paths` and `disable-model-invocation`; Pi discovers this skill through its description.
- Replace dependencies on `type-system-discipline` and `boundary-discipline` with self-contained rules.
- Keep exceptions practical: casts may follow validation, object arguments may be skipped on measured hot paths, and type strengthening should solve a real partiality problem.

## Acceptance

Advice models invalid states out where useful, validates external data once at the boundary, and does not add type cleverness without leverage.
