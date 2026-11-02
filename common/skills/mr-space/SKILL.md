---
name: mr-space
description: Commit message and merge request title for Space (Космос) service repositories under ~/deploy/env/development/services (GitLab group `ecosystem`). Use before committing to one of them or opening its merge request.
---

# Space commit and MR title

Space repositories name the work by its branch, not by a summary of the change:

- **Commit message**: exactly the branch name, one line, no body. For example `feature/T-3052`.
- **MR title**: the same branch name, `feature/T-3052`.

The EChat format `<summary> #T-<id>` from `mr-echat` does not apply here.
