---
name: publish-artifact-page
description: Publish a local HTML file to GitLab Pages at pages.esoft.tech/tidy/artifacts, or replace an already published page, and return its URL. Use when the user asks to publish, update, or share an HTML artifact, or to get a link to it.
---

Publishes one self-contained HTML file as `public/<slug>/index.html` in the GitLab project `tidy/artifacts` (id `2800`, host `git.esoft.tech`, branch `main`) without cloning it. The page is served at `https://pages.esoft.tech/tidy/artifacts/<slug>/` to anyone on the internal network, without login. Two modes: **new** creates a page under a fresh slug; **update** replaces the `index.html` of a published page and keeps its URL. The repository README (https://git.esoft.tech/tidy/artifacts) is the human manual; this file is the agent procedure.

## API access

REST paths below are relative to `https://git.esoft.tech/api/v4/`. Use `glab api --hostname git.esoft.tech <path>` if `glab auth status --hostname git.esoft.tech` succeeds, otherwise `curl -H "PRIVATE-TOKEN: $GITLAB_TOKEN"` if `GET user` succeeds with it. Never print the token or ask the user to paste it into the chat. With neither, follow [No API access](#no-api-access) at step 5.

## Steps

1. **Version.** With API access, fetch the current skill: `GET projects/2800/repository/files/.agents%2Fskills%2Fpublish-artifact-page%2FSKILL.md/raw?ref=main`. If you are running an installed copy that differs from it, follow the fetched text from here on. Done when you know which text you follow and whether the installed copy is stale.
2. **File.** Take the HTML file from the user's request or the session context. If several candidates fit, ask which one. Done when exactly one existing file is chosen.
3. **Checks.** Inspect the file and keep each finding for the summary:
   - Root-relative `src="/…"` or `href="/…"` break under `/tidy/artifacts/`. Blocker: offer to rewrite them or stop.
   - Relative references to local files (anything that is not `data:`, `#…`, `http(s)://` or `mailto:`) are not published. Blocker: offer to inline them or stop.
   - External `http(s)://` resources load only if the viewer can reach them. Warning.
   - Secret-looking strings (`glpat-`, JWT `eyJ…`, `-----BEGIN … PRIVATE KEY`, assignments like `password=` or `token:`) and personal data (emails, phone numbers). Warning, since the page is open to the whole internal network.
   - Size above 20 MB. Warning.
   Embedded video and images cannot be reviewed; say so if present. Done when every check has a result.
4. **Target.** Settle the mode and the slug:
   - **Update** when the user asks to update or replace a published page, or names its URL or slug. Take the slug from the URL path after `/tidy/artifacts/`. If the page is not named, list `GET projects/2800/repository/tree?path=public&ref=main&per_page=100` and propose the closest folder by file name or title; never pick one silently. `GET projects/2800/repository/files/public%2F<slug>%2Findex.html?ref=main` must succeed: keep its `last_commit_id`, and fetch the same path with `/raw` to compare in step 5.
   - **New** otherwise. Build `YYYY-MM-DD-<kebab-case>` from today's date and the page title or file name: lowercase ASCII, transliterated, at most 60 characters. `GET projects/2800/repository/tree?path=public/<slug>&ref=main` must return 404 (`glab` exits non-zero on it; that is the expected result); otherwise pick another slug. If an existing folder matches the file name or title (for example the file is a new revision such as `name (3).html`), ask whether the user means to update that page.
   Done when the mode is settled and the slug is free (new), exists (update), or, without access, unchecked.
5. **Confirm.** Show the file, size, mode, slug, final URL and check results. For an update, also show old and new size and a short summary of what changed in the visible text. Then ask «Публикуем?» (new) or «Обновляем?» (update) in the user's language and wait. Only a clear yes continues. Without API access, follow [No API access](#no-api-access) instead.
6. **Publish.** Write the commit payload to a temp file outside the user's project and POST it. Pass `last_commit_id` from step 4 for an update and an empty string for a new page:

   ```sh
   payload=$(mktemp)
   python3 -I - "$file" "$slug" "$last_commit_id" > "$payload" <<'EOF'
   import base64, json, sys
   path, slug, last_commit_id = sys.argv[1:]
   action = {"file_path": f"public/{slug}/index.html", "encoding": "base64",
             "content": base64.b64encode(open(path, "rb").read()).decode()}
   if last_commit_id:
       action.update(action="update", last_commit_id=last_commit_id)
   else:
       action.update(action="create")
   verb = "Update" if last_commit_id else "Add"
   print(json.dumps({"branch": "main", "commit_message": f"{verb} {slug}", "actions": [action]}))
   EOF
   glab api --hostname git.esoft.tech -X POST projects/2800/repository/commits -H 'Content-Type: application/json' --input "$payload"
   # or: curl -sS -H "PRIVATE-TOKEN: $GITLAB_TOKEN" -H 'Content-Type: application/json' --data-binary @"$payload" https://git.esoft.tech/api/v4/projects/2800/repository/commits
   rm -f "$payload"
   ```

   A 400 means the page changed under you: `create` finds the file already there, and `update` finds a newer commit than `last_commit_id`. Go back to step 4 and reconfirm. Done when the response contains the commit `id`.
7. **Verify.** Poll `GET projects/2800/pipelines?sha=<commit id>` until `success`; on `failed`, report the tail of `GET projects/2800/jobs/<job id>/trace`, and if it stays `pending` for over 3 minutes, report that no runner picked it up. Then poll the URL until `curl -s "$url" | sha256sum` equals `sha256sum "$file"`: Pages deploys asynchronously and lags the pipeline by seconds to minutes, and during an update the old page keeps answering 200. Give up after 5 minutes and report the last status. Done when the served page matches the file.
8. **Report.** Give the `https://` URL. After an update, add that browsers may show the old version for up to 10 minutes (`cache-control: max-age=600`) until a hard reload. Then, if `~/.claude/skills/publish-artifact-page/SKILL.md` is missing or stale, offer to install or update it, and on yes write the text fetched in step 1 there.

## No API access

Steps 2-4 still run: the slug stays unchecked, and an update takes it from the URL the user gives. Then reply in one message, in this order, and stop:

1. **Token first.** Say you have no GitLab API access and recommend setting it up, so this page and every next one publishes automatically: create a personal access token with the `api` scope at https://git.esoft.tech/-/user_settings/personal_access_tokens, then run `glab auth login --hostname git.esoft.tech` (works in the current session) or add `export GITLAB_TOKEN=...` to the shell profile (needs a new agent session). Offer to publish as soon as it is set up.
2. **Manual fallback.** Only then give the slug, the final URL, the mode (for an update: replace `index.html` in the existing folder), a note that the slug is unchecked, and the README section «Вручную»: https://git.esoft.tech/tidy/artifacts#вручную.
