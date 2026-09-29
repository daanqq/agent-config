# Skill mechanics

The skill-specific branch of [`writing-for-agents`](SKILL.md): what changes when the document is a skill (frontmatter, the invocation choice, and router skills). Everything else about writing it is the universal reference in `SKILL.md`.

## Invocation

Two choices, trading the two loads:

- A **model-invoked** skill keeps a `description`, so the agent can fire it autonomously, and other skills can reach it. You can still type its name: model-invocation always _includes_ user reach; a description only ever adds agent discovery, never removes the human's. The description is the skill's top-level context pointer, forced to stay loaded at all times: permanent context load in exchange for discoverability. A model-invoked skill whose content is all reference is also one home for shared reference: another skill can invoke it, so reference needed by several skills lives in one place. Mechanics: omit `disable-model-invocation`, and write a model-facing description carrying the trigger branches (the pointer-writing rules in `SKILL.md` apply in full).
- A **user-invoked** skill is hidden from Pi's automatic skill-discovery list when `disable-model-invocation: true`. Its description does not add to that list's context load, and users can still invoke it explicitly. This flag is not a file-access restriction: another skill can link to its `SKILL.md`, and the agent can read that file when the routing instructions call for it. Keep the description as a short human-facing summary.

Enable model invocation when the agent needs to discover the skill directly from a task. If it is reached only by explicit user invocation or a router's file link, hiding it can avoid an unnecessary discovery entry. Keep any direct-invocation restrictions in the skill's own instructions distinct from what the Pi flag actually does.

Shared reference can live in a plain file linked from both skills. Use that form when the material is reference rather than an independently useful workflow; a plain file is not required merely because both skills are hidden from discovery.

## Splitting by invocation

The invocation cut of splitting (the sequence cut lives in `SKILL.md`): split off a model-invoked skill when it needs its own task-based discovery trigger. A link from another skill alone does not require automatic discovery. You pay context load for the new always-loaded description, so that independent reach has to be worth it.

## Router skills

When user-invoked skills multiply past what you can remember, use a **router skill** that names the alternatives and when to read each one. The router can direct the agent to read a linked `SKILL.md`, including one hidden from automatic discovery. State whether the route executes that workflow or only consults it as reference, and respect any explicit invocation restrictions in the target's instructions.
