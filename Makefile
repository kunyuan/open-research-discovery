.PHONY: check test pool-check

check: test
	uv run python scripts/validate.py

test:
	uv run pytest

POOL ?= ../open-research-problem-pool
pool-check:
	uv run python scripts/validate_pool_repository.py "$(POOL)"
