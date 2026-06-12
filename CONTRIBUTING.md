# Contributing

## Adding a new connector

A connector is a single class that implements the `TmsConnector` protocol
defined in `src/testops_mirror/connectors/base.py`.  You only need one method:

```python
from collections.abc import Iterator
from testops_mirror.models import TestCase

class MyTmsConnector:
    def iter_test_cases(self, project_id: str) -> Iterator[TestCase]:
        ...
```

### Checklist

1. **Create** `src/testops_mirror/connectors/my_tms.py`.
2. **Define API path constants** at the top of the module with a comment:
   ```python
   # Verify against <endpoint>/swagger-ui/ for your TMS version.
   _PATH_LIST = "/api/v1/testcases"
   ```
3. **Raise typed exceptions** from `testops_mirror.exceptions` — never let raw
   `httpx` errors escape the connector module.
4. **Write tests** in `tests/test_my_tms_connector.py` using
   `httpx.MockTransport`.  No real TMS instance should be required to run the
   test suite.  Cover: auth, pagination, field mapping, retry, graceful fallback.
5. **Add fixtures** under `tests/fixtures/` with realistic but anonymised
   API responses.
6. **Wire up the CLI** — add a `--connector` option or a dedicated subcommand
   in `cli.py` so users can select your connector.
7. **Update the README** — add a row to the supported TMS table.

### Graceful fallback pattern

If loading an individual test case fails, log a warning and continue — do not
abort the entire sync:

```python
for item in items:
    case_id = str(item["id"])
    try:
        ...
        yield self._map_case(detail, steps_raw, project_id)
    except AuthError:
        raise  # auth failures are always fatal
    except Exception as exc:
        logger.warning("Skipping test case %s due to error: %s", case_id, exc)
```

---

## Dev setup

```bash
git clone https://github.com/yourusername/testops-mirror
cd testops-mirror
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Quality gate (run before every commit)

```bash
ruff check .
ruff format --check .
mypy --strict src
pytest
```

### Pre-commit hooks (optional but recommended)

```bash
pip install pre-commit
pre-commit install
```

---

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(allure): add step fallback to /step endpoint
fix(serializer): handle empty suite_path tuple
docs: update README quick start
test(gitstore): add rename idempotency test
chore: bump httpx to 0.28
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

Scope is optional but recommended for connector-specific changes.

---

## Project layout

```
src/testops_mirror/
├── models.py          # canonical TMS-agnostic model — never import connector types here
├── exceptions.py      # all typed exceptions live here
├── serializer.py      # TestCase -> Markdown + YAML front matter
├── gitstore.py        # diff desired state + idempotent commits
├── sync.py            # orchestrator
├── cli.py             # typer CLI
└── connectors/
    ├── base.py        # TmsConnector protocol
    └── allure_testops.py
```

The data flow is strictly one-directional:

```
connector -> sync.py -> serializer -> gitstore
```

`serializer`, `gitstore`, and `sync` must remain TMS-agnostic.
All TMS-specific logic belongs inside the connector module.
