export interface ParsedPatchAction {
	type: "add" | "delete" | "update";
	path: string;
	movePath?: string | undefined;
	newFile?: string | undefined;
	lines?: string[] | undefined;
}

interface PatchActionHeader {
	type: "add" | "delete" | "update";
	path: string;
	movePath?: string | undefined;
}

export function parsePatchActionHeaders(text: string): Array<{ path: string; movePath?: string | undefined }> {
	const actions: PatchActionHeader[] = [];
	let current: PatchActionHeader | undefined;
	for (const line of text.split("\n")) {
		const header = parseActionHeader(line);
		if (header) {
			current = header;
			actions.push(current);
			continue;
		}
		if (current && line.startsWith("*** Move to: ")) current.movePath = normalizePatchPath(line.slice("*** Move to: ".length));
	}

	const collapsed: PatchActionHeader[] = [];
	for (const action of actions) {
		const previous = collapsed.at(-1);
		if (action.type === "add" && previous?.type === "delete" && previous.path === action.path) {
			collapsed[collapsed.length - 1] = { type: "update", path: action.path };
		} else {
			collapsed.push(action);
		}
	}

	return collapsed
		.filter((action) => action.path.length > 0)
		.map(({ path, movePath }) => ({ path, ...(movePath ? { movePath } : {}) }));
}

export function parsePatchActions(text: string): ParsedPatchAction[] {
	// The bundled binary accepts both LF and CRLF patches. Normalize here too so
	// the TUI preview does not report a false "No files were modified" after a
	// CRLF patch was successfully applied.
	const lines = text.trim().replace(/\r\n?/g, "\n").split("\n");
	if (lines.length < 2 || !lines[0]!.startsWith("*** Begin Patch") || lines.at(-1) !== "*** End Patch") {
		throw new Error("Invalid patch text");
	}
	const actions: ParsedPatchAction[] = [];
	let index = 1;
	while (index < lines.length - 1) {
		const line = lines[index]!;
		if (line.startsWith("*** Add File: ")) {
			const path = normalizePatchPath(line.slice("*** Add File: ".length));
			index += 1;
			const newLines: string[] = [];
			while (index < lines.length - 1 && !isActionHeader(lines[index]!)) {
				const value = lines[index]!;
				if (!value.startsWith("+")) throw new Error(`Invalid Add File line: ${value}`);
				newLines.push(value.slice(1));
				index += 1;
			}
			actions.push({ type: "add", path, newFile: newLines.length === 0 ? "" : `${newLines.join("\n")}\n` });
			continue;
		}
		if (line.startsWith("*** Delete File: ")) {
			const path = normalizePatchPath(line.slice("*** Delete File: ".length));
			actions.push({ type: "delete", path });
			index += 1;
			continue;
		}
		if (line.startsWith("*** Update File: ")) {
			const path = normalizePatchPath(line.slice("*** Update File: ".length));
			index += 1;
			let movePath: string | undefined;
			if (index < lines.length - 1 && lines[index]!.startsWith("*** Move to: ")) {
				movePath = normalizePatchPath(lines[index]!.slice("*** Move to: ".length));
				index += 1;
			}
			const bodyStart = index;
			while (index < lines.length - 1 && !isActionHeader(lines[index]!)) index += 1;
			const bodyLines = lines.slice(bodyStart, index);
			if (bodyLines.length === 0) throw new Error(`Update file hunk for '${path}' is empty`);
			actions.push({ type: "update", path, movePath, lines: bodyLines });
			continue;
		}
		throw new Error(`Invalid patch hunk: ${line}`);
	}
	if (actions.length === 0) throw new Error("No files were modified.");
	return actions;
}

export function normalizePatchPath(path: string): string {
	const trimmed = path.trim();
	const withoutAt = trimmed.startsWith("@") ? trimmed.slice(1) : trimmed;
	return withoutAt.replace(/^['"]|['"]$/g, "");
}

function parseActionHeader(line: string): PatchActionHeader | undefined {
	if (line.startsWith("*** Add File: ")) return { type: "add", path: normalizePatchPath(line.slice("*** Add File: ".length)) };
	if (line.startsWith("*** Delete File: ")) return { type: "delete", path: normalizePatchPath(line.slice("*** Delete File: ".length)) };
	if (line.startsWith("*** Update File: ")) return { type: "update", path: normalizePatchPath(line.slice("*** Update File: ".length)) };
	return undefined;
}

function isActionHeader(line: string): boolean {
	return line.startsWith("*** Add File: ") || line.startsWith("*** Delete File: ") || line.startsWith("*** Update File: ");
}
