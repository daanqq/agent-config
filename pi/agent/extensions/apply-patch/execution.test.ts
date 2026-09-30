import assert from "node:assert/strict";
import { lstat, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { type TestContext } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import type { ExtensionToolContext } from "@earendil-works/pi-coding-agent";
import { discoverAndLoadExtensions, withFileMutationQueue } from "@earendil-works/pi-coding-agent";

async function fixture(t: TestContext) {
	const cwd = await mkdtemp(join(tmpdir(), "pi-apply-patch-test-"));
	t.after(() => rm(cwd, { recursive: true, force: true }));
	const { extensions, errors } = await discoverAndLoadExtensions(
		[fileURLToPath(new URL("./index.ts", import.meta.url))], cwd, join(cwd, "agent"),
	);
	assert.deepEqual(errors, []);
	const tool = extensions[0]?.tools.get("apply_patch")?.definition;
	assert.ok(tool);
	return {
		cwd,
		execute: (actions: string[], signal = t.signal) => tool.execute(
			"fixture",
			{ input: ["*** Begin Patch", ...actions, "*** End Patch"].join("\n") },
			signal,
			undefined,
			// execute only reads cwd; no agent session is needed for these file operations.
			{ cwd } as ExtensionToolContext,
		),
	};
}

test("deletes a symbolic link and its target without locking the same file twice", { timeout: 2_000 }, async (t) => {
	const { cwd, execute } = await fixture(t);
	const target = join(cwd, "target.txt");
	const link = join(cwd, "link.txt");
	await writeFile(target, "fixture\n");
	await symlink(target, link);

	const result = await execute([`*** Delete File: ${link}`, `*** Delete File: ${target}`]);
	assert.match(result.content[0]?.type === "text" ? result.content[0].text : "", /Applied patch successfully/);
	await assert.rejects(readFile(target), { code: "ENOENT" });
	await assert.rejects(lstat(link), { code: "ENOENT" });
});

test("creates files whose paths do not exist yet", { timeout: 2_000 }, async (t) => {
	const { cwd, execute } = await fixture(t);
	await execute(["*** Add File: new/directory/file.txt", "+created"]);
	assert.equal(await readFile(join(cwd, "new/directory/file.txt"), "utf8"), "created\n");
});

test("cancels a queued patch promptly and never applies it after the queue is released", { timeout: 2_000 }, async (t) => {
	const { cwd, execute } = await fixture(t);
	const target = join(cwd, "target.txt");
	await writeFile(target, "original\n");
	const entered = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	const holder = withFileMutationQueue(target, async () => {
		entered.resolve();
		await release.promise;
	});
	await entered.promise;
	const controller = new AbortController();
	const pending = execute(["*** Update File: target.txt", "@@", "-original", "+changed"], controller.signal);
	const rejected = assert.rejects(pending, /abort/i);
	try {
		await delay(30);
		controller.abort();
		await rejected;
		assert.equal(await readFile(target, "utf8"), "original\n");
	} finally {
		release.resolve();
		await holder;
	}
	await withFileMutationQueue(target, async () => {
		assert.equal(await readFile(target, "utf8"), "original\n");
	});
});

test("does not mutate files when already cancelled", { timeout: 2_000 }, async (t) => {
	const { cwd, execute } = await fixture(t);
	const controller = new AbortController();
	controller.abort();
	await assert.rejects(execute(["*** Add File: file.txt", "+created"], controller.signal), /abort/i);
	await assert.rejects(readFile(join(cwd, "file.txt")), { code: "ENOENT" });
});

test("releases acquired locks when cancelled while waiting for another file", { timeout: 2_000 }, async (t) => {
	const { cwd, execute } = await fixture(t);
	const first = join(cwd, "a.txt");
	const blocked = join(cwd, "b.txt");
	await writeFile(first, "original\n");
	await writeFile(blocked, "original\n");
	const entered = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	const holder = withFileMutationQueue(blocked, async () => {
		entered.resolve();
		await release.promise;
	});
	await entered.promise;
	const controller = new AbortController();
	const pending = execute([first, blocked].flatMap((path) => [
		`*** Update File: ${path}`, "@@", "-original", "+changed",
	]), controller.signal);
	const rejected = assert.rejects(pending, /abort/i);
	try {
		await delay(30);
		controller.abort();
		await rejected;
		await withFileMutationQueue(first, async () => {
			assert.equal(await readFile(first, "utf8"), "original\n");
		});
	} finally {
		release.resolve();
		await holder;
	}
	await withFileMutationQueue(blocked, async () => {
		assert.equal(await readFile(blocked, "utf8"), "original\n");
	});
});
