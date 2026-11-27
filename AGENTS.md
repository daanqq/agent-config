# Repository rules

- Use Conventional Commits.
- Keep credentials, session history, caches, and machine-local state outside this repository.
- Preserve existing HOME configuration and user changes when installing links. Never overwrite a conflicting path without retaining its original contents.
- The pre-commit hook runs full `make check` on the staged snapshot during `git commit`. Before committing, run only targeted checks for the changed step (the relevant `unittest` module, `python3 common/skills-maintenance/check.py --skill <scope>/<name>`, and `git diff --check`); run full `make check` manually for changes left uncommitted.
- For every skill edit, including one made through `~/.claude/skills` or `~/.pi/agent/skills`, refresh hashes only for the skill you changed (`check.py --skill <scope>/<name> --refresh-installed-hashes`, then diff the manifest) and verify with `check.py --skill <scope>/<name>` before committing (or full `make check` when left uncommitted). An unrefreshed hash fails the check for every later session.
