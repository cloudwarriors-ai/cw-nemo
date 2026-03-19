.PHONY: check lint format lint-ts lint-py lint-contracts format-ts format-py docs docs-live docs-clean

check: lint-ts lint-py lint-contracts
	@echo "All checks passed."

lint: lint-ts lint-py lint-contracts

lint-ts:
	cd nemoclaw && npm run check

lint-py:
	cd nemoclaw-blueprint && $(MAKE) check

lint-contracts:
	cd artifact-loop && npx tsc --noEmit

format: format-ts format-py

format-ts:
	cd nemoclaw && npm run lint:fix && npm run format

format-py:
	cd nemoclaw-blueprint && $(MAKE) format

# --- Documentation ---

docs:
	uv run --group docs sphinx-build -b html docs docs/_build/html

docs-live:
	uv run --group docs sphinx-autobuild docs docs/_build/html --open-browser

docs-clean:
	rm -rf docs/_build
