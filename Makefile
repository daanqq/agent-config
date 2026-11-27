.PHONY: check check-extensions-dev dep dep-dev plan install install-hooks bootstrap-plan bootstrap

check:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests --buffer
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s claude/skills/mr-echat/tests --buffer
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s common/skills/mr-review/tests --buffer
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s common/skills/babysit-mr/tests --buffer
	PYTHONDONTWRITEBYTECODE=1 python3 common/skills-maintenance/check.py
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/install.py --backup-existing > /dev/null
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/bootstrap.py --backup-existing > /dev/null
	git diff --check

check-extensions-dev:
	@for dir in pi/agent/extensions/firecrawl-search pi/agent/extensions/background-terminals; do \
		if [ ! -d "$$dir/node_modules" ]; then \
			echo "Missing $$dir/node_modules: run 'make dep-dev' first." >&2; \
			exit 1; \
		fi; \
	done
	npm --prefix pi/agent/extensions/firecrawl-search test
	npm --prefix pi/agent/extensions/background-terminals test

dep:
	node pi/agent/scripts/install-dependencies.mjs

dep-dev:
	node pi/agent/scripts/install-dependencies.mjs --dev

plan:
	python3 scripts/install.py --backup-existing

bootstrap-plan:
	python3 scripts/install.py --backup-existing
	python3 scripts/bootstrap.py --backup-existing

hooks := grep-literal-glob reply-language

install-hooks:
	@set -eu; \
		dir="$(HOME)/.local/libexec/agent-config"; \
		mkdir -p "$$dir"; \
		stage=$$(mktemp -d "$$dir/.install.XXXXXX"); \
		trap 'rm -rf "$$stage"' EXIT; \
		for name in $(hooks); do \
			CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off \
				go build -trimpath -o "$$stage/$$name" "claude/hooks/$$name.go"; \
		done; \
		for name in $(hooks); do \
			mv -f "$$stage/$$name" "$$dir/$$name"; \
		done

install: install-hooks
	python3 scripts/install.py --backup-existing --apply

bootstrap: install-hooks dep install
	python3 scripts/bootstrap.py --backup-existing --apply
