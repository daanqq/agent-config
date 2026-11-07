// Template for chrome-devtools `evaluate_script` (pass as `sourcePath`, output via `filePath`).
// Edit CFG, run once per call, repeat until the result has `done: true`.
// State lives in window.__mars[CFG.key] and survives between calls until the page navigates.
async () => {
  const CFG = {
    key: 'job1',                       // new key = new job; same key resumes
    endpoint: '/api/list/events',      // or /api/requests/logs, /api/plugins/logs (paged); /api/services/logs (array, no paging)
    paged: true,                       // false for /api/services/logs
    body: {                            // fixed part of the POST body
      status: ['SENDED', 'CANCEL', 'FAILED', 'RECEIVED', 'FRONT'],
      type: 'users.updatedInfo',
    },
    fromKey: 'createDateFrom',         // events: createDateFrom/createDateTo; services/logs: dateFrom/dateTo
    toKey: 'createDateTo',
    windows: [[1793854800, 1793856600]], // [from, to) in epoch seconds, as in the recorded requests
    pageSize: 50,
    maxPages: 6,                       // per window; above that the window is `partial`: split it
    pauseMs: 300,
    retries: 2,
    budgetMs: 45000,                   // keep one call well under the 180 s protocolTimeout
    arrayCap: 300,                     // services/logs returned 300 rows when unfiltered; treat >= cap as partial
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t0 = Date.now();
  const state = ((window.__mars ??= {})[CFG.key] ??= { next: 0, results: [] });
  const startNext = state.next;

  // events/requests: {rows, count}; services/logs: bare array; plugins/logs: ClickHouse-style {data, meta, rows_before_limit_at_least}.
  const unwrap = (j) => Array.isArray(j)
    ? { got: j, total: null }
    : { got: Array.isArray(j.rows) ? j.rows : j.data, total: j.count ?? j.rows_before_limit_at_least ?? null };

  // One request -> {status:'ok', json} or {status:'error', error}. Never throws.
  const call = async (body, offset) => {
    const url = `${CFG.endpoint}${CFG.paged ? `?limit=${CFG.pageSize}&offset=${offset}` : ''}`;
    let error = 'unknown';
    for (let a = 0; a <= CFG.retries; a++) {
      try {
        const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
        const text = await res.text();
        const isJson = (res.headers.get('content-type') || '').includes('json');
        if (res.ok && isJson) {
          try {
            const json = JSON.parse(text);
            if (Array.isArray(unwrap(json).got)) return { status: 'ok', json };
            error = `unexpected shape: ${text.slice(0, 200)}`;
          } catch { error = `bad JSON: ${text.slice(0, 200)}`; }
        } else {
          error = `HTTP ${res.status}: ${text.slice(0, 200)}`; // Mars sends plain text such as "connection N to host:27017 timed out"
        }
      } catch (e) { error = `fetch failed: ${e.message}`; }
      if (a < CFG.retries) await sleep(2000);
    }
    return { status: 'error', error };
  };

  while (state.next < CFG.windows.length && Date.now() - t0 < CFG.budgetMs) {
    const [from, to] = CFG.windows[state.next];
    const body = { ...CFG.body, [CFG.fromKey]: String(from), [CFG.toKey]: String(to) };
    const rows = [];
    let total = null;
    let out = null;
    for (let page = 0; ; page++) {
      if (Date.now() - t0 >= CFG.budgetMs) { out = { status: 'partial', reason: 'time budget' }; break; }
      const r = await call(body, page * CFG.pageSize);
      if (r.status === 'error') { out = { status: rows.length ? 'partial' : 'error', error: r.error }; break; }
      const { got, total: t } = unwrap(r.json);
      rows.push(...got);
      if (!CFG.paged) { out = { status: got.length >= CFG.arrayCap ? 'partial' : 'ok', reason: got.length >= CFG.arrayCap ? 'array cap' : undefined }; break; }
      total = t ?? total;
      if (total === null ? got.length < CFG.pageSize : rows.length >= total) { out = { status: 'ok' }; break; }
      if (!got.length) { out = { status: 'partial', reason: 'empty page before count reached' }; break; }
      if (page + 1 >= CFG.maxPages) { out = { status: 'partial', reason: 'page limit' }; break; }
      await sleep(CFG.pauseMs);
    }
    // Budget hit before anything finished in this call: record the window as partial instead of looping forever.
    if (out.reason === 'time budget' && state.next > startNext) break; // else retry this window in the next call
    if (out.status === 'ok' && !rows.length) out.status = 'empty';
    state.results.push({ from, to, total, got: rows.length, ...out, rows });
    state.next++;
    await sleep(CFG.pauseMs);
  }

  // Per-chunk return: only windows finished in this call, with the status of each.
  const fresh = state.results.slice(state.results.length - (state.next - startNext));
  return {
    done: state.next >= CFG.windows.length,
    next: state.next,
    of: CFG.windows.length,
    elapsedMs: Date.now() - t0,
    windows: fresh,
  };
};
