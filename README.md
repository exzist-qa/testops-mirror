# testops-mirror

> Mirror test cases from any TMS into a Git repository — one file per test case, history forever.

```
mirror/
├── Transfers/
│   ├── Negative/
│   │   └── TC-2301-transfer-to-blocked-account.md
│   └── TC-2201-transfer-between-own-accounts.md
└── Auth/
    └── TC-1001-login-with-valid-credentials.md
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
  ghcr.io/exzist-qa/testops-mirror \
  sync --project-id 42 --repo /mirror
```

## Example output file

```markdown
---
id: '2301'
name: Transfer to blocked account
status: Ready
automated: false
tags: [api, negative]
links:
  - {name: BAN-17, url: 'https://jira.example.com/browse/BAN-17', type: issue}
source: {url: 'https://testops.example.com/project/42/test-cases/2301', project: '42'}
---

# Transfer to blocked account

## Preconditions

Sender account has sufficient balance. Recipient account status is BLOCKED.

## Steps

1. Send `POST /transfers`
    - **Expected:** `422 Unprocessable Entity`
2. Check response body
    1. Field `code` equals `ACCOUNT_BLOCKED`

## Expected result

API returns 422 with error code ACCOUNT_BLOCKED.
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
