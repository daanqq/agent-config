# `bro` semantic overlay

## Preserve

- Keep the upstream content unchanged, including `disable-model-invocation: true`.

## Add beyond upstream

- `agents/openai.yaml` with `policy.allow_implicit_invocation: false`: Codex ignores `disable-model-invocation` and reads only this policy, so without it the model could start the skill on its own.

## Acceptance

The skill matches upstream except for `agents/openai.yaml`, and Codex lists it without implicit invocation.
