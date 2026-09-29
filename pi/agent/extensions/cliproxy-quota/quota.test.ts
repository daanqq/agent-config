import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import test from "node:test";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { aggregatePoolQuota, fetchPoolQuotaFromManagement, fetchSharedPoolQuota, formatPoolDetails, formatPoolFooter, nearestPoolReset, nearestPoolWindowReset, poolWindowResetIncrease, type AccountQuota, type PoolQuota } from "./quota.ts";
import { isCLIProxyProvider } from "./index.ts";

function account(name: string, fiveHour: number, weekly: number): AccountQuota {
	return {
		name,
		windows: {
			"5h": { remaining: fiveHour, resetsAt: Date.now() + 60_000 },
			"7d": { remaining: weekly, resetsAt: Date.now() + 60_000 },
		},
	};
}

test("averages equal subscription capacity across two accounts", () => {
	const now = Date.now();
	const one = account("one", 80, 40);
	const two = account("two", 20, 60);
	for (const item of [one, two]) {
		item.windows["5h"]!.resetsAt = now + 3 * 60 * 60_000;
		item.windows["7d"]!.resetsAt = now + (6 * 24 + 4) * 60 * 60_000;
	}
	const pool = aggregatePoolQuota(2, [one, two]);
	assert.equal(pool.windows["5h"]?.remaining, 50);
	assert.equal(pool.windows["7d"]?.remaining, 50);
	assert.equal(formatPoolFooter(pool, now), "50%/3h+50% 50%/6d4h+50%");
});

test("shows partial account availability instead of pretending the whole pool was measured", () => {
	const now = Date.now();
	const pool = aggregatePoolQuota(2, [account("one", 80, 40)], ["two: HTTP 401"]);
	assert.equal(formatPoolFooter(pool, now), "1/2 80%/1m+20% 40%/1m+60%");
});

test("recognizes both CLIProxy provider ids", () => {
	assert.equal(isCLIProxyProvider("openai-codex"), true);
	assert.equal(isCLIProxyProvider("cliproxy"), true);
	assert.equal(isCLIProxyProvider("openrouter"), false);
});

test("formats per-subscription status like the Codex quota command", () => {
	const pool = aggregatePoolQuota(1, [{
		...account("one", 80, 40),
		email: "one@example.com",
		planType: "plus",
		availableResetCount: 1,
	}]);
	const text = formatPoolDetails(pool);
	assert.match(text, /subscription 1/);
	assert.match(text, /email: one@example\.com/);
	assert.match(text, /5h window\n    remaining: 80%/);
	assert.match(text, /7d window\n    remaining: 40%/);
	assert.match(text, /available usage resets: 1/);
});

test("uses the earliest future reset across subscriptions", () => {
	const now = Date.now();
	const first = account("one", 80, 40);
	const second = account("two", 20, 60);
	first.windows["5h"]!.resetsAt = now + 6 * 60 * 60_000;
	first.windows["7d"]!.resetsAt = now + 6 * 60 * 60_000;
	second.windows["5h"]!.resetsAt = now + 2 * 60 * 60_000;
	second.windows["7d"]!.resetsAt = now + 8 * 60 * 60_000;
	assert.equal(nearestPoolReset([first, second], now), now + 2 * 60 * 60_000);
	assert.equal(nearestPoolWindowReset([first, second], "5h", now), now + 2 * 60 * 60_000);
	assert.equal(nearestPoolWindowReset([first, second], "7d", now), now + 6 * 60 * 60_000);
	assert.equal(poolWindowResetIncrease([first, second], "5h", now + 2 * 60 * 60_000), 40);
	assert.equal(poolWindowResetIncrease([first, second], "7d", now + 6 * 60 * 60_000), 30);
});

test("loads Codex quota through the CLIProxyAPI management API", async () => {
	const requests: Array<{ url: string; init?: RequestInit }> = [];
	const fetchImpl: typeof fetch = async (input, init) => {
		const url = String(input);
		requests.push({ url, init });
		if (url.endsWith("/auth-files")) {
			return Response.json({
				files: [{
					name: "codex-one.json",
					provider: "codex",
					auth_index: "auth-one",
					email: "one@example.com",
					disabled: false,
					id_token: { "https://api.openai.com/auth": { chatgpt_account_id: "account-one" } },
				}],
			});
		}
		return Response.json({
			status_code: 200,
			body: JSON.stringify({
				plan_type: "plus",
				rate_limit: {
					primary_window: { used_percent: 20, reset_at: Date.now() + 60_000, limit_window_seconds: 18_000 },
					secondary_window: { used_percent: 60, reset_at: Date.now() + 120_000, limit_window_seconds: 604_800 },
				},
			}),
		});
	};

	const pool = await fetchPoolQuotaFromManagement({
		managementUrl: "http://127.0.0.1:8317/",
		managementKey: "management-secret",
		fetchImpl,
	});

	assert.equal(pool.totalAccounts, 1);
	assert.equal(pool.accounts[0]?.email, "one@example.com");
	assert.equal(pool.accounts[0]?.windows["5h"]?.remaining, 80);
	assert.equal(pool.accounts[0]?.windows["7d"]?.remaining, 40);
	assert.equal(requests[0]?.url, "http://127.0.0.1:8317/v0/management/auth-files");
	assert.equal(new Headers(requests[0]?.init?.headers).get("Authorization"), "Bearer management-secret");
	const apiCall = JSON.parse(String(requests[1]?.init?.body));
	assert.equal(apiCall.auth_index, "auth-one");
	assert.equal(apiCall.header.Authorization, "Bearer $TOKEN$");
	assert.equal(apiCall.header["Chatgpt-Account-Id"], "account-one");
});

test("requires a plaintext CLIProxyAPI management key", async () => {
	await assert.rejects(
		fetchPoolQuotaFromManagement({
			managementUrl: "http://127.0.0.1:8317",
			managementKey: "",
			fetchImpl: async () => assert.fail("fetch must not run without a management key"),
		}),
		/CLIPROXY_MANAGEMENT_KEY/,
	);
});

test("deduplicates concurrent quota refreshes across processes through the shared cache", async () => {
	const cacheDir = await mkdtemp(join(tmpdir(), "cliproxy-quota-test-"));
	const pool: PoolQuota = aggregatePoolQuota(1, [account("one", 80, 40)]);
	let refreshes = 0;
	const fetchQuota = async (): Promise<PoolQuota> => {
		refreshes++;
		await new Promise((resolve) => setTimeout(resolve, 25));
		return pool;
	};

	try {
		const results = await Promise.all(Array.from({ length: 10 }, () => fetchSharedPoolQuota({ cacheDir, fetchQuota })));
		assert.equal(refreshes, 1);
		assert.equal(results.length, 10);
		assert.ok(results.every((result) => result === pool || result.accounts[0]?.name === "one"));
	} finally {
		await rm(cacheDir, { recursive: true, force: true });
	}
});
