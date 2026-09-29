import { PreviewBudget } from "./preview-budget.ts";

export interface NumberedDiffLine {
	marker: "+" | "-" | " ";
	lineNumber?: number;
	text: string;
}

export function formatPatchSummaryCounts(
	summary: string,
	formatAdded: (text: string) => string,
	formatRemoved: (text: string) => string,
	formatMuted: (text: string) => string,
): string {
	return summary
		.split("\n")
		.map((line) => {
			const counts = line.match(/^(.*?)(\+\d+)(\s+)(-\d+)$/);
			if (!counts) return formatMuted(line);
			return `${formatMuted(counts[1]!)}${formatAdded(counts[2]!)}${formatMuted(counts[3]!)}${formatRemoved(counts[4]!)}`;
		})
		.join(formatMuted("\n"));
}

export function formatNumberedDiffLines(lines: NumberedDiffLine[]): string[] {
	const width = lines.reduce((width, { lineNumber }) => Math.max(width, lineNumber === undefined ? 0 : String(lineNumber).length), 1);
	return lines.map(({ marker, lineNumber, text }) => {
		const gutter = lineNumber === undefined ? "".padStart(width) : String(lineNumber).padStart(width);
		return `${marker}${gutter} ${text}`;
	});
}

export function visualizeWhitespaceOnlyChanges(diffText: string): string {
	const lines = diffText.split("\n");
	const result: string[] = [];
	let index = 0;

	while (index < lines.length) {
		const removed: ParsedChangedLine[] = [];
		while (index < lines.length) {
			const parsed = parseChangedLine(lines[index]!);
			if (parsed?.marker !== "-") break;
			removed.push(parsed);
			index += 1;
		}

		if (removed.length === 0) {
			result.push(lines[index]!);
			index += 1;
			continue;
		}

		const added: ParsedChangedLine[] = [];
		while (index < lines.length) {
			const parsed = parseChangedLine(lines[index]!);
			if (parsed?.marker !== "+") break;
			added.push(parsed);
			index += 1;
		}

		if (removed.length === added.length) {
			const renderedRemoved: string[] = [];
			const renderedAdded: string[] = [];
			for (let pairIndex = 0; pairIndex < removed.length; pairIndex++) {
				const oldLine = removed[pairIndex]!;
				const newLine = added[pairIndex]!;
				const visualized = visualizeWhitespacePair(oldLine.content, newLine.content);
				if (visualized) {
					renderedRemoved.push(withContent(oldLine, visualized.oldText));
					renderedAdded.push(withContent(newLine, visualized.newText));
				} else {
					renderedRemoved.push(oldLine.raw);
					renderedAdded.push(newLine.raw);
				}
			}
			result.push(...renderedRemoved, ...renderedAdded);
		} else {
			result.push(...removed.map((line) => line.raw), ...added.map((line) => line.raw));
		}
	}

	return result.join("\n");
}

type ParsedChangedLine = { marker: "+" | "-"; gutter: string; content: string; raw: string };

function parseChangedLine(line: string): ParsedChangedLine | undefined {
	const parsed = line.match(/^([+-])(\s*\d*) (.*)$/);
	if (!parsed) return undefined;
	const content = parsed[3]!;
	return {
		marker: parsed[1] as "+" | "-",
		gutter: parsed[2]!,
		content,
		raw: line,
	};
}

function withContent(line: ParsedChangedLine, content: string): string {
	return `${line.raw.slice(0, line.raw.length - line.content.length)}${content}`;
}

function isWhitespace(char: string | undefined): boolean {
	return char === " " || char === "\t";
}

function visibleWhitespace(text: string): string {
	return text.replace(/ /g, "·").replace(/\t/g, "→");
}

function visualizeWhitespacePair(
	oldText: string,
	newText: string,
): { oldText: string; newText: string } | undefined {
	if (oldText === newText) return undefined;
	if (oldText.replace(/[ \t]/g, "") !== newText.replace(/[ \t]/g, "")) return undefined;

	let oldIndex = 0;
	let newIndex = 0;
	let visualizedOld = "";
	let visualizedNew = "";

	while (oldIndex < oldText.length || newIndex < newText.length) {
		const oldWhitespaceStart = oldIndex;
		while (isWhitespace(oldText[oldIndex])) oldIndex++;
		const newWhitespaceStart = newIndex;
		while (isWhitespace(newText[newIndex])) newIndex++;

		const oldWhitespace = oldText.slice(oldWhitespaceStart, oldIndex);
		const newWhitespace = newText.slice(newWhitespaceStart, newIndex);
		if (oldWhitespace === newWhitespace) {
			visualizedOld += oldWhitespace;
			visualizedNew += newWhitespace;
		} else {
			visualizedOld += visibleWhitespace(oldWhitespace);
			visualizedNew += visibleWhitespace(newWhitespace);
		}

		if (oldIndex === oldText.length || newIndex === newText.length) break;
		if (oldText[oldIndex] !== newText[newIndex]) return undefined;
		visualizedOld += oldText[oldIndex];
		visualizedNew += newText[newIndex];
		oldIndex++;
		newIndex++;
	}

	return { oldText: visualizedOld, newText: visualizedNew };
}

