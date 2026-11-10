#!/usr/bin/env python3
"""Embed teaching-workspace components from assets/ into lessons and reference pages.

A viewer may open an HTML file on its own, without serving sibling files, so
relative links to ../assets/ do not load. assets/ stays the source of truth and
each page carries a copy:

  <link rel="stylesheet" href="../assets/X.css">  ->  <style data-asset="X.css">...</style>
  <script src="../assets/X.js"></script>           ->  <script data-asset="X.js">...</script>

Running again refreshes blocks that are already embedded.

Usage: python3 -I inline_assets.py <workspace-dir>
"""
import pathlib
import re
import sys

LINK = re.compile(r'<link rel="stylesheet" href="\.\./assets/([\w.-]+\.css)"\s*/?>')
SCRIPT = re.compile(r'<script src="\.\./assets/([\w.-]+\.js)"></script>')
STYLE_BLOCK = re.compile(r'<style data-asset="([\w.-]+\.css)">.*?</style>', re.S)
SCRIPT_BLOCK = re.compile(r'<script data-asset="([\w.-]+\.js)">.*?</script>', re.S)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    root = pathlib.Path(argv[0]).resolve()
    assets = root / "assets"
    if not assets.is_dir():
        print(f"no assets/ directory in {root}", file=sys.stderr)
        return 1

    def asset(name: str) -> str:
        # The closing tag inside a source would end the embedded block early.
        text = (assets / name).read_text(encoding="utf-8").strip()
        if re.search(r"</(style|script)", text, re.I):
            raise ValueError(f"assets/{name} contains a closing style/script tag")
        return text

    def style(match: re.Match) -> str:
        return f'<style data-asset="{match.group(1)}">\n{asset(match.group(1))}\n</style>'

    def script(match: re.Match) -> str:
        return f'<script data-asset="{match.group(1)}">\n{asset(match.group(1))}\n</script>'

    try:
        for page in sorted([*root.glob("lessons/*.html"), *root.glob("reference/*.html")]):
            text = page.read_text(encoding="utf-8")
            updated = text
            for pattern, render in ((LINK, style), (STYLE_BLOCK, style), (SCRIPT, script), (SCRIPT_BLOCK, script)):
                updated = pattern.sub(render, updated)
            if updated != text:
                page.write_text(updated, encoding="utf-8")
                print(f"updated {page.relative_to(root)}")
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
