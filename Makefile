.PHONY: dryrun
dryrun:
	uv run auto_invest.py --force-dry-run

.PHONY: test
test:
	uv run pytest -v
