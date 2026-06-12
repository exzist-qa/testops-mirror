# testops-mirror

> Mirror test cases from any TMS into a Git repository — one file per test case, history forever.

```
mirror/
├── Shipments/
│   ├── Negative/
│   │   └── TC-1042-ship-without-cargo.md
│   └── TC-1001-basic-shipment.md
└── Auth/
    └── TC-2001-login-valid-credentials.md
```

## Why

Your TMS is a single point of failure. Test cases deserve version control just like code —
history, diff, blame, and code review through merge requests.

testops-mirror pulls every test case on a schedule and commits changes to a plain Git repo.
No vendor lock-in, no proprietary format.

## Quick Start

**pip:**

```bash
pip install testops-mirror
cp .env.example .env  # fill in TESTOPS_ENDPOINT and TESTOPS_TOKEN
testops-mirror sync --project-id 42 --repo ./mirror
```

**Docker:**

```bash
docker run --rm \
  -e TESTOPS_ENDPOINT=https://testops.example.com \
  -e TESTOPS_TOKEN=your-token \
  -v $(pwd)/mirror:/mirror \
  ghcr.io/yourusername/testops-mirror \
  sync --project-id 42 --repo /mirror
```

## Example output file

```markdown
---
id: '1042'
name: Ship without cargo
status: Ready
automated: false
tags: [api, negative]
links:
  - {name: BUG-42, url: 'https://tracker.local/BUG-42', type: issue}
source: {url: 'https://testops.example.com/project/42/test-cases/1042', project: '42'}
---

# Ship without cargo

## Preconditions

The ship must have an active voyage.

## Steps

1. Send `POST /ship`
    - **Expected:** `409 Conflict`
2. Check response body
    1. Field `error` is present

## Expected result

API returns 409 with a descriptive error message.
```

## Supported TMS

| TMS | Status |
|-----|--------|
| Allure TestOps | ✅ |
| TestIT | 🚧 planned |
| TestRail | 🤝 contributions welcome |

## Configuration

| Option | Env | Default | Description |
|--------|-----|---------|-------------|
| `--project-id` | — | required | TMS project ID |
| `--endpoint` | `TESTOPS_ENDPOINT` | required | Base URL of TMS |
| `--token` | `TESTOPS_TOKEN` | required | API token |
| `--repo` | — | `./mirror` | Local Git repo path |
| `--suite-field` | `TESTOPS_SUITE_FIELD` | `Suite` | Custom field for folder structure |
| `--dry-run` | — | false | Preview changes without writing |
| `-v/--verbose` | — | false | Verbose logging |

> **Note:** API endpoint paths are verified against Allure TestOps documented API.
> If your instance uses different paths, check `<endpoint>/swagger-ui/` and
> update the constants in `connectors/allure_testops.py`.

## Roadmap

- Attachments download
- TestIT connector
- Index file (`cases/INDEX.md`) with a table of all cases
- Reverse import (Markdown → TMS)

## License

MIT
