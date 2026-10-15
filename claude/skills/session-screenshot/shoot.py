#!/usr/bin/env python3
"""Render real Claude Code sessions as PNG terminal screenshots.

find     list sessions that invoked a skill or slash command
capture  resume a session copy in a headless tmux and save the screen
live     run a new prompt in a headless tmux, interrupt it, print the session id
render   turn a captured line range into HTML and a PNG
"""
import argparse
import glob
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

PROJECTS = os.path.expanduser("~/.claude/projects")
DEFAULT_FONT = "IosevkaTermSlab Nerd Font Mono"
# Variables of the calling Claude Code session. Inherited, they make the child
# think it is a subagent (transcript saving off, warning in the footer).
SESSION_ENV = [
    "TMUX", "TMUX_PANE", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "CLAUDECODE", "CLAUDE_PID",
    "CLAUDE_EFFORT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_EXECPATH",
]
WIDTH = 150
FOOTER_GAP = 3


def die(msg):
    sys.exit("error: " + msg)


# ---------- find ----------

def items_of(entry):
    c = entry.get("message", {}).get("content")
    return c if isinstance(c, list) else [{"type": "text", "text": c or ""}]


def cmd_find(a):
    name = a.name.lstrip("/")
    slash = f"<command-name>/{name}</command-name>"
    rows = []
    for path in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if name not in text:
            continue
        hit, cwd, after, users_after, total = None, None, [], 0, 0
        for line in text.splitlines():
            total += 1
            try:
                d = json.loads(line)
            except ValueError:
                continue
            cwd = cwd or d.get("cwd")
            if d.get("type") not in ("user", "assistant"):
                continue
            for x in items_of(d):
                t = x.get("type")
                if t == "text" and slash in x.get("text", ""):
                    m = re.search(r"<command-args>(.*?)</command-args>", x["text"], re.S)
                    hit, after, users_after = (d["timestamp"][:16], "slash", (m.group(1) if m else "")[:60]), [], 0
                elif t == "tool_use" and x.get("name") == "Skill" and x.get("input", {}).get("skill") == name:
                    hit, after, users_after = (d["timestamp"][:16], "model", str(x["input"].get("args", ""))[:60]), [], 0
                elif hit and t == "tool_use":
                    after.append(x["name"])
                elif (hit and t == "text" and d["type"] == "user" and not d.get("isMeta")
                      and not x.get("text", "").startswith("<")):
                    users_after += 1
        if hit:
            rows.append((hit[0], os.path.basename(path)[:-6], cwd, hit[1], hit[2], len(after), users_after, total))
    for ts, sid, cwd, how, args, n_after, users, total in sorted(rows):
        print(f"{ts}  {sid}  {cwd}  {how} args={args!r}  tools_after={n_after} "
              f"user_msgs_after={users} transcript_lines={total}")
    if not rows:
        print(f"no sessions invoked {name}")


# ---------- tmux helpers ----------

def clean_env():
    env = {k: v for k, v in os.environ.items() if k not in SESSION_ENV}
    env["COLORTERM"] = "truecolor"
    return env


def tmux(sock, *args, check=True):
    return subprocess.run(["tmux", "-L", sock, *args], check=check, capture_output=True, text=True).stdout


def start(sock, cwd, rows, argv):
    # tmux must be started with the clean env: its server environment is what the pane inherits.
    # tmux still sets TMUX in every pane, so drop it again there: inside tmux Claude Code falls back
    # to 256 colours (custom themes need truecolor) and adds a scroll hint above the prompt box.
    # A faked TERM_PROGRAM makes it clip wrapped non-ASCII lines, so leave it unset.
    subprocess.run(["tmux", "-L", sock, "-f", "/dev/null", "new-session", "-d", "-s", "cc",
                    "-x", str(WIDTH), "-y", str(rows), "-c", cwd, "env", "-u", "TMUX", "-u", "TMUX_PANE", *argv,
                    ";", "set", "-g", "default-terminal", "tmux-256color",
                    ";", "set", "-as", "terminal-features", ",*:RGB"],
                   check=True, env=clean_env())


def screen(sock, color=False):
    return tmux(sock, "capture-pane", "-p", *(["-e"] if color else []), "-t", "cc")


