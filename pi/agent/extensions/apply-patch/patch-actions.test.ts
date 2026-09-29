import assert from "node:assert/strict";
import test from "node:test";
import { parsePatchActionHeaders, parsePatchActions } from "./patch-actions.ts";

test("accepts replacing a file with consecutive delete and add actions", () => {
	const actions = parsePatchActions([
		"*** Begin Patch",
		"*** Delete File: target.ts",
		"*** Add File: target.ts",
		"+replacement",
		"*** End Patch",
	].join("\n"));

	assert.deepEqual(actions.map(({ type, path }) => ({ type, path })), [
		{ type: "delete", path: "target.ts" },
		{ type: "add", path: "target.ts" },
	]);
});

test("shows a delete-add replacement as one in-progress target", () => {
	const targets = parsePatchActionHeaders([
		"*** Begin Patch",
		"*** Delete File: target.ts",
		"*** Add File: target.ts",
	].join("\n"));

	assert.deepEqual(targets, [{ path: "target.ts" }]);
});

test("keeps repeated non-replacement actions visible", () => {
	const targets = parsePatchActionHeaders([
		"*** Begin Patch",
		"*** Update File: target.ts",
		"@@",
		"-old",
		"+middle",
		"*** Update File: target.ts",
	].join("\n"));

	assert.deepEqual(targets, [{ path: "target.ts" }, { path: "target.ts" }]);
});

test("reports an empty move update hunk", () => {
	assert.throws(
		() => parsePatchActions([
			"*** Begin Patch",
			"*** Update File: source.ts",
			"*** Move to: target.ts",
			"*** End Patch",
		].join("\n")),
		/Update file hunk for 'source\.ts' is empty/,
	);
});
