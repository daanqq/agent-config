#!/usr/bin/env python3
"""Render a single-file HTML overview of code changes from a content JSON.

Usage: python3 build.py <content.json> <out.html>

Content JSON (all text fields accept `code` and **bold**; blank-line separated
paragraphs; a paragraph made only of "- " lines becomes a list):

{
  "repo": "/abs/path/to/repo",
  "lang": "ru",
  "title": "...", "eyebrow": "...", "intro": "...",
  "labels": {"overview": "...", "step": "Коммит {n} из {total}", "show_code": "...", "hide_code": "...",
             "before": "...", "after": "...", "validation": "...",
             "previous": "...", "next": "...", "close": "..."},  # last three: image viewer buttons
  "subject_strip": "\\s*#[A-Z]+-\\d+$",            # optional regex removed from commit subjects
  "demo": [                                         # optional validation evidence, one item per scenario
    {"video": "/abs/clip.mp4", "width": 1136, "height": 1246, "caption": "...",
     "controls": false},                            # controls adds pause and seek for long clips
    {"before": "/abs/before.png", "after": "/abs/after.png", "caption": "..."},
    {"image": "/abs/shot.png", "caption": "..."}
  ],
  "demo_lead": "...",                               # optional: where and how it was checked
  "sections": [
    {"rev": "<commit>", "title": "...", "lead": "...",
     "blocks": [{"title": "...", "text": "...",
                 "refs": [["path/in/repo", "start substring", "end substring"], ["path"]]}]}
  ]
}

A section with "rev" shows that commit's diff (rev^..rev) and subject; a section
with "base" and "head" instead shows the combined diff of that range.
A ref with substrings shows only the diff lines inside that range of the new
file; a ref with a path only shows the whole file diff. Every substring must
occur exactly once in the file at the shown revision.
"demo" (a single object is accepted too) renders as the validation section right
after the intro, before the commit sections. Screenshots are PNG or JPEG.
Landscape ones (desktop) take the column width, before above after; portrait
ones (mobile) sit side by side, like the video halves. Every screenshot opens
in the page's image viewer, which pages through all of them.
"""
import base64
import html
import json
import re
import struct
import subprocess
import sys

CONTENT, OUT = sys.argv[1], sys.argv[2]
C = json.load(open(CONTENT))
REPO = C['repo']
L = {
    'overview': 'Overview', 'step': 'Commit {n} of {total}', 'show_code': 'Show full code',
    'hide_code': 'Collapse code', 'before': 'Before', 'after': 'After', 'validation': 'Validation',
    'previous': 'Previous', 'next': 'Next', 'close': 'Close', **C.get('labels', {}),
}


def git(*args):
    return subprocess.run(['git', '-C', REPO, *args], capture_output=True, check=True).stdout.decode(errors='replace')


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', text)


def md(text):
    parts = []
    for para in text.strip().split('\n\n'):
        lines = [line.strip() for line in para.strip().split('\n') if line.strip()]
        if not lines:
            continue
        if all(line.startswith('- ') for line in lines):
            parts.append('<ul>' + ''.join(f'<li>{inline(line[2:])}</li>' for line in lines) + '</ul>')
        else:
            parts.append(f'<p>{inline(" ".join(lines))}</p>')
    return '\n'.join(parts)


def diff_rows(old, new, path):
    rows, new_no, in_hunk = [], 0, False
    for line in git('diff', old, new, '--', path).split('\n'):
        m = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
        if m:
            new_no, in_hunk = int(m.group(1)), True
            rows.append(('gap', new_no, ''))
            continue
        kind = {'+': 'add', '-': 'del', ' ': 'ctx'}.get(line[:1]) if in_hunk else None
        if kind:
            rows.append((kind, new_no, line[1:]))
            if kind != 'del':
                new_no += 1
    return rows


def find_range(rev, path, start, end):
    lines = git('show', f'{rev}:{path}').split('\n')
    hits = [i for i, line in enumerate(lines) if start in line]
    if len(hits) != 1:
        sys.exit(f'{path}: "{start}" occurs {len(hits)} times at {rev}')
    s = hits[0]
    e = s if end is None else next((i for i in range(s, len(lines)) if end in lines[i]), None)
    if e is None:
        sys.exit(f'{path}: "{end}" not found after "{start}" at {rev}')
    return s + 1, e + 1


def trim_context(rows, keep=1):
    """Keeps changed lines with `keep` context lines around them; cut places become gaps."""
    changed = [i for i, r in enumerate(rows) if r[0] in ('add', 'del')]
    near = {j for i in changed for j in range(i - keep, i + keep + 1)}
    out = []
    for i, r in enumerate(rows):
        if r[0] in ('add', 'del') or (r[0] == 'ctx' and i in near):
            out.append(r)
        elif out and out[-1][0] != 'gap':
            out.append(('gap', r[1], ''))
    while out and out[-1][0] == 'gap':
        out.pop()
    return out


def snippet(old, new, ref):
    path, start, end = (list(ref) + [None, None])[:3]
    rows = diff_rows(old, new, path)
    if not rows:
        sys.exit(f'{path}: no diff between {old} and {new}')
    if start:
        s, e = find_range(new, path, start, end)
        rows = [r for r in rows if r[0] != 'gap' and s <= r[1] <= e]
    body = ''.join(
        '<span class="gap">⋯</span>' if kind == 'gap' else f'<span class="{kind}">{html.escape(text) or " "}</span>'
        for kind, _, text in trim_context(rows)
    )
    return f'<div class="path">{html.escape(path)}</div><pre>{body}</pre>'


