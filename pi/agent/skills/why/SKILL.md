---
name: why
description: Investigates why code, a threshold, guard, workflow, or design decision exists. Use for historical rationale, regressions, postmortems, legacy removal, rejected alternatives, and product or operational constraints. Separates direct evidence from inference and reports unavailable sources. Use how for runtime mechanics.
license: LICENSE
metadata:
  source: https://github.com/cursor/plugins/tree/57fc467a229cf2853329f19c9e6a9fd83ddc2ea2/pstack/skills/why
  adapted-for: pi
---

# Why

Investigate the forces that produced a design. Code is evidence of mechanics, not proof of intent. Build the answer from cited history and keep unsupported explanations visibly separate.

Read [`references/epistemics.md`](references/epistemics.md) before synthesizing.

## Workflow

1. **Lock the question.** Name the target and the kind of rationale requested: design choice, alternative, defensive edge case, threshold, regression, business constraint, or historical evolution.
2. **Anchor in code.** Identify exact paths, lines, symbols, tests, current behavior, and recent commits. Use `git blame`, `git log --follow`, commit messages, and local documentation. Completion: every source search has concrete identifiers instead of a broad project name.
3. **Build the available-source map.** Search only read-only sources that actually exist and can affect the question:
   - git history, code comments, tests, and local ADRs or docs;
   - GitLab MR context through the installed review tooling when the target came from an MR;
   - YouTrack or PORA through installed EUTP tooling when the target has a task identifier;
   - Pond for past agent sessions and decisions, using semantic search first and reading relevant session tails;
   - other connected MCP sources only after checking their instructions and confirming the calls are read-only.
4. **Investigate proportionally.** Start with source control and the strongest named source. Add another source when it can distinguish competing explanations or fill a material gap. Use at most one subagent by default for an independent evidence category; the parent owns synthesis and citation checks.
5. **Test alternatives.** Ask what evidence would exist if a competing explanation were true and search for it. Preserve contradictions instead of choosing the smoothest story.
6. **Synthesize.** Separate direct evidence, supported inference, competing hypotheses, and unknowns. Every claim about intent needs a citation or an explicit inference chain.

Do not query production or shared develop databases. Obtain permission before any other configured database query. Never update tickets, MRs, documents, chats, dashboards, or external systems during a why investigation without explicit confirmation.

## Pond discipline

- Through the MCP gateway, use `pond_pond_search` to find relevant conversational messages, then `pond_pond_get_session` from the end to capture the final state. Use `mcpScript` when several Pond calls need logic between them.
- Search does not include tool bodies or reasoning. Use `pond_pond_get_message` or scoped `pond_pond_sql` when the answer depends on commands, failures, or tool parameters.
- Scope by workspace, topic, date, or session. Do not treat the nearest vector result as proof.
- A missing Pond result means only that the searchable corpus did not surface evidence.

## Output

- **Question.** The rationale being investigated.
- **Code anchor.** Paths, lines, symbols, and commits.
- **Direct evidence.** Cited statements from commits, MRs, tickets, docs, comments, tests, or past sessions.
- **Reasonable inference.** The evidence chain and calibrated confidence.
- **Competing hypotheses.** Evidence for and against each, when more than one survives.
- **Unknowns.** Specific gaps and unavailable sources.
- **Sources consulted.** What was searched, what was found, and what was unavailable or irrelevant.

When the investigation precedes a change, finish with `Preserve`, `Change`, `Avoid`, and `Risk` constraints for planning.
