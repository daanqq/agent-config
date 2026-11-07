---
name: mars-logs
description: Reads events and service, request, and plugin logs from the Mars admin panel (mars.esoft.cloud) through chrome-devtools. Use before pulling Mars events such as `users.userHasBeenFired` or `users.updatedInfo`, or any Mars log data.
compatibility: Requires the chrome-devtools MCP server and the T3 Code `request_secret` tool. Works in Pi and Claude Code.
---

# Mars logs

Mars is the Space admin panel (`https://mars.esoft.cloud`, the page title says `prod`). It is production and read-only for you: only POST the list/log endpoints below, click nothing that resends or cancels events. The API is the panel's own, uses the page session cookie, and is called with `fetch` from a logged-in Mars page through `evaluate_script`.

## Login

Open the target Mars URL with `new_page`/`navigate_page`. A login form (`Логин`, `Пароль`, `Войти`; also `Войти по ключу`) means no session: it is `/login?&state=<base64 of the target path>` and returns to the target after login. Never ask the user to log in by hand and never print credentials; follow the login rule in `chrome-devtools`.

1. `request_secret` twice with `delivery: "file"` (login, then password); each returns `{"status":"saved","file":"<path>"}`.
2. `python3 -I <skill>/scripts/make_login.py "$D/login.js" <login file> <password file>` with `D=$(mktemp -d)` under `umask 077`.
3. `evaluate_script` with `sourcePath: "$D/login.js"`, then delete `login.js` and `$D`.
4. `wait_for` text that proves the target loaded (the panel's header shows `сеанс 59 мин.` right after login, so expect the session to expire in about an hour; re-login when the form reappears).

## Requests

All are `POST`, `content-type: application/json`, timestamps are epoch seconds as strings (the panel's URL filters use local-time ISO strings, the API does not).

- `/api/list/events?limit=N&offset=M`: body `{status: ["SENDED","CANCEL","FAILED","RECEIVED","FRONT"], createDateFrom, createDateTo, type, entityId}`; `type` and `entityId` are optional filters. Returns `{rows, count}`. A row has `_id`, `date` (ISO), `type`, `entity`, `entityId` (number; compare as strings, ids can be huge), `status`, `payload` (a JSON string, parse it), `logsSummary` (`[{service, status, attempts}]`).
- `/api/services/logs`: body `{services: ["users"], severity: ["error","warn"], dateFrom, dateTo}`. Returns a bare array of `{labels: {level, module, pod, operation}, log, date}`, where `date` is nanoseconds as a string. No paging parameters were found; unfiltered calls returned 300 rows, so treat 300 as a cap. `createDateFrom/To` returned nothing here: use `dateFrom/dateTo`.
- `/api/requests/logs?offset=M&limit=N`: body `{services: ["users"], textSearch: "216736", codes: [], dateFrom, dateTo}`. Returns ClickHouse-style `{meta, data, rows, rows_before_limit_at_least, statistics}`; `data` rows may be arrays, zip them with `meta[].name`. `textSearch` works reliably only on short windows (the session assumed up to 24 h, not verified).
- `/api/plugins/logs?limit=N&offset=M`: same ClickHouse-style shape; body filter `{hookName}` is what the UI sends. It returned HTTP 500 for some limits and `Clickhouse timed out` on wide windows and `{}` bodies; date keys for it were not confirmed.

Errors come back as plain text, not JSON: `connection 261 to 10.181.32.120:27017 timed out`, `Clickhouse timed out`. Calling `.json()` on them throws `Unexpected token 'c'`, and indexing `rows` on an error object gave `KeyError: 'rows'`. Always read `.text()`, check content-type, then parse.

## Collect

What worked in the session: filter by `entityId` when you have it, split the range into windows (30 min for a busy type), pages of 50 with a 250-400 ms pause, retry text errors after about 2 s. One `evaluate_script` that looped over 3 types and up to 2000 offsets hung until `Runtime.callFunctionOn timed out` (180 s) and returned nothing.

- One `evaluate_script` call must finish in well under 60 s. Use `scripts/chunk.js` as `sourcePath` with `filePath` for the output: edit its `CFG`, call repeatedly until `done: true`. State persists in `window.__mars[key]` until the page navigates.
- Every window gets a status: `ok` (all rows), `empty`, `error` (with the server text), `partial` (page limit, time budget, array cap, or a short page). Split `partial` windows and rerun them; do not read the result as complete.
- Parse the output file with `python3 -I`, not by pasting it into context. Exports of prod data go to `/tmp`; delete them when done.

## Before analysis

State what the data covers: windows and their statuses, row count versus the `count` field, endpoints with caps, and everything that was `error` or `partial`. A conclusion such as "no `users.updatedInfo` for this user" holds only for `ok` or `empty` windows. In the session a scan with `limit=50, offset=0` per window silently dropped events where `count > 50`.
