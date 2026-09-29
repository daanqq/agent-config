# Epistemics for historical rationale

## Evidence classes

**Direct evidence** explicitly states intent or a motivating constraint. Examples: an MR discussion says why an alternative was rejected, a ticket states the product requirement, or a postmortem assigns the change as an action item.

**Corroborated inference** combines independent facts that support one explanation without stating it directly. Explain the chain and use calibrated language such as `likely`, `appears to`, or `suggests`.

**Hypothesis** is plausible but underdetermined. State what evidence would confirm or reject it.

**Unknown** means the searched record does not answer the question. It is a valid result.

## Confidence

- **High.** A direct statement tied to the shipped change, or several independent sources agreeing without contradiction.
- **Medium.** Strong indirect evidence or one direct source whose authority or timing is uncertain.
- **Low.** A plausible interpretation with missing links, stale context, or unresolved contradiction.

Do not convert low confidence into firm prose during editing.

## Citation rules

- Cite commits, MR numbers or URLs, task IDs, document links, Pond session or message IDs, and `file:line` comments or tests.
- A current implementation can show what happens. It cannot by itself prove why the author chose it.
- A null search result is bounded by source, query, scope, and date. State those bounds.
- Tickets, comments, and early plans can be superseded. Prefer later decisions tied to the shipped artifact, while preserving contradictions.
- The user's suggested explanation is a hypothesis until independently supported.

## Synthesis check

Before finalizing, ask:

1. Which statements are direct evidence?
2. Which statements are inference, and is their chain visible?
3. What competing explanation still fits?
4. Which source would most likely contain the missing answer?
5. Did a later source supersede an earlier conclusion?
