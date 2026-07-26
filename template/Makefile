.PHONY: check ci test verify

check:
	uv run python tools/check_problem.py

ci:
	uv run python tools/ci_verify.py

test:
	uv run python -m unittest discover -s verifier -p 'test_*.py'

verify:
	uv run python verifier/check.py submission
