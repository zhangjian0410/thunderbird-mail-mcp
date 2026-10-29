# Changelog

**English** | [简体中文](CHANGELOG.zh-CN.md) · [Project overview](README.md)

Public source history starts with [0.5.0](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/272e1702e30f900a2761457e7b869fbd02cad5f8), then advances to 0.11.0 and 0.12.0. Earlier milestones are preserved from the imported project notes. The 0.6.0, 0.8.0, 0.9.0, and 0.10.0 entries were published together with the 0.11.0 source, not as separate public version commits. No separate release dates or tags are implied.

## Documentation maintenance (0.12.0 unchanged)

- Made English the primary README and retained a complete Chinese companion with language navigation. See [the README update](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/d5aa5329d1185d5ac4dc6ae8ad2fc5c6fa7ee6a1).
- Added English tool and development guides with complete Chinese companions. Clarified heartbeat readiness, status cleanup, diagnostic tab closure, native `.eml` verification limits, and deployment/test scope against the implementation. See [the guide update](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/36696370d6fa95c43d68a103a108e53f5f46813e).
- Added checks that both tool catalogs match registered signatures, defaults, and minimum profiles. Extended the deployment file list and navigation check to include bilingual documentation and the generic MCP configuration example.
- Added this English changelog and its Chinese companion, synchronized navigation and deployment coverage, and distinguished inherited milestones from public source revisions. The server and extension remain at 0.12.0.

## 0.12.0 · Server capability profiles

Source: [capability-profile commit](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/ce6c045f2660d9faae5fe3d53d57d760126ff715).

- Added strict `THUNDERBIRD_MCP_PROFILE=read_only|review|direct_send` profiles. Omission defaults to `review`; empty, case-variant, and unknown values prevent startup. The server no longer exposes every tool by default.
- `read_only` exposes 10 query, read, and status tools. `review` adds a compose window, draft saving, and prepare-only diagnostics for 13 tools. Only `direct_send` also exposes `send_email`, `reply_email`, and `forward_email`, for 16 tools.
- `get_send_capabilities` reports `mcp_profile`, `review_enabled`, and `direct_send_enabled` so clients can inspect the running server.
- The generic stdio example and protocol tests default to `review`. Direct-send protocol tests explicitly select `direct_send`; tests also verify that the default server rejects calls to hidden send tools.

## 0.11.0 · Native `.eml` metadata verification

Public source import: [native reply and forward workflows](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/a98b22434ef39fe8988105a9f8d26301aba04306). This commit includes the earlier reply/forward milestones below.

- Changed the send path to handle native `.eml` attachments that cannot be read through `compose.getAttachmentFile`. It retains the attachment produced by `forwardAsAttachment`, without removing it, reattaching a raw File, or claiming native-attachment byte equality.
- Preparation and send-event checks verify the source raw fingerprint, native context, and the sole `.eml` attachment's extension, metadata size, and accepted MIME classification. Caller-supplied attachments still receive byte-level SHA-256 checks.
- The native attachment ID is part of the internal manifest: remove-and-replace is rejected even when metadata matches. Caller attachments use actual IDs rather than assumed consecutive IDs.
- Public API metadata checks cannot establish native `.eml` byte equality; final packaging retains trust in Thunderbird's native implementation.
- Prepare-only diagnostics advertise a separate `forward_diagnostic_v1` feature. An older extension supporting only `forward_v1` cannot accept these diagnostic requests.
- Diagnostic attachment classifications are capped at 16 entries, with bounds on counts, shape, sizes, and total JSON size. `count` / `truncated` report omitted classifications.

## 0.10.0 · Prepare-only forward diagnostics

- Added `diagnose_forward_preparation`, `get_forward_diagnostic_status`, and a separate diagnostic queue. The path looks up the source, calls getRaw and native forwardAsAttachment, removes inherited attachments, reattaches the raw source, and reads it back. It calls neither sendMessage nor draft saving and attempts to close the exact compose tab.
- Results contain bounded failure stages, sizes, SHA-256 values, equality flags, attachment counts, extensions, and MIME classifications. They exclude bodies, addresses, subjects, paths, and raw bytes; the queue still stores the request context. Diagnostics remain separate from send recovery.
- Tab closure is reported through `close_confirmed`. A failed close returns `close_not_confirmed` and keeps the tab's send-blocking guard; successful closure is not guaranteed.

## 0.9.0 · Raw-message attachment compatibility

