# Repository rules

- Use Conventional Commits.
- Keep credentials, session history, caches, and machine-local state outside this repository.
- Preserve existing HOME configuration and user changes when installing links. Never overwrite a conflicting path without retaining its original contents.
- Run `python3 -m unittest discover -s tests`, `python3 common/skills-maintenance/check.py`, and `git diff --check` after changing platform scripts.
