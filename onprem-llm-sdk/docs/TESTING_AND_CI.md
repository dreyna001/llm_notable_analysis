# Testing and CI

This guide covers:

- local test execution
- CI/CD wiring
- current test coverage and known gaps

## Local test commands

Run from `onprem-llm-sdk/`.

### Option A: unittest (current default)

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test*.py" -v
```

Windows PowerShell:

```powershell
$env:PYTHONPATH='src'; python -m unittest discover -s tests -p "test*.py" -v
```

### Option B: pytest

```bash
PYTHONPATH=src pytest -q
```

## What tests exist

- `tests/test_config.py`
  - config defaults, env overrides, explicit override precedence, invalid config handling
- `tests/test_client.py`
  - success path, retry-on-500, no-retry on 400, timeout exhaustion
- `tests/test_contract_compat.py`
  - response shape parsing and Retry-After parsing
- `tests/test_semaphore_limits.py`
  - inflight semaphore bound enforcement
- `tests/conftest.py`
  - fake session/response helpers for deterministic unit tests

## CI/CD wiring (GitHub Actions example)

Create `.github/workflows/sdk-tests.yml`:

```yaml
name: sdk-tests

on:
  push:
    paths:
      - "onprem-llm-sdk/**"
  pull_request:
    paths:
      - "onprem-llm-sdk/**"

jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: onprem-llm-sdk
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dev dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"
      - name: Lint
        run: ruff check .
      - name: Unit tests
        run: PYTHONPATH=src python -m unittest discover -s tests -p "test*.py" -v
```

## Recommended pipeline stages

1. lint (`ruff`)
2. unit tests (`unittest` or `pytest`)
3. package build (`python -m build`)
4. optional: offline bundle creation (`scripts/build_offline_bundle.sh`)

