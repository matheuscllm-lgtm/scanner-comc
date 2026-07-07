# Root conftest: with pytest's default "prepend" import mode, the presence of
# this file makes pytest insert the repo root into sys.path, so tests can
# `import comc_summary` (root-level delivery tool) regardless of how pytest is
# invoked (`pytest tests/` vs `python -m pytest tests/`).
