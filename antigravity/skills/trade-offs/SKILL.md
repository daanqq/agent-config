---
name: trade-offs
description: Compare existing code with one or more alternative designs and recommend one, read-only. Use when the user asks for pros and cons of another interface, state model, or implementation shape for code that already exists.
argument-hint: "<code location> [alternative]"
---

Compare the current design with its alternatives on this codebase's terms, then let the user choose. The output is a proposal: change no project files until the user picks an option.

Ground every pro and con in this code. A claim with no consumer, file, or convention behind it ("more flexible", "cleaner") holds for any codebase, so drop it.

## 1. Map the current design

Read the code at the given location and find every consumer with a search. Record:

- which values are independent inputs (stored, user- or server-owned) and which are derived;
- which states are valid, and how many combinations the types allow;
- what each consumer reads and what it must know to read it correctly.

Done when every consumer is listed with `file:line` and the valid states are enumerated.

## 2. Shape the alternatives

Take the user's alternative. If none is given, propose one or two that differ in kind, not in naming. For each, write a short sketch of the new interface and the after-form of every consumer from step 1. Name what cannot change shape, such as a user-owned input that must stay stored.

Done when every consumer has an after-form for every alternative.

## 3. Read the taste

Taste is how this project already solves the same kind of problem. If [`taste/`](taste/) has a file for the repository (`frontend` is `space-frontend.md`, `echat.business.service` is `echat-business-service.md`), read it first. It is a dated snapshot, so treat it as a lead and confirm each point you rely on in the code. Then collect taste from:

- the documented standards the repository points to (`AGENTS.md`, `CLAUDE.md`, coding standards);
- the same file and its sibling modules: how they model similar states, name things, and handle errors;
- the user's own skills and rules that cover the topic, for example a TypeScript or state-modeling rule.

Note where local consistency and the repository-wide habit disagree: that disagreement is itself a trade-off to report.

## 4. Compare on fixed axes

Judge the current design and every alternative on each axis, with evidence. Call a tie a tie.

- **Invalid states**: contradictory combinations the types allow, and what guards against them today.
- **Consumer knowledge**: what a consumer must know to use it correctly, and where that knowledge is duplicated.
- **Change locality**: where a likely next change lands (a new state, a new consumer, a new rule).
- **Taste fit**: agreement with step 3.
- **Switching cost**: files and tests touched, verified behaviour that must be rechecked, contract changes for other repositories or services.

Done when every axis has a verdict for every option.

## 5. Find the middle option

Look for a cheap change that closes the current design's main risk without the full switch, such as narrowing a public interface or adding one guard. Name it, or state that there is none.

## 6. Report and stop

Lead with the verdict and its main caveat. Then give, in order:

1. the valid states, as a table when there are several;
2. pros and cons of each option, drawn from the axes;
3. the middle option;
4. a recommendation, and a direct question naming the choices.

Wait for the user's choice before changing anything.