- The inherited milestone notes describe retaining the native `forwardAsAttachment` context while replacing all inherited attachments with the original File from `messages.getRaw(..., {data_format: "File"})`, then checking size and SHA-256 before sending. The 0.11.0 send path supersedes this replacement strategy.
- Added bounded `failure_code` values for source lookup, raw reads, native compose, context, body, native attachments, raw mismatch, caller attachments, and the final guard. These codes do not expose message bodies, attachment names, or local paths.
- Existing failed/unknown requests and idempotency-key semantics remain unchanged; upgrading does not requeue or resend them.

## 0.8.0 · Native attachment forwarding

- Added `forward_email` / `forward_v1`, binding an RFC Message-ID, source account, and explicit identity to `compose.beginForward(..., "forwardAsAttachment")`. No new-message fallback or inline forwarding.
- The inherited design used `messages.getRaw(..., {data_format: "File"})` as an independent source for checking the original attachment, exact commentary, and caller attachments during preparation and before sending. Native-attachment handling was revised in 0.9.0 and 0.11.0; current guarantees are described under 0.11.0.
- Checks before sending and during `onBeforeSend` cover the source, native context, identity, recipients, subject, final body, and attachments. Unknown outcomes are not resent. Offline checks do not establish deployment or real-account delivery.

## 0.6.0 · Native reply and reply-all

- Added `reply_email` / `reply_v1`, binding an RFC Message-ID, source account, and explicit sender identity to native `beginReply`. Supports `reply_all` / `reply_sender` without falling back to a new message.
- Reads back native reply context, authorized recipients, sender fields, body, and attachments. Source changes are checked before sending and during the send event; durable idempotency and unknown-outcome handling are retained.
- Capabilities include account IDs and each identity's account. Existing tools and request digests remain compatible. Replies require an extension advertising `reply_v1` and a refreshed MCP connection; local validation does not establish deployment or real sending.

## Engineering maintenance (after 0.5.0, version unchanged)

These changes landed [between the initial 0.5.0 source and the reply/forward import](https://github.com/zhangjian0410/thunderbird-mail-mcp/compare/272e1702e30f900a2761457e7b869fbd02cad5f8...ad7d70f6390effc13bba3a8ee60e50ac030707c9); the server and extension version stayed at 0.5.0.

- Published read-only Sent queries: Inbox remains the default, while saved sent copies or a combined scope require explicit selection. Added portable Sent path configuration without connecting pending Outbox; the tool count remained 12.
- Reorganized the README around the project, installation, and generic stdio setup, moving tool/deployment and development details into `docs/`. Clarified that sending and draft saving are independent actions.
- Added a generic client configuration and real MCP stdio regression tests, distinguishing protocol coverage from GUI compatibility and end-to-end testing.
- Added `uv.lock`, locked build tooling, Linux/macOS CI, current/history sensitive-data scans, and synthetic negative cases.
- Fixed deployment-generated native launchers for paths containing spaces and validated the host manifest against the deployment target. Ignored generated configuration, XPI files, and deployment backups.
- Attachment retries use stored digests without reopening source files. Legacy query tools skip invalid dates and emit warnings without message bodies.
- Added the MIT license.

## 0.5.0 · HTML bodies

Added `body_format="plain"|"html"` to `send_email` and `create_draft`. The plain default and existing idempotency digests remain compatible. HTML uses actual markup and a Thunderbird-generated plain-text alternative, requiring `html_v1`; extension permissions are unchanged from 0.4.0. Native draft preview is recommended, not a send prerequisite. Reconnect the MCP client after an upgrade.

## 0.4.0 · Attachments and native drafts

Added verified attachment snapshots: at most 10 files and 20 MiB combined. Native draft saving requires `draft_v1`; attachments require `attachments_v1`. The extension added `compose.save`. Saving a draft does not authorize sending; older extensions do not claim requests with unsupported features.

## 0.3 · Thunderbird extension sending

Added sending through a native host and Thunderbird extension, durable idempotency keys, status queries, and sent-copy verification. Thunderbird handles account authentication and Sent filing; the server does not implement direct mail-server connections.

## 0.2 · Paginated read-only tools

Added local folder listing, exact sender/time-range queries, cursors/locators, batch reads, chunked attachment reads, and explicit coverage reporting, while retaining legacy query compatibility.

## Initial functionality

Local mbox search, single-message reads, recent-message listing, and opening a Thunderbird compose window.

For current usage and limits, see the [project overview](README.md) and [tool reference](docs/reference.md).
