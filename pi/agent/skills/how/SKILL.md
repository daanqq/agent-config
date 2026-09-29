---
name: how
description: Explains how a subsystem, feature flow, or function works and where its logic belongs. Use for code walkthroughs, runtime traces, ownership and layering questions, onboarding mental models, or architectural critique before changing code. Use historical investigation separately when the question is why the design exists.
license: LICENSE
metadata:
  source: https://github.com/cursor/plugins/tree/57fc467a229cf2853329f19c9e6a9fd83ddc2ea2/pstack/skills/how
  adapted-for: pi
---

# How

Build a working mental model of code from the implementation itself. Explain enough for a senior engineer to start changing the subsystem without turning the answer into annotated source.

## Choose the mode

- **Explain.** The default for mechanics, runtime flow, placement, ownership, and layering.
- **Critique.** Explain first, then judge architectural problems when the user asks whether the design is sound or how it should improve.

Historical motivation is a different question. Do not infer intent from code shape; use available history sources when the user asks why.

## Explain

1. **Lock the question.** State the best concrete interpretation when the scope is ambiguous, then proceed without blocking on a reversible assumption.
2. **Size the exploration.**
   - **Simple:** one function, module, adapter, or narrow path. Explore directly in the parent session.
   - **Complex:** a subsystem spanning several files, packages, or services. Decompose it into distinct angles. The entire request has a default budget of one subagent; delegate at most one independent angle and keep the rest in the parent session.
3. **Trace the code.** Start broad with `fffind` and `ffgrep`, then read the top matches. Follow an entry point through callers, callees, data transformations, state transitions, side effects, and boundaries. Read actual definitions and implementations; filenames are clues, not evidence.
4. **Close gaps.** Continue until the path from trigger to effect can be described without hand-waving. Name any edge that remains untraced.
5. **Explain.** Use the output contract below and cite exact files and symbols. A diagram belongs only where it removes ambiguity.

For a delegated exploration, build the prompt from [`references/explorer-prompt.md`](references/explorer-prompt.md). The parent checks the report against the code and writes the final explanation. Do not pass a subagent summary through unreviewed.

## Critique

1. Complete the explanation first.
2. Read [`references/critique-rubric.md`](references/critique-rubric.md).
3. Review the architecture yourself. For a broad or contested subsystem, use one read-only Luna reviewer with [`references/critic-prompt.md`](references/critic-prompt.md) only if the request has not already spent its default subagent budget. Otherwise the parent performs the critique, or asks before adding a second subagent.
4. Apply lead judgment. Classify findings as:
   - **Act on.** A concrete architectural problem worth changing now.
   - **Consider.** A real tradeoff whose benefit may not justify the cost yet.
   - **Noted.** Valid context with low current priority.
   - **Dismissed.** Wrong, stylistic, already constrained, or missing repository context.

Critique is read-only unless the user explicitly asks for implementation.

## Output contract

- **Overview.** What the subsystem is, what it does, and why a reader should care.
- **Key concepts.** Only the types, modules, state, and boundaries needed for the flow.
- **How it works.** Trigger-to-effect sequence, data transformations, decisions, and side effects.
- **Where things live.** The small file and directory map needed to start work.
- **Gotchas.** Non-obvious behavior, lifecycle constraints, hidden coupling, and unresolved gaps.

In critique mode, append the categorized architectural verdict after the explanation. Keep mechanics and historical rationale separate.
