# Background terminals

Vendored from [davis7dotsh/my-pi-setup](https://github.com/davis7dotsh/my-pi-setup/tree/5a0863f442402aa35cb0830805d67639957c7172/extensions/background-terminals),
commit `5a0863f442402aa35cb0830805d67639957c7172`. The upstream MIT license is
included in `LICENSE`. Runtime source and tests are unchanged.

Local integration changes:

- `tsconfig.json` is self-contained instead of inheriting the upstream root config.
  The upstream Effect compiler patch is omitted; checks use plain TypeScript.
- Development dependencies supply Pi 0.99.1, TypeBox, and Node declarations for
  standalone tests and type checking. Pi supplies its own modules at runtime;
  `effect` is the only direct runtime dependency.
- `make dep` installs the package, and `links.json` connects its files to the
  global Pi extension directory. Dependencies stay in ignored `node_modules/`.
- The companion skill is installed only in `~/.pi/agent/skills/background-terminals`.

## Use

The agent has `bg_start`, `bg_status`, `bg_list`, and `bg_kill`. `/ps` shows live
stdout/stderr and can stop processes. Commands have no stdin or PTY and run via
`/bin/sh -c` on POSIX, without the Pi-specific zsh setup. Processes belong to one
Pi session and stop on shutdown, reload, or session replacement. Private spill
logs are temporary and removed during session cleanup.

## Verify

```sh
npm --prefix pi/agent/extensions/background-terminals run check
npm --prefix pi/agent/extensions/background-terminals test
```

Run these commands from the repository root after `make dep`. The upstream
`docs/implementation-guide.md` is retained as historical design context, not as
installation instructions for this checkout.
