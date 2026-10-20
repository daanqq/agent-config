.PHONY: check check-extensions dep plan install install-hooks

check:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests --buffer
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s claude/skills/mr-echat/tests --buffer
	PYTHONDONTWRITEBYTECODE=1 python3 common/skills-maintenance/check.py
	PYTHONDONTWRITEBYTECODE=1 python3 scripts/install.py --backup-existing > /dev/null
	$(MAKE) check-extensions
	git diff --check

check-extensions:
	node --test --experimental-strip-types pi/agent/extensions/tests/00-ui-transition.test.ts pi/agent/extensions/tests/herdr-pi-session-name.test.ts

dep:
	node pi/agent/scripts/install-dependencies.mjs

plan:
	python3 scripts/install.py --backup-existing

install-hooks:
	@set -eu; \
		dir="$(HOME)/.local/libexec/agent-config"; \
		mkdir -p "$$dir"; \
		temporary=$$(mktemp "$$dir/.grep-literal-glob.XXXXXX"); \
		trap 'rm -f "$$temporary"' EXIT; \
		CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off \
			go build -trimpath -o "$$temporary" claude/hooks/grep-literal-glob.go; \
		mv -f "$$temporary" "$$dir/grep-literal-glob"

install: install-hooks
	python3 scripts/install.py --backup-existing --apply