def wait_stable(sock, timeout=60):
    end, last, same = time.time() + timeout, None, 0
    while time.time() < end:
        time.sleep(1)
        s = screen(sock)
        same = same + 1 if s == last and "❯" in s else 0
        if same >= 3:
            return
        last = s
    die("Claude Code screen did not settle; inspect with tmux -L " + sock + " attach")


def rerender(sock, rows):
    # The first paint of a resumed transcript can clip long lines; a resize forces a clean layout.
    tmux(sock, "resize-window", "-t", "cc", "-x", str(WIDTH + 1), "-y", str(rows))
    time.sleep(2)
    tmux(sock, "resize-window", "-t", "cc", "-x", str(WIDTH), "-y", str(rows))
    wait_stable(sock)


def kill(sock):
    tmux(sock, "kill-server", check=False)


# ---------- capture ----------

def resolve(session):
    if session.endswith(".jsonl") and os.path.isfile(session):
        return os.path.abspath(session)
    hits = glob.glob(os.path.join(PROJECTS, "*", session + "*.jsonl"))
    if len(hits) != 1:
        die(f"session {session!r} matched {len(hits)} transcripts")
    return hits[0]


def session_cwd(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                cwd = json.loads(line).get("cwd")
            except ValueError:
                continue
            if cwd:
                return cwd
    die("no cwd in " + path)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def fitted_rows(text, rows):
    """Rows that keep the whole transcript and drop the empty gap above the prompt box."""
    lines = text.split("\n")
    run, best = 0, None
    for i, line in enumerate(lines):
        run = run + 1 if not line.strip() else 0
        if run > FOOTER_GAP:
            best = i
    gap = 0
    if best is not None:
        j = best
        while j >= 0 and not lines[j].strip():
            j -= 1
        k = best
        while k < len(lines) and not lines[k].strip():
            k += 1
        gap = k - j - 1
    return rows - max(0, gap - 2)


def snapshot(path, cwd, rows, verbose):
    sock = f"shot-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    argv = ["claude", "--resume", os.path.basename(path)[:-6]] + (["--verbose"] if verbose else [])
    start(sock, cwd, rows, argv)
    try:
        wait_stable(sock)
        rerender(sock, rows)
        return screen(sock), screen(sock, color=True)
    finally:
        kill(sock)


def cmd_capture(a):
    src = resolve(a.session)
    cwd = a.cwd or session_cwd(src)
    old_id = os.path.basename(src)[:-6]
    before = sha256(src)
    # Resume a renamed copy so the user's transcript cannot change.
    new_id = str(uuid.uuid4())
    copy = os.path.join(os.path.dirname(src), new_id + ".jsonl")
    with open(src, encoding="utf-8") as f:
        data = f.read().replace(old_id, new_id)
    with open(copy, "w", encoding="utf-8") as f:
        f.write(data)
    try:
        text, ansi = snapshot(copy, cwd, a.rows, a.verbose)
        if "Claude Code v" not in "\n".join(text.split("\n")[:6]):
            print(f"warning: transcript is taller than {a.rows} rows, the top is cut; raise --rows "
                  "or crop only the visible part", file=sys.stderr)
        else:
            fit = fitted_rows(text, a.rows)
            if fit < a.rows:
                text, ansi = snapshot(copy, cwd, fit, a.verbose)
    finally:
        # Everything named after the copy's fresh UUID belongs to this capture.
        claude_dir = os.path.expanduser("~/.claude")
        for leftover in (glob.glob(os.path.join(claude_dir, "*", new_id + "*"))
                         + glob.glob(os.path.join(claude_dir, "*", "*", new_id + "*"))):
            if os.path.isdir(leftover):
                shutil.rmtree(leftover)
            else:
                os.remove(leftover)
    if sha256(src) != before:
        print("warning: the original transcript changed during capture", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "screen.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(a.out, "screen.ansi"), "w", encoding="utf-8") as f:
        f.write(ansi)
    print_index(text, a.out)


def print_index(text, out):
    lines = text.rstrip("\n").split("\n")
    print(f"saved {out}/screen.txt and screen.ansi, {len(lines)} rows")
    for i, line in enumerate(lines, 1):
        if re.match(r"^(❯|●|✻|\S.*Claude Code v)|^  (Ran|Read|Searched|Called|called) ", line) or "⏵⏵" in line:
            print(f"{i:5}  {line[:110]}")


# ---------- live ----------

def cmd_live(a):
    cwd = os.path.abspath(a.cwd)
    existing = set(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")))
    sock = f"shot-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    start(sock, cwd, a.rows, ["claude"] + (["--verbose"] if a.verbose else []))
    try:
        wait_stable(sock)
        tmux(sock, "send-keys", "-t", "cc", "-l", a.prompt)
        time.sleep(1)
        tmux(sock, "send-keys", "-t", "cc", "Enter")
        end = time.time() + a.timeout
        while not re.search(a.until, screen(sock)):
            if time.time() > end:
                print("warning: --until did not match before --timeout; interrupting", file=sys.stderr)
                break
            time.sleep(2)
        time.sleep(a.settle)
        tmux(sock, "send-keys", "-t", "cc", "Escape")
        time.sleep(3)
    finally:
        kill(sock)
    found = [p for p in set(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))) - existing
             if session_cwd(p) == cwd]
    if len(found) != 1:
        die(f"expected one new session transcript in {cwd}, found {len(found)}")
    print("session", os.path.basename(found[0])[:-6])


# ---------- render ----------

def palette():
    """ANSI palette, background and foreground of the user's Ghostty theme, or xterm-like defaults."""
    pal = ["#000000", "#cd0000", "#00cd00", "#cdcd00", "#0000ee", "#cd00cd", "#00cdcd", "#e5e5e5",
           "#7f7f7f", "#ff0000", "#00ff00", "#ffff00", "#5c5cff", "#ff00ff", "#00ffff", "#ffffff"]
    bg, fg = "#ffffff", "#000000"
    conf_dir = os.path.expanduser("~/.config/ghostty")
    theme = None
    for name in ("config", "config.ghostty"):
        p = os.path.join(conf_dir, name)
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                m = re.match(r"\s*theme\s*=\s*\"?([^\"\n]+)", line)
                if m:
                    theme = m.group(1).strip()
    path = os.path.join(conf_dir, "themes", theme) if theme else None
    if path and os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\s*palette\s*=\s*(\d+)\s*=\s*(#[0-9a-fA-F]{6})", line)
            if m and int(m.group(1)) < 16:
                pal[int(m.group(1))] = m.group(2)
            m = re.match(r"\s*(background|foreground)\s*=\s*(#[0-9a-fA-F]{6})", line)
            if m:
                bg, fg = (m.group(2), fg) if m.group(1) == "background" else (bg, m.group(2))
    return pal, bg, fg


def color256(n, pal):
    if n < 16:
        return pal[n]
    if n < 232:
        n -= 16
        v = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (v[n // 36], v[n // 6 % 6], v[n % 6])
    g = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (g, g, g)


def apply_sgr(params, st, pal):
    p = [int(x) if x else 0 for x in params.split(";")] if params else [0]
    i = 0
    while i < len(p):
        n = p[i]
        if n == 0: st.clear()
        elif n == 1: st["b"] = 1
        elif n == 2: st["dim"] = 1
        elif n == 3: st["i"] = 1
        elif n == 4: st["u"] = 1
        elif n == 7: st["inv"] = 1
        elif n == 22: st.pop("b", None); st.pop("dim", None)
        elif n == 23: st.pop("i", None)
        elif n == 24: st.pop("u", None)
        elif n == 27: st.pop("inv", None)
        elif 30 <= n <= 37: st["fg"] = pal[n - 30]
        elif 90 <= n <= 97: st["fg"] = pal[n - 82]
        elif 40 <= n <= 47: st["bg"] = pal[n - 40]
        elif 100 <= n <= 107: st["bg"] = pal[n - 92]
        elif n == 39: st.pop("fg", None)
        elif n == 49: st.pop("bg", None)
        elif n in (38, 48) and i + 1 < len(p):
            key = "fg" if n == 38 else "bg"
            if p[i + 1] == 5:
                st[key] = color256(p[i + 2], pal); i += 2
            elif p[i + 1] == 2:
                st[key] = "#%02x%02x%02x" % tuple(p[i + 2:i + 5]); i += 4
        i += 1


def css(st, bg, fg):
    f, b = st.get("fg"), st.get("bg")
    if st.get("inv"):
        f, b = b or bg, f or fg
    out = []
    if f: out.append("color:" + f)
    if b: out.append("background:" + b)
    if st.get("b"): out.append("font-weight:700")
    if st.get("dim"): out.append("opacity:.6")
    if st.get("i"): out.append("font-style:italic")
    if st.get("u"): out.append("text-decoration:underline")
    return ";".join(out)


def to_html(ansi, first, last, font, size):
    pal, bg, fg = palette()
    # OSC sequences (OSC 8 hyperlinks and the like) are invisible in a terminal.
    ansi = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", ansi)
    lines = ansi.split("\n")
    st, out = {}, []
    # SGR state carries across lines, so walk from the top even when the crop starts lower.
    for n, line in enumerate(lines[:last], 1):
        buf = []
        for part in re.split(r"(\x1b\[[0-9;]*m)", line):
            m = re.fullmatch(r"\x1b\[([0-9;]*)m", part)
            if m:
                apply_sgr(m.group(1), st, pal)
            elif part:
                s = css(st, bg, fg)
                buf.append(f'<span style="{s}">{html.escape(part)}</span>' if s else html.escape(part))
        if n >= first:
            out.append("".join(buf))
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:{bg}}}'
            f'pre{{margin:0;padding:16px 20px;color:{fg};background:{bg};font:{size}px/1.3 "{font}";'
            f'white-space:pre;display:inline-block}}</style></head><body><pre>{chr(10).join(out)}</pre>'
            f'</body></html>'), len(out)


def chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    die("no Chrome/Chromium binary found")


def cmd_render(a):
    with open(os.path.join(a.dir, "screen.ansi"), encoding="utf-8") as f:
        ansi = f.read()
    total = ansi.rstrip("\n").count("\n") + 1
    last = min(a.to or total, total)
    if subprocess.run(["fc-list", a.font], capture_output=True, text=True).stdout.strip() == "":
        print(f"warning: font {a.font!r} is not installed; the browser will substitute it", file=sys.stderr)
    page, rows = to_html(ansi, a.start, last, a.font, a.size)
    png = os.path.abspath(a.png)
    page_path = png[:-4] + ".html"
    with open(page_path, "w", encoding="utf-8") as f:
        f.write(page)
    width = int(WIDTH * a.size * 0.5 + 60)
    height = int(rows * a.size * 1.3 + 40)
    # Chrome refuses captures taller than about 16k device pixels.
    scale = min(a.scale, 16000 / height)
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--force-device-scale-factor={scale:.2f}", f"--window-size={width},{height}",
                    f"--screenshot={png}", "file://" + page_path], check=True, capture_output=True)
    with open(png, "rb") as f:
        head = f.read(24)
    w, h = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    print(f"wrote {png} ({w}x{h}), rows {a.start}-{last}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find", help="list sessions that invoked a skill or slash command")
    p.add_argument("name")
    p.set_defaults(fn=cmd_find)
    p = sub.add_parser("capture", help="resume a session copy headlessly and save its screen")
    p.add_argument("session", help="session id (prefix) or transcript path")
    p.add_argument("--out", required=True, help="directory for screen.txt and screen.ansi")
    p.add_argument("--rows", type=int, default=1000, help="terminal height; must fit the transcript")
    p.add_argument("--verbose", action="store_true", help="expand tool output (claude --verbose)")
    p.add_argument("--cwd", help="override the working directory recorded in the transcript")
    p.set_defaults(fn=cmd_capture)
    p = sub.add_parser("live", help="run a new prompt headlessly, interrupt it, print the session id")
    p.add_argument("--cwd", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--until", required=True, help="regex on the screen that ends the run")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--settle", type=int, default=5, help="seconds to wait after --until matches")
    p.add_argument("--rows", type=int, default=60)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=cmd_live)
    p = sub.add_parser("render", help="render a captured row range to PNG")
    p.add_argument("dir", help="capture directory")
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", type=int)
    p.add_argument("--png", required=True)
    p.add_argument("--font", default=DEFAULT_FONT)
    p.add_argument("--size", type=float, default=15)
    p.add_argument("--scale", type=float, default=2)
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
