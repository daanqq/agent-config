import { readFile } from "node:fs/promises";
import { dirname } from "node:path";
import { stripFrontmatter, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	type AutocompleteItem,
	type AutocompleteProvider,
	type AutocompleteSuggestions,
	fuzzyFilter,
} from "@earendil-works/pi-tui";

type SkillInfo = {
	name: string;
	description?: string;
	filePath: string;
	baseDir: string;
};

const MAX_SUGGESTIONS = 100;
const SKILL_TOKEN_BEFORE_CURSOR = /(?:^|[\s([{])\$([a-z0-9-]*)$/;
const SKILL_MARKER = /(^|[\s([{])\$([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/g;
const SKILL_AUTOCOMPLETE_CONTEXT = /(?:^|[\s([{])\$[a-z0-9-]*$/;
const TRAILING_SKILL_TOKEN_WITH_SPACES = /(?:^|[\s([{])\$([a-z0-9-]*)\s*$/;

function getSkills(pi: ExtensionAPI): SkillInfo[] {
	return pi
		.getCommands()
		.filter((command) => command.source === "skill" && command.name.startsWith("skill:"))
		.map((command) => ({
			name: command.name.slice("skill:".length),
			description: command.description,
			filePath: command.sourceInfo.path,
			baseDir: command.sourceInfo.baseDir ?? dirname(command.sourceInfo.path),
		}))
		.sort((a, b) => a.name.localeCompare(b.name));
}

function skillToAutocompleteItem(skill: SkillInfo): AutocompleteItem {
	return {
		value: `$${skill.name}`,
		label: `$${skill.name}`,
		description: skill.description,
	};
}

function filterSkills(skills: SkillInfo[], query: string): AutocompleteItem[] {
	if (!query.trim()) {
		return skills.slice(0, MAX_SUGGESTIONS).map(skillToAutocompleteItem);
	}

	const prefixMatches = skills
		.filter((skill) => skill.name.startsWith(query))
		.slice(0, MAX_SUGGESTIONS)
		.map(skillToAutocompleteItem);

	if (prefixMatches.length > 0) return prefixMatches;

	return fuzzyFilter(skills, query, (skill) => `${skill.name} ${skill.description ?? ""}`)
		.slice(0, MAX_SUGGESTIONS)
		.map(skillToAutocompleteItem);
}

function createSkillAutocompleteProvider(pi: ExtensionAPI, current: AutocompleteProvider): AutocompleteProvider {
	return {
		triggerCharacters: ["$"],

		async getSuggestions(lines, cursorLine, cursorCol, options): Promise<AutocompleteSuggestions | null> {
			const currentLine = lines[cursorLine] ?? "";
			const beforeCursor = currentLine.slice(0, cursorCol);
			const match = beforeCursor.match(SKILL_TOKEN_BEFORE_CURSOR);
			const query = match?.[1];
			const skills = getSkills(pi);

			if (query === undefined) {
				const trailingSkillToken = beforeCursor.match(TRAILING_SKILL_TOKEN_WITH_SPACES);
				const completedQuery = trailingSkillToken?.[1];
				if (completedQuery !== undefined && !skills.some((skill) => skill.name === completedQuery)) return null;
				return current.getSuggestions(lines, cursorLine, cursorCol, options);
			}

			const exactSkill = skills.some((skill) => skill.name === query);
			if (exactSkill && !options.force) return null;

			const items = filterSkills(skills, query);
			if (options.signal.aborted || items.length === 0) return null;

			return {
				prefix: `$${query}`,
				items,
			};
		},

		applyCompletion(lines, cursorLine, cursorCol, item, prefix) {
			if (!prefix.startsWith("$")) {
				return current.applyCompletion(lines, cursorLine, cursorCol, item, prefix);
			}

			const currentLine = lines[cursorLine] ?? "";
			const beforePrefix = currentLine.slice(0, cursorCol - prefix.length);
			const afterCursor = currentLine.slice(cursorCol);
			const suffix = afterCursor.startsWith(" ") || afterCursor.startsWith("\t") ? "" : " ";
			const newLine = `${beforePrefix}${item.value}${suffix}${afterCursor}`;
			const newLines = [...lines];
			newLines[cursorLine] = newLine;

			return {
				lines: newLines,
				cursorLine,
				cursorCol: beforePrefix.length + item.value.length + suffix.length,
			};
		},

		shouldTriggerFileCompletion(lines, cursorLine, cursorCol) {
			const currentLine = lines[cursorLine] ?? "";
			const beforeCursor = currentLine.slice(0, cursorCol);
			if (SKILL_AUTOCOMPLETE_CONTEXT.test(beforeCursor)) return true;

			const trailingSkillToken = beforeCursor.match(TRAILING_SKILL_TOKEN_WITH_SPACES);
			const query = trailingSkillToken?.[1];
			if (query !== undefined && !getSkills(pi).some((skill) => skill.name === query)) return false;

			return current.shouldTriggerFileCompletion?.(lines, cursorLine, cursorCol) ?? true;
		},
	};
}

async function expandDollarSkills(text: string, skills: SkillInfo[]): Promise<string | undefined> {
	const skillsByName = new Map(skills.map((skill) => [skill.name, skill]));
	const selectedSkills: SkillInfo[] = [];
	const selectedNames = new Set<string>();

	const task = text
		.replace(SKILL_MARKER, (marker, prefix: string, name: string) => {
			const skill = skillsByName.get(name);
			if (!skill) return marker;

			if (!selectedNames.has(name)) {
				selectedNames.add(name);
				selectedSkills.push(skill);
			}

			return prefix;
		})
		.trim();

	if (selectedSkills.length === 0) return undefined;

	const skillBlocks = await Promise.all(
		selectedSkills.map(async (skill) => {
			const content = await readFile(skill.filePath, "utf8");
			const body = stripFrontmatter(content).trim();
			return `<skill name="${skill.name}" location="${skill.filePath}">\nReferences are relative to ${skill.baseDir}.\n\n${body}\n</skill>`;
		}),
	);

	return task ? `${skillBlocks.join("\n\n")}\n\n${task}` : skillBlocks.join("\n\n");
}

export default function skillDollarExtension(pi: ExtensionAPI) {
	pi.on("session_start", (_event, ctx) => {
		if (!ctx.hasUI) return;
		ctx.ui.addAutocompleteProvider((current) => createSkillAutocompleteProvider(pi, current));
	});

	pi.on("input", async (event, ctx) => {
		let transformed: string | undefined;
		try {
			transformed = await expandDollarSkills(event.text, getSkills(pi));
		} catch (error) {
			ctx.ui.notify(`Failed to load skill: ${error instanceof Error ? error.message : String(error)}`, "error");
			return { action: "continue" };
		}

		if (!transformed) return { action: "continue" };
		return { action: "transform", text: transformed };
	});
}
