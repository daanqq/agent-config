# Quality Gate

Use before finalizing any non-trivial code change. Review the diff as if it will receive a strict maintainability review.

Completion criterion: every question is checked against the actual diff; any structural regression is fixed or reported as a risk.

Ask:

1. Is there a code-judo move that would make this simpler by deleting branches, modes, helpers, or concepts?
2. Did the change add ad-hoc conditionals, flags, nullable modes, or special cases into an already busy flow?
3. Is the logic in the canonical owning layer/module, or did feature-specific behavior leak into shared plumbing?
4. Did I introduce a helper, wrapper, abstraction, or generic mechanism that does not clearly reduce complexity?
5. Did I duplicate an existing utility or pattern instead of reusing the canonical one?
6. Did I make type boundaries worse with `any`, `unknown`, casts, unnecessary optionality, or silent fallback?
7. Did a file/component grow toward or past a size boundary, especially 1000 lines?
8. Are independent async steps serialized unnecessarily, or can related state updates become partially applied?
9. Would a reviewer reasonably say this works but makes the surrounding code more spaghetti?
10. Which existing services, helpers, components, icons, style tokens, or patterns did I check before adding a new one?
11. Did I replace an installed library's default behavior with manual DOM logic, measurements, animation, or configuration without a product requirement?
12. Does each new file or service live in the module that owns its domain concept rather than the nearest convenient directory?

For changes to business rules, persistence, permissions, external services,
retries, or user-visible state, also ask:

13. What happens when the entity already exists? Does lookup or reopening happen before creation-only checks?
14. What happens on a repeated or concurrent call? Can it duplicate effects, spend retries early, or leave optimistic state incorrect?
15. What state remains after a transient external-service failure, and will normal operation recover without manual repair?
16. Can `null`, `undefined`, an empty collection, or two missing identifiers accidentally pass a comparison or authorization check?
17. Did a new route or call path expand who can reach the behavior, and are role checks still valid on that path?
18. Is an actual failure distinguishable from a valid empty result or normal pagination end?
19. Does the order of lookup, authorization, validation, and side effects preserve valid existing-state behavior?

If any answer indicates structural regression, fix the structure before claiming the implementation is done.