export function buildUpdatePreview(numbered: NumberedDiffLine[], hasMovePath: boolean): { added: number; removed: number; lines: string[]; pureMove: boolean } {
	const added = numbered.filter((line) => line.marker === "+").length;
	const removed = numbered.filter((line) => line.marker === "-").length;
	const pureMove = hasMovePath && added === 0 && removed === 0;
	return { added, removed, lines: pureMove ? [] : formatNumberedDiffLines(numbered), pureMove };
}

export function buildReplacementPreview(original: string[], replacement: string[]): { added: number; removed: number; lines: string[] } {
	return {
		added: replacement.length,
		removed: original.length,
		lines: formatNumberedDiffLines([
			...original.map((text, index) => ({ marker: "-" as const, lineNumber: index + 1, text })),
			...replacement.map((text, index) => ({ marker: "+" as const, lineNumber: index + 1, text })),
		]),
	};
}

export function numberUpdateDiffLines(original: string[], body: string[], budget = new PreviewBudget()): NumberedDiffLine[] {
	const result: NumberedDiffLine[] = [];
	let searchFrom = 0;
	let lineDelta = 0;

	for (const hunk of splitHunks(body)) {
		const oldPattern = hunk.lines
			.filter((line) => line[0] === " " || line[0] === "-")
			.map((line) => line.slice(1));
		const anchorFrom = findAnchor(original, hunk.header, searchFrom);
		const oldStart = findSequence(original, oldPattern, anchorFrom, budget)
			?? (anchorFrom !== searchFrom ? findSequence(original, oldPattern, searchFrom, budget) : undefined)
			?? searchFrom;
		if (result.length > 0 && oldStart > searchFrom) {
			result.push({ marker: " ", text: "⋮" });
		}
		let oldLine = oldStart + 1;
		let newLine = oldStart + 1 + lineDelta;
		let added = 0;
		let removed = 0;

		for (const line of hunk.lines) {
			const marker = line[0];
			if (marker !== "+" && marker !== "-" && marker !== " ") continue;
			if (marker === "-") {
				result.push({ marker, lineNumber: oldLine, text: line.slice(1) });
				oldLine += 1;
				removed += 1;
			} else if (marker === "+") {
				result.push({ marker, lineNumber: newLine, text: line.slice(1) });
				newLine += 1;
				added += 1;
			} else {
				result.push({ marker, lineNumber: newLine, text: line.slice(1) });
				oldLine += 1;
				newLine += 1;
			}
		}
		searchFrom = oldLine - 1;
		lineDelta += added - removed;
	}

	return result;
}

function splitHunks(body: string[]): Array<{ header?: string; lines: string[] }> {
	const hunks: Array<{ header?: string; lines: string[] }> = [];
	let current: { header?: string; lines: string[] } = { lines: [] };
	for (const line of body) {
		if (line.startsWith("@@")) {
			if (current.lines.length > 0) hunks.push(current);
			const header = line.slice(2).trim();
			current = { ...(header ? { header } : {}), lines: [] };
		} else if (line !== "*** End of File") {
			current.lines.push(line);
		}
	}
	if (current.lines.length > 0) hunks.push(current);
	return hunks;
}

function findAnchor(lines: string[], header: string | undefined, from: number): number {
	if (!header) return from;
	const exact = lines.indexOf(header, from);
	if (exact !== -1) return exact + 1;
	const trimmed = header.trim();
	const fuzzy = lines.findIndex((line, index) => index >= from && line.trim() === trimmed);
	return fuzzy === -1 ? from : fuzzy + 1;
}

function findSequence(lines: string[], sequence: string[], from: number, budget: PreviewBudget): number | undefined {
	if (sequence.length === 0) return from;
	for (let index = from; index <= lines.length - sequence.length; index += 1) {
		if (sequence.every((line, offset) => {
			budget.compare();
			return lines[index + offset] === line;
		})) return index;
	}
	const trimmedSequence = sequence.map((line) => line.trim());
	for (let index = from; index <= lines.length - sequence.length; index += 1) {
		if (trimmedSequence.every((line, offset) => {
			budget.compare();
			return lines[index + offset]!.trim() === line;
		})) return index;
	}
	return undefined;
}
