# Thunderbird Native Send Implementation Plan

> Execution: inline in this session, using executing-plans and TDD. Preserve all existing uncommitted query upgrades.

**Goal:** Add explicit automatic sending with durable deduplication and separate sent-copy evidence.

**Architecture:** Python MCP writes a private SQLite request journal. An allowlisted Thunderbird MailExtension connects through native messaging, claims each request once, sends through Thunderbird's account, and records the result. No SMTP credentials, network listener, or UI automation.

**Tech stack:** Python 3.11 stdlib, existing FastMCP v1, Thunderbird 153+ MailExtension (installed version 154), Node's built-in test runner.

**Spec:** User-approved design in this conversation: retain compose_email; add send_email/status; reuse account FCC; ambiguous sends must not be retried automatically. Existing FCC is local POP account Sent.

## Constraints

- Existing query/compose behavior stays intact.
- Sending requires an explicit user instruction to the calling agent; adding a tool is not general permission to send arbitrary mail.
- Native host only permits the fixed extension ID. Journal directory 0700, database 0600.
- A key is permanently bound to a normalized payload hash. Claimed requests never re-enter the queue.
- Queue expiry 60s; bridge heartbeat freshness 15s. Expired unsent requests cannot be delivered on restart.
- SendNow only. Never treat outbox queueing or a timeout as sent.
- Store Message-ID and copy folders separately. Missing/failed FCC does not cause another send.
- Test fixtures use example.com and temporary journals; no live test mail until explicitly authorized.

## Tasks

### 1. Durable Python journal and MCP facade
Files: mail_sender.py, server.py, tests/test_mail_sender.py, tests/test_server.py.
- [ ] Write/run failing tests for offline bridge, key conflict, concurrent claims, expiry, restart after claim, immutable sent outcomes, and returned copy status.
- [ ] Implement SQLite transaction state changes and input validation; no mailbox writes.
- [ ] Register send_email, get_send_status and get_send_capabilities, test these against a temporary journal.
- [ ] Run Python unittest suite.

### 2. Native messaging and MailExtension
Files: native_host.py, extension/manifest.json, extension/sender.js, extension/background.js, tests/test_native_host.py, tests/sender.test.cjs.
- [ ] Exercise native length-prefixed framing with BytesIO and subprocess pipes, including truncated/oversize requests and forbidden operations.
- [ ] Test extension sending using a fake Thunderbird API at the external boundary: explicit identity, exact body, sendNow, copy lookup, missing copy, ambiguous errors, and restart recovery.
- [ ] Implement persistent native connection polling and durable pending results. The extension cannot enqueue requests; it can only claim/report them.
- [ ] Run Python and Node tests.

### 3. Package, install and verify
Files: scripts/package_send.py, README.md, pyproject.toml, deployment report.
- [ ] Build XPI deterministically and validate its ZIP manifest and scripts.
- [ ] Compare deployed file hashes to the recorded baseline before applying changes; retain a rollback backup.
- [ ] Register the narrowly allowlisted native host; install/enable XPI through Thunderbird's supported add-on flow with required permission approval.
- [ ] Verify actual bridge heartbeat and MCP tool schemas. Live self-mail and Sent verification require a specific test-send authorization.
- [ ] Report accurately any outstanding activation or live verification steps.
