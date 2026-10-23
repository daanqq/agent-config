# Analysis checks

Each check guards a pitfall seen in a past task analysis. Apply every check whose
condition matches the task before writing conclusions.

## Spatial claims from images

Condition: a conclusion depends on where elements sit relative to each other in a
screenshot or video frame: above or below, overlap, which element covers which.

1. For every image involved, record the pixel coordinates (top and bottom `y`, left
   and right `x`) of each element the claim compares, then derive the relation from
   the numbers rather than from the overall impression.
2. Keep relations per image. When images disagree, say so instead of generalizing
   one image into platform behavior.
3. In the answer, mark which image claims were measured and which remain visual
   impressions.

Completion criterion: every spatial claim in the answer cites its coordinates or is
labeled unmeasured.

Why: in T-2394 the first analysis stated that the iOS menu opened above the
selection after "checking pixels"; the coordinates showed it below, and the
recommendation weakened only after the user asked.
