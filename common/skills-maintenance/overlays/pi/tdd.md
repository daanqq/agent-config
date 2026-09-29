# `tdd` semantic overlay

## Preserve

- Invoke only for explicitly requested test-first or red-green-refactor work; integration tests alone do not imply TDD.
- Keep the Matt Pocock behavior/seam guidance, vertical slices, anti-patterns, and supporting references.
- Choose the narrowest useful existing public boundary without routine confirmation. Ask only when the contract, scope, or public interface is materially disputed.
- Consult the local `codebase-design` skill by file link when the seam itself is unclear.
- Follow `AGENTS.md` for verification scope, evidence reuse, and stopping.

## Replace or omit from upstream

- Remove mandatory pre-approval of every test seam.
- Replace cross-skill tool-call phrasing with a direct link to the installed Pi skill.

## Acceptance

Each cycle demonstrates red before green through a meaningful behavior boundary and avoids tests that merely mirror implementation details.
