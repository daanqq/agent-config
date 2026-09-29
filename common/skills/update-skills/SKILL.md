---
name: update-skills
description: Reconcile shared and client-specific Agent Skills against their locked cached sources when explicitly requested.
disable-model-invocation: true
---

# Update skills

Resolve the maintenance directory relative to this skill. Read its
[`manifest.json`](../../skills-maintenance/manifest.json) and
[`README.md`](../../skills-maintenance/README.md).

1. Run `python3 <maintenance-dir>/check.py` before editing. Classify any drift
   as an intentional customization, an incomplete prior update, or unrelated
   damage before continuing. By default, an explicit update request covers all
   scopes. When the user names `pi`, `claude`, or `common`, limit edits to that
   scope; global inventory and collision checks still apply.
2. Refresh each unique upstream repository through the installed `librarian`
   skill under the active permission policy. Record the inspected commit. Do
   not guess an upstream for a `local` skill.
3. Compare each `exact` skill's complete directory with the old and new locked
   source. Sync only after confirming that no local customization would be lost.
   For an `overlay` skill, read its semantic overlay and reconstruct the result
   from the new source while preserving client behavior, tool names, permission
   boundaries, and bundled licenses. Do not replay a textual patch blindly.
4. A repository revision is shared across scopes. Before changing it, identify
   every affected skill and reconcile them together. If this exceeds an explicit
   client-only request, ask before expanding the scope; do not leave other
   clients on an unreconciled lock. Update embedded source revisions and overlays
   when accepted behavior or upstream ownership changes.
5. Refresh only accepted hashes with
   `python3 <maintenance-dir>/check.py --refresh-installed-hashes`, adding
   `--scope <scope>` for an explicitly restricted update. Then run
   `python3 <maintenance-dir>/check.py --check-sources` and review the complete
   diff with `git diff --check` from the platform repository.

Completion: every affected skill is reconciled to a recorded commit, every
retained customization is described semantically, relative links and licenses
remain intact, and inventory and source checks pass. Do not replace client
adaptations or silently refresh unrelated drift.
