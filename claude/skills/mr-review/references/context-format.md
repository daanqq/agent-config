# Generated context format

Preparation creates one owned workspace with three artifacts:

- `manifest.json` describes workspace ownership, private Git refs, source repositories, worktrees, and cleanup state.
- `review-context.json` is the canonical review input.
- `review-context.md` is the same input rendered for a human or an agent prompt.

`review-context.json` has `schema_version: 1` and these top-level fields:

- `generated_at`, `kind`, and `workspace` identify the preparation run.
- `scope_contract` defines the hard review boundary.
- `targets` contains one entry per MR or local repository.
- `primary_task` and `related_tasks` contain optional YouTrack/PORA responses.
- `additional_information` contains user-supplied context.
- `warnings` records unavailable optional metadata or task data.

Each target includes:

- `kind`, `repo`, and absolute `path`;
- `source_branch`, `base_ref`, `head_ref`, and exact `merge_base`;
- `scope`: `branch`, `working-tree`, or `all`;
- porcelain `status` and `untracked_files`;
- `file_sets` for branch, staged, unstaged, untracked, and final in-scope files;
- minimal `review_commands` derived from the exact refs and scope;
- optional `mr`, `task_id`, and task data.

The manifest and context deliberately exclude GitLab tokens and PORA sessions. Treat fetched task descriptions as internal project data even though they are not authentication secrets.
