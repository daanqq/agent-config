# `background-terminals` packaging overlay

## Preserve

- Keep upstream `SKILL.md` unchanged, including automatic invocation and the
  instructions for starting, inspecting, and stopping session-scoped processes.
- Keep the source locked to the same commit as the companion Pi extension.

## Local packaging

- Bundle the repository's MIT license as `LICENSE`; upstream keeps it at the
  repository root rather than inside the skill directory.
- Install only in Pi's global skill directory. Do not add aliases in common,
  Claude, or `~/.agents/skills/`.

## Acceptance

Pi discovers the skill globally and exposes the matching background process
tools. Other clients do not receive this skill through the installation manifest.
