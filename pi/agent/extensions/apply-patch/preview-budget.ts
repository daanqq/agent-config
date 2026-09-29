import { closeSync, constants, fstatSync, openSync, readSync } from "node:fs";

export const MAX_PREVIEW_BYTES = 256 * 1024;
export const MAX_PREVIEW_LINES = 4_000;
const MAX_PREVIEW_COMPARISONS = 200_000;

export class PreviewLimitError extends Error {}

/** One budget for the entire preview, not for each file or hunk. Never limits patch execution. */
export class PreviewBudget {
	private bytesLeft = MAX_PREVIEW_BYTES;
	private comparisonsLeft = MAX_PREVIEW_COMPARISONS;
	private linesLeft = MAX_PREVIEW_LINES;

	consumeText(text: string): void {
		this.bytesLeft -= Buffer.byteLength(text, "utf8");
		if (this.bytesLeft < 0) throw new PreviewLimitError("text budget exceeded");
		if (--this.linesLeft < 0) throw new PreviewLimitError("line budget exceeded");
		for (const char of text) {
			if (char === "\n" && --this.linesLeft < 0) {
				throw new PreviewLimitError("line budget exceeded");
			}
		}
	}

	compare(): void {
		if (--this.comparisonsLeft < 0) throw new PreviewLimitError("hunk search budget exceeded");
	}

	readFile(path: string): string {
		// Bound the read itself as well as the initial size check (the file may grow).
		const fd = openSync(path, constants.O_RDONLY | constants.O_NONBLOCK);
		try {
			const stat = fstatSync(fd);
			if (!stat.isFile() || stat.size > this.bytesLeft) throw new PreviewLimitError("file budget exceeded");
			const buffer = Buffer.allocUnsafe(stat.size + 1);
			let length = 0;
			while (length < buffer.length) {
				const read = readSync(fd, buffer, length, buffer.length - length, null);
				if (read === 0) break;
				length += read;
			}
			if (length === buffer.length) throw new PreviewLimitError("file grew during preview");
			const text = buffer.toString("utf8", 0, length);
			this.consumeText(text);
			return text;
		} finally {
			closeSync(fd);
		}
	}
}
