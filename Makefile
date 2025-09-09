.PHONY: dryrun
dryrun:
	uv run autoinvest.py --force-dry-run

.PHONY: test
test:
	uv run pytest -v
