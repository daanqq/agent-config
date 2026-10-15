---
name: solution-discovery
description: Compare ready-made tools, adapters, and custom implementations when choosing a new developer tool or reproducing an existing workflow before an implementation is chosen.
---

# Solution discovery

Choose the class of solution before broad implementation research. This is a
read-only selection workflow, not permission to install tools or change code.
Use it for new tooling or workflow analogues, not routine code changes.

## Process

1. **Define the result.** Name the observable output and decisive constraints:
   fidelity, supported inputs, integration points, privacy, side effects, and
   operating environment. Read enough of the existing workflow to distinguish
   a real requirement from its current implementation.
2. **Check what exists locally.** Inspect the current tool's supported commands,
   installed packages, and repository helpers before proposing a replacement.
3. **Find alternatives.** When external discovery is permitted, search relevant
   package registries and documentation for ready-made tools. For remote Git
   references, follow [`librarian`](../librarian/SKILL.md). With an offline or
   no-web constraint, use local evidence and state what remains unknown; do not
   make network calls or block the local comparison.
4. **Compare before diving deeper.** Evaluate ready-made, ready-made plus an
   adapter, and custom approaches against the decisive constraints. Exclude an
   option with a concrete reason, not a preference for familiar code. Inspect
   implementation details or make an authorized isolated probe only to resolve
   a difference that could change the choice. Do not install dependencies or
   execute downloaded code merely because a candidate was found.
5. **Recommend with limits.** State the selected approach, the adapter it still
   needs, the evidence supporting it, and the smallest remaining check. Separate
   a verified mechanism from an untested integration; do not promise savings
   without a relevant measurement.

Completion: each decisive constraint has evidence or an explicit unknown for
the viable options, and the next investigation is tied to a choice-changing gap.
If only one option is supported, explain why rather than inventing alternatives.

## Output

Keep the comparison compact: option, decisive fit or mismatch, evidence, and
remaining uncertainty. Follow with the recommendation and next check. For
rendering or export tools, distinguish a faithful runtime capture from a
reconstruction or formatted transcript; matching appearance alone does not
establish the same behavior or side effects.
