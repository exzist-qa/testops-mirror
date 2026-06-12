---
id: '2301'
name: Transfer to blocked account
status: Ready
automated: false
tags:
- api
- negative
links:
- name: BAN-17
  url: https://jira.example.com/browse/BAN-17
  type: issue
source:
  url: https://testops.example.com/project/42/test-cases/2301
  project: '42'
---

# Transfer to blocked account

Verify that a fund transfer is rejected when the recipient account is blocked.

## Preconditions

Sender account has sufficient balance. Recipient account status is BLOCKED.

## Steps

1. Send POST /transfers with blocked recipient account ID
    - **Expected:** HTTP 422 Unprocessable Entity
2. Verify response body
    1. Field 'errorCode' equals 'ACCOUNT_BLOCKED'
    2. Field 'message' is non-empty string

## Expected result

API returns 422 with error code ACCOUNT_BLOCKED.
