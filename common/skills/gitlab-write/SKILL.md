---
name: gitlab-write
description: Use before posting, replying to, or editing a GitLab comment (MR or issue note, line discussion, review reply). Sets the authorship label and the post-and-verify procedure.
compatibility: Requires glab authenticated for the GitLab host.
---

# GitLab write

A comment goes out under the user's GitLab account and notifies colleagues. The
**label** tells readers the agent wrote it; the account only says who asked.

## Label

The first line of every comment, reply, or amended note you write is the label,
even when the user did not ask for it:

```
> 🤖 Комментарий написал Claude <модель> в рамках ревью задачи <задача>.
```

- `<модель>` is the model you run as, from your system context, for example
  `Claude Opus 5.5`. A non-Claude model writes its own name in place of
  `Claude <модель>`.
- `<задача>` is the reviewed task ID (`T-…` or `EUTP-…`), written bare: GitLab
  autolinks it to the task in SpaceHub. Never put a work ID (`J-…`) there; its
  autolink does not lead to the work. Keep ` в рамках ревью задачи …` only for a
  comment made during a review; otherwise end the line after the model.
- Write nothing else about authorship: no "posted from <name>'s account" and
  no signature at the end. The rest of the text is written in the first person
  of the agent.

When amending a note the agent wrote, keep its label.

## Permission

An instruction to publish authorizes posting. An instruction to write, draft, or
reply authorizes a draft: show the exact text, label included, and wait for
approval. Approval covers the text shown; any later change needs it again.

## Text

Apply [`unslop`](../unslop/SKILL.md). Write in the language of the MR or thread.
Write `@name` only for a real login you mean to notify; put roles and code in
backticks. Use no em dash.

## Post

1. Confirm the acting account: `glab api user --hostname <host>`.
2. For a finding on code, post a line discussion. Read the MR: its `sha` must
   equal `diff_refs.head_sha`, and the line must exist on the new side of the MR
   diff (`git diff -U0 <base_sha>...<head_sha> -- <path>`). If HEAD moved, re-check
   the finding on the new HEAD before posting.
3. Build the payload with a JSON encoder, not shell quoting, so multi-line
   Cyrillic and code fences survive:

   ```json
   {"body": "<text>", "position": {"position_type": "text",
     "base_sha": "<base_sha>", "start_sha": "<start_sha>", "head_sha": "<head_sha>",
     "old_path": "<path>", "new_path": "<path>", "new_line": <line>}}
   ```

   ```bash
   glab api -X POST "projects/<project>/merge_requests/<iid>/discussions" \
     --hostname <host> -H "Content-Type: application/json" --input payload.json
   ```

   For a general MR comment, omit `position`. Replies inside a thread and
   amendments use the endpoints in
   [`fix-gitlab-mr-review`](../fix-gitlab-mr-review/SKILL.md#write-and-publish).

## Verify

Read the note back (`GET .../notes/<note-id>`) and compare its body with the
posted text exactly. If a request timed out, check whether it succeeded before
retrying. Done when every posted note is read back unchanged; report its
discussion ID, note ID, file and line.