toc, body = [], []
total = len(C['sections'])
for n, section in enumerate(C['sections'], 1):
    if 'rev' in section:
        new = git('rev-parse', section['rev']).strip()
        old = git('rev-parse', f'{new}^').strip()
        subject = git('log', '-1', '--format=%s', new).strip()
        if C.get('subject_strip'):
            subject = re.sub(C['subject_strip'], '', subject)
        step = L['step'].format(n=n, total=total) + f'<span class="subject">{html.escape(subject)}</span>'
    else:
        old, new = section['base'], section['head']
        step = L['step'].format(n=n, total=total)
    toc.append(f'<li><a href="#c{n}"><span class="n">{n}</span>{html.escape(section["title"])}</a></li>')
    body.append(
        f'<section class="commit" id="c{n}"><div class="step">{step}</div>'
        f'<h2>{html.escape(section["title"])}</h2><p class="lead">{inline(section["lead"])}</p>'
    )
    for block in section['blocks']:
        code = ''.join(snippet(old, new, ref) for ref in block['refs'])
        body.append(
            f'<article class="block"><h3>{html.escape(block["title"])}</h3>{md(block["text"])}'
            f'<div class="code"><div class="code-body">{code}</div>'
            f'<button type="button" class="toggle" data-show="{html.escape(L["show_code"])}" '
            f'data-hide="{html.escape(L["hide_code"])}">{html.escape(L["show_code"])}</button></div></article>'
        )
    body.append('</section>')

def image(path):
    """Returns (mime, width, height, bytes) of a PNG or JPEG file."""
    data = open(path, 'rb').read()
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        width, height = struct.unpack('>II', data[16:24])
        return 'png', width, height, data
    i = 2 if data[:2] == b'\xff\xd8' else len(data)
    while i + 9 <= len(data):
        marker, length = data[i + 1], struct.unpack('>H', data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack('>HH', data[i + 5:i + 9])
            return 'jpeg', width, height, data
        i += 2 + length
    sys.exit(f'{path}: demo screenshots must be PNG or JPEG')


def img_tag(path, alt):
    mime, width, height, data = image(path)
    tag = (
        f'<img src="data:image/{mime};base64,{base64.b64encode(data).decode()}" '
        f'width="{width}" height="{height}" alt="{html.escape(alt)}">'
    )
    return width, height, tag


def demo_figure(d):
    caption = f'<figcaption>{inline(d["caption"])}</figcaption></figure>'
    if 'image' in d:
        width, height, tag = img_tag(d['image'], d['caption'])
        layout = 'stack' if width > height else 'row'
        return f'<figure class="demo"><div class="demo-pair {layout}"><div>{tag}</div></div>{caption}'
    if 'video' in d:
        data = base64.b64encode(open(d['video'], 'rb').read()).decode()
        return (
            f'<figure class="demo"><div class="demo-labels"><span>{html.escape(L["before"])}</span>'
            f'<span>{html.escape(L["after"])}</span></div>'
            f'<video src="data:video/mp4;base64,{data}" autoplay loop muted playsinline '
            f'{"controls " if d.get("controls") else ""}'
            f'width="{d["width"]}" height="{d["height"]}" aria-label="{html.escape(d["caption"])}"></video>'
            f'<figcaption>{inline(d["caption"])}</figcaption></figure>'
        )
    shots = {key: img_tag(d[key], L[key]) for key in ('before', 'after')}
    if shots['before'][:2] != shots['after'][:2]:
        print(f'warning: before and after differ in size: {d["before"]}, {d["after"]}', file=sys.stderr)
    width, height, _ = shots['before']
    layout = 'stack' if width > height else 'row'
    cells = ''.join(
        f'<div><span class="demo-label">{html.escape(L[key])}</span>{tag}</div>' for key, (_, _, tag) in shots.items()
    )
    return f'<figure class="demo"><div class="demo-pair {layout}">{cells}</div>{caption}'


demos = C.get('demo') or []
demos = demos if isinstance(demos, list) else [demos]
demo = ''
if demos:
    toc.insert(0, f'<li><a href="#validation"><span class="n">✓</span>{html.escape(L["validation"])}</a></li>')
    lead = f'<p class="lead">{inline(C["demo_lead"])}</p>' if C.get('demo_lead') else ''
    demo = (
        f'<section class="commit" id="validation"><h2>{html.escape(L["validation"])}</h2>{lead}'
        + ''.join(demo_figure(d) for d in demos) + '</section>'
    )

template = open(__file__.rsplit('/', 1)[0] + '/template.html').read()
page = template
for key, value in {
    'LANG': html.escape(C.get('lang', 'en')), 'TITLE': html.escape(C['title']),
    'EYEBROW': html.escape(C.get('eyebrow', '')), 'L_OVERVIEW': html.escape(L['overview']),
    'INTRO': md(C['intro']), 'DEMO': demo, 'TOC': '\n'.join(toc), 'BODY': '\n'.join(body),
    'L_PREVIOUS': html.escape(L['previous']), 'L_NEXT': html.escape(L['next']), 'L_CLOSE': html.escape(L['close']),
}.items():
    page = page.replace('{{' + key + '}}', value)
open(OUT, 'w').write(page)
print(f'written {OUT}: {total} sections, {sum(len(s["blocks"]) for s in C["sections"])} blocks, {len(page)} bytes')
