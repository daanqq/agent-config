# `writing-for-agents` semantic overlay

## Preserve

- Keep the upstream information hierarchy, context/cognitive load model, completion criteria, leading words, pruning guidance, and skill mechanics.
- Preserve Pi's actual `disable-model-invocation` semantics: it hides a skill from automatic discovery but does not prevent another skill from reading its file.
- Treat positive instructions and prohibitions as different tools. Do not claim that negation inherently causes the prohibited behavior; evaluate wording against representative runs on the target model.
- Keep router skills able to direct the agent to a hidden skill by file link.

## Replace or omit from upstream

- Replace harness-agnostic claims that only a human can reach user-invoked skills with Pi-specific discovery behavior.
- Replace universal anti-negation theory with evidence-based guidance and a permitted alternative when a prohibition leaves the next action unclear.

## Acceptance

The guide remains accurate for Pi while retaining upstream's document-design vocabulary and progressive-disclosure model.
