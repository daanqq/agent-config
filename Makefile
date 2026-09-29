.PHONY: check dep plan install

check:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
	PYTHONDONTWRITEBYTECODE=1 python3 common/skills-maintenance/check.py
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/install.py --backup-existing > /dev/null
	git diff --check

dep:
	node pi/agent/scripts/install-dependencies.mjs

plan:
	python3 scripts/install.py --backup-existing

install:
	python3 scripts/install.py --backup-existing --apply
