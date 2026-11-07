# Repository rules

- Use Conventional Commits.
- Keep credentials, session history, caches, and machine-local state outside this repository.
- Preserve existing HOME configuration and user changes when installing links. Never overwrite a conflicting path without retaining its original contents.
- Before moving or merging skill directories, read [structural migration preflight](common/skills-maintenance/README.md#structural-migration-preflight-read-only) and validate the complete plan before the first mutation.
- Run `python3 -m unittest discover -s tests`, `python3 common/skills-maintenance/check.py`, and `git diff --check` after changing platform scripts.
- Finish every skill edit, including one made through `~/.claude/skills` or `~/.pi/agent/skills`, with `make check`; refresh hashes only for the skill you changed (`check.py --scope <scope> --refresh-installed-hashes`, then diff the manifest). An unrefreshed hash fails the check for every later session.
