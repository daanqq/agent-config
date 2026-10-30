# `herdr` semantic overlay

## Preserve

- Keep the upstream Herdr CLI reference, workflows and safety rules.

## Local changes

- In «Safety and coordination rules», after the rule about `--current` and explicit targets, add: before `agent prompt` to an agent not started for this task, check `agent get`; on `focused: true` do not prompt, because submitted text merges with the user's draft even when the agent is `idle`; use a handoff file or wait until the pane is unfocused.

## Acceptance

The skill retains all other upstream content and contains the focused-pane rule in its safety rules.
