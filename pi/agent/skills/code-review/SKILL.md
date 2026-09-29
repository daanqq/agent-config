---
name: code-review
description: Review branch, PR, or working-tree changes against repository standards and the available task specification. Use for code review requests or review since a fixed point.
---

Two-axis review of an explicitly bounded change:

- **Standards**: does the code conform to this repo's documented coding standards?
- **Spec**: does the code faithfully implement the originating issue / spec?

Keep the axes separate in the report. Follow `AGENTS.md` for delegation budget and model selection. When this skill is explicitly invoked, it permits up to two reviewers, one per axis; automatic activation does not increase the default budget. With one child, the parent handles the other axis. A small review can stay in the parent.

## Process

### 1. Pin the review scope

Use an explicit repository path for Git commands. Resolve the request into one scope and state it before reviewing:

- `branch`: committed changes from the merge-base of the fixed point and captured `HEAD` to that captured head.
- `working-tree`: staged and unstaged changes relative to `HEAD`, plus untracked files. No branch base is needed.
- `all`: the combined current change from the branch merge-base through the working tree, plus untracked files.

Use the user's explicit scope first. Otherwise, a branch or MR request selects `branch`, a local/WIP request selects `working-tree`, and a request including committed and pending work selects `all`. Derive the fixed point from the request, earlier context, or authoritative MR target metadata. Do not assume a same-name remote tracking branch is the integration base. Ask only when materially different scopes or branch bases remain plausible; continue an independently authorized review portion while waiting.

Capture `git rev-parse --verify HEAD`, `git status --short`, and `git ls-files --others --exclude-standard`. For `branch` or `all`, resolve the fixed point to a commit, compute `git merge-base <fixed-point-oid> <head-oid>`, and capture `git log <merge-base>..<head-oid> --oneline`.

Use these exact bounds in reviewer inputs:

- `branch`: `git diff <merge-base> <head-oid>`; exclude pending and untracked files.
- `working-tree`: inspect `git diff --cached` and `git diff` for staged and unstaged changes, and `git diff <head-oid>` for their net result. Read every in-scope untracked file explicitly.
- `all`: use `git diff <merge-base>` for the combined net result. Inspect branch history and staged/unstaged diffs as context, and read every in-scope untracked file explicitly. Report each issue once, against the combined change.

Record commands, resolved commits, changed files, and untracked paths as the shared scope manifest. Pending files are not frozen by capturing `HEAD`; check for concurrent changes before aggregation and refresh affected evidence if needed. For a repository without `HEAD`, review initial staged and untracked content as `working-tree`; branch comparison is unavailable.

An invalid required ref or unavailable merge-base blocks that comparison, not a separately authorized working-tree review. An empty tracked diff is not an empty review when in-scope untracked files remain. If the complete scope is empty, report that without spawning reviewers.

### 2. Identify the spec source

Look for the originating spec, in this order:

1. The user's task description, supplied spec, or task context already available in the conversation.
2. Issue references in commit messages or MR metadata, using `docs/agents/issue-tracker.md` when present or an available read-only tracker integration. Missing integration guidance does not require setup before review.
3. A spec file under `docs/`, `specs/`, or `.scratch/` matching the branch name or feature.
4. If no spec is available, continue correctness and Standards review. Report Spec coverage as unavailable rather than inventing requirements. Ask for a missing requirement only when it materially changes a finding, without blocking unrelated review.

### 3. Identify the standards sources

Anything in the repo that documents how code should be written, such as `CODING_STANDARDS.md` or `CONTRIBUTING.md`.

On top of whatever the repo documents, the Standards axis always carries the **smell baseline** below: a fixed set of Fowler code smells (_Refactoring_, ch.3) that applies even when a repo documents nothing. Two rules bind it:

- **The repo overrides.** A documented repo standard always wins; where it endorses something the baseline would flag, suppress the smell.
- **Always a judgement call.** Each smell is a labelled heuristic ("possible Feature Envy"), never a hard violation. Like any standard here, skip anything tooling already enforces.

Each smell reads *what it is* → *how to fix*; match it against the diff:

- **Mysterious Name**: a function, variable, or type whose name doesn't reveal what it does or holds. → rename it; if no honest name comes, the design's murky.
- **Duplicated Code**: the same logic shape appears in more than one hunk or file in the change. → extract the shared shape, call it from both.
- **Feature Envy**: a method that reaches into another object's data more than its own. → move the method onto the data it envies.
- **Data Clumps**: the same few fields or params keep travelling together (a type wanting to be born). → bundle them into one type, pass that.
- **Primitive Obsession**: a primitive or string standing in for a domain concept that deserves its own type. → give the concept its own small type.
- **Repeated Switches**: the same `switch`/`if`-cascade on the same type recurs across the change. → replace with polymorphism, or one map both sites share.
- **Shotgun Surgery**: one logical change forces scattered edits across many files in the diff. → gather what changes together into one module.
- **Divergent Change**: one file or module is edited for several unrelated reasons. → split so each module changes for one reason.
- **Speculative Generality**: abstraction, parameters, or hooks added for needs the spec doesn't have. → delete it; inline back until a real need shows.
- **Message Chains**: long `a.b().c().d()` navigation the caller shouldn't depend on. → hide the walk behind one method on the first object.
- **Middle Man**: a class or function that mostly just delegates onward. → cut it, call the real target direct.
- **Refused Bequest**: a subclass or implementer that ignores or overrides most of what it inherits. → drop the inheritance, use composition.

### 4. Review both axes within the available budget

**Standards sub-agent prompt** should include:

- The scope manifest from step 1, including exact diff commands, resolved commits, and in-scope untracked paths.
- The list of standards-source files you found in step 3, **plus the smell baseline from step 3** pasted in full (the sub-agent has no other access to it).
- The brief: "Report, per file/hunk where relevant, (a) every place the diff violates a documented standard: cite the standard (file + the rule); and (b) any baseline smell you spot: name it and quote the hunk. Distinguish hard violations from judgement calls: documented-standard breaches can be hard, but baseline smells are always judgement calls, and a documented repo standard overrides the baseline. Skip anything tooling enforces. Under 400 words."

**Spec sub-agent prompt** should include:

- The same scope manifest, so both axes review the same committed and pending content.
- The path or fetched contents of the spec.
- The brief: "Report: (a) requirements the spec asked for that are missing or partial; (b) behaviour in the diff that wasn't asked for (scope creep); (c) requirements that look implemented but where the implementation looks wrong. Quote the spec line for each finding. Under 400 words."

If the spec is missing, skip the Spec sub-agent and note this in the final report. Whether an axis runs in the parent or a child, inspect the actual in-scope artifacts and applicable immediate callers. Reuse current verification evidence under `AGENTS.md`; neither an extra reviewer nor a repeated test is mandatory merely because a review was delegated.

### 5. Aggregate

Present the two reports under `## Standards` and `## Spec` headings, verbatim or lightly cleaned. Do **not** merge or rerank findings, because the two axes are deliberately separate (see _Why two axes_).

End with a one-line summary: total findings per axis, and the worst issue _within each axis_ (if any). Don't pick a single winner across axes: that's the reranking the separation exists to prevent.

## Why two axes

A change can pass one axis and fail the other:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**

Reporting them separately stops one axis from masking the other.
