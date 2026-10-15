# Architectural critique rubric

Apply only the lenses relevant to the subsystem.

## Interface depth

- Does the interface hide meaningful implementation complexity, or mirror it back to callers?
- Do callers need internal ordering rules, state details, or transport shapes to use it correctly?
- Would deleting an abstraction simplify the system, or spread its complexity across callers?

## Data and state model

- Do the types represent runtime states honestly?
- Are invalid combinations expressible through optional fields or scattered booleans?
- Does code repeatedly reshape data because the model does not match access patterns?
- Are identity, ownership, generation, ordering, and lifecycle explicit where they matter?

## Boundary discipline

- Are parsing, validation, compatibility, and error translation concentrated at real external boundaries?
- Does internal business logic depend on framework, transport, or persistence details?
- Can the subsystem be exercised through a focused interface, or does every test need the whole application?

## Coupling and locality

- Do independently changing concerns depend on one another?
- Does one behavior require scattered edits or repeated conditionals across callers?
- Is mutable state wider or longer-lived than the invariant requires?
- Are wrappers and delegation layers reducing reader load or merely adding hops?

## Evolution and consistency

- For a likely next requirement suggested by current code or issues, is the change local or cross-cutting?
- Does the subsystem follow an established repository pattern? If it differs, is the reason visible?
- Are legacy paths preserved without a known consumer?

## Complexity versus value

- Is complexity concentrated around genuine domain constraints?
- Can deletion, a better data shape, or a deeper interface remove concepts rather than rearrange them?
- Avoid proposing abstractions for hypothetical variation or rewrites without demonstrated cost.
