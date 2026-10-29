# Tool and behavior reference

**English** | [简体中文](reference.zh-CN.md) · [Project overview](../README.md)

## 16 MCP tools (complete catalog)

| Tool | Minimum profile | Purpose and parameters |
|---|---|---|
| `list_mail_folders()` | `read_only` | List configured local Inbox/Sent mbox files and their availability. Pending Outbox is not connected. |
| `query_email(keyword="", senders=None, start=None, end=None, folders=None, page_size=50, cursor=None)` | `read_only` | Paginate matching mail. Omitted `folders` means Inbox only; select Sent or Inbox+Sent explicitly. An empty keyword allows enumeration. Sender addresses match exactly. Dates use timezone-aware ISO timestamps with `start ≤ date < end`. Page size: 1–200. |
| `read_emails(locators, include_quoted_history=False, max_body_chars=30000)` | `read_only` | Read 1–20 locators. Returns per-message results, current body, optional quoted history, truncation flags, and attachment IDs/hashes. Body limit: 1000–100000 characters. |
| `read_attachment(locator, attachment_id, offset=0, max_bytes=262144)` | `read_only` | Return a base64 chunk, full-attachment SHA-256, total length, and `next_offset`. Maximum chunk: 1 MiB. |
| `search_email(keyword, days=None, sender=None)` | `read_only` | Legacy Inbox search: required keyword, sender substring matching, no pagination. Prefer `query_email` for new integrations. |
| `read_email(message_id)` | `read_only` | Legacy Inbox message read by Message-ID, with body and attachment metadata. Quoted history is omitted by default. |
| `list_recent_email(limit=20)` | `read_only` | Legacy Inbox list, newest first. Limit: 1–100. |
| `compose_email(to, subject, body, cc=None, bcc=None)` | `review` | Open a native Thunderbird compose window without sending. |
| `create_draft(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format="plain")` | `review` | Save a native draft through the extension; never send. Poll for `drafted` or a terminal failure/unknown outcome. |
| `send_email(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format="plain")` | `direct_send` | Send an authorized message through the extension. After acceptance, poll its status. |
| `reply_email(to, subject, body, from_email, idempotency_key, source_message_id, source_account_id, identity_id, reply_mode="reply_all", cc=None, bcc=None, attachments=None, body_format="plain")` | `direct_send` | Send in a native reply context. Supports `reply_all` / `reply_sender`; explicit recipients must match Thunderbird's native recipient fields. Requires `reply_v1`. |
| `forward_email(to, subject, body, from_email, idempotency_key, source_message_id, source_account_id, identity_id, forward_mode="forward_attachment", cc=None, bcc=None, attachments=None, body_format="plain")` | `direct_send` | Send in a native attachment-forward context. The authorized commentary is the exact body; Thunderbird preserves the source as a native `.eml`. Requires `forward_v1`. |
| `diagnose_forward_preparation(source_message_id, source_account_id, from_email, identity_id, diagnostic_key, body_format="plain")` | `review` | Prepare and inspect a native forward without sending or saving. Attempts to close its exact compose tab. Results contain bounded sizes, hashes, and classifications; at most 16 attachment classifications, with `count` / `truncated` for the full count. Requires `forward_diagnostic_v1`. |
| `get_forward_diagnostic_status(diagnostic_key)` | `read_only` | Read the separate diagnostic queue, without reading or changing send requests. |
| `get_send_status(idempotency_key)` | `read_only` | Read durable request status, Message-ID, and sent-copy verification; also expire unclaimed requests. |
| `get_send_capabilities()` | `read_only` | Read extension heartbeat, sender identities, features, and the active server profile. Does not send mail. |

For draft and direct-send tools, `to`, `cc`, and `bcc` are arrays of bare email addresses. `from_email` must match exactly one available identity. In `compose_email`, recipient fields are strings. MCP `tools/list` returns the full input schemas.

## Capability profiles

Set `THUNDERBIRD_MCP_PROFILE` in the MCP client's `env`. Values must match exactly. Omission defaults to `review`; empty values, case variants, and unknown values prevent startup.

| Profile | Tools | Exposed capabilities |
|---|---:|---|
| `read_only` | 10 | Mail queries, body/attachment reads, and send/diagnostic status checks. No compose windows, drafts, preparation diagnostics, or direct sending. |
| `review` (default) | 13 | Adds `compose_email`, `create_draft`, and `diagnose_forward_preparation` to `read_only`. No direct-send tools. |
| `direct_send` | 16 | All tools, including `send_email`, `reply_email`, and `forward_email`. |

The profile is fixed when the server process starts. Restart or reconnect the MCP server and refresh the tool list after changing it. Editing a JSON file does not change an existing connection. `get_send_capabilities()` reports `mcp_profile`, `review_enabled`, and `direct_send_enabled`. Profiles control MCP tool registration; they do not replace message authorization, idempotency checks, or extension feature checks.

`ready=true` means the last extension heartbeat is no more than 15 seconds old; it does not mean direct sending is enabled or a message is authorized. Status/capability tools may initialize the local journal, and `get_send_status` cleans up expired pending requests. Thus `read_only` restricts mail actions, not all filesystem writes. Switching to a lower profile does not cancel requests already queued by another connection or an earlier process.

## Inbox and Sent queries

`THUNDERBIRD_INBOX_PATH` points to the Inbox mbox. Optional `THUNDERBIRD_SENT_PATH` selects the Sent mbox; otherwise it uses `Sent` beside Inbox. These are explicit paths and a derived default: the server does not discover accounts, read account passwords, or verify sent-copy (FCC) settings. Thunderbird determines where sent copies are actually saved.

`query_email()` defaults to Inbox even if Sent is unavailable. Use `folders=["Sent"]` for saved sent copies or `folders=["Inbox", "Sent"]` for both. Each result retains its `folder`; pass its locator to `read_emails` or `read_attachment`. Legacy `search_email`, `read_email`, and `list_recent_email` remain Inbox-only.

Sent queries only read local mbox data. They do not invoke `send_email`, move mail, or mark it read. Sent holds saved copies, not pending Outbox messages. Outbox, an empty folder selection, duplicate folders, and unknown folder names are rejected. `server_sync_status` remains `unknown`; a saved copy does not prove recipient delivery.

## Writing, reply, forward, and diagnostic execution

| Tool | Server and Thunderbird path | Outcome |
|---|---|---|
| `compose_email` | `MailComposer` → Thunderbird CLI `-compose` | Open a compose window; no automatic save or send. |
| `create_draft` | Queue with `action="draft"` → extension `compose.saveMessage(..., {mode: "draft"})` | Save only; status becomes `drafted`. |
| `send_email` | Queue with default `action="send"` → extension `compose.sendMessage(..., {mode: "sendNow"})` | Send directly; status becomes `sent` on confirmed submission. No preceding draft save. |
| `reply_email` | Immutable `reply` context → unique account-scoped RFC Message-ID lookup → `compose.beginReply(..., "replyToAll" / "replyToSender")` → `sendMessage(..., {mode: "sendNow"})` | Send a native reply; fail on source, identity, or recipient mismatch. Never fall back to a new message. |
| `forward_email` | Immutable `forward` context → unique account-scoped RFC Message-ID lookup → snapshot source raw bytes → `compose.beginForward(..., "forwardAsAttachment")` → set exact commentary → `sendMessage(..., {mode: "sendNow"})` | Send a native attachment forward, retaining Thunderbird's `.eml`. Check source and final content; never fall back to a new message. Native attachment verification is limited to the metadata checks below. |
| `diagnose_forward_preparation` | Separate queue → read source raw bytes → native `forwardAsAttachment` → temporarily replace and reread the `.eml` → attempt to close the exact tab | Inspect preparation only. No send or draft-save call; results remain separate from send requests. |

`create_draft` and `send_email` are independent actions, not a mandatory sequence. Direct sending requires neither a draft ID nor a manual Send click. New requests are rejected when the extension is offline, the sender identity does not match, or required features are missing. Thunderbird may still fail or return an uncertain outcome during execution.

The server validates inputs, extension availability, identities, features, attachment integrity, and idempotency keys. It does not validate human approval records or confirmation tokens. The caller obtains user authorization and applies its client permission policy; authorization wording in a tool description is not a server-side approval mechanism.

A diagnostic result includes `close_confirmed`. If tab closure fails, it returns `status="failed"` and `failure_stage="close_not_confirmed"`; the extension retains the send-blocking guard for that tab. Do not assume every diagnostic successfully closes its window.

## Native reply boundaries

`source_message_id` is the original RFC Message-ID, optionally surrounded by one pair of angle brackets. It is not a query locator or Thunderbird's temporary numeric message ID. Read the source and confirm user authorization, then select the source account from `get_send_capabilities().accounts[{id,type,name}]` using its actual name/type. Select the `id` from `identities[{id,email,account_id}]` that uniquely matches `from_email`. A source in Local Folders may belong to a different account from the sending identity. Resolve an ambiguous account before calling.

The extension queries Message-ID locally within the specified account, follows every result page, and requires exactly one non-external message. Missing/duplicate sources, changed accounts or identities, or failed source reads prevent sending. After native `beginReply`, it checks `type="reply"` and `relatedMessageId`. It compares Thunderbird's computed To/Cc/Bcc against the explicitly authorized fields, ignoring address case and order within each field. A mismatch closes the prepared tab when possible and fails. The tool does not support adding, removing, or moving reply recipients between fields; any native Bcc recipients must also be explicitly authorized.

The body replaces automatic quotes and the signature; provide the complete authorized text and signature. The extension removes inherited attachments, disables automatic vCard/public-key attachments, and adds only the verified snapshots supplied by the caller. It checks From, identity, subject, body, attachment metadata, and byte hashes before sending. It rechecks the source MIME content/location, identity, and recipients after preparation and during `onBeforeSend`, cancelling on change. These guards do not isolate malicious programs running as the same OS user or other extensions, and do not implement multi-party approval.

The source, mode, identity ID, sender, To/Cc/Bcc, subject, body, and attachment digests are bound to one idempotency key. `reply_email` shares the durable journal, claim mechanism, and `unknown` recovery rules. Never resend an uncertain outcome with a new key. There is no reply-draft tool; `create_draft` creates a separate new-message draft.

API context and limits: Thunderbird's [compose API](https://webextension-api.thunderbird.net/en/esr-mv2/compose.html#beginreply-messageid-replytype-details) provides `beginReply`, the reply modes, and read-only reply type/related-message fields. The [messages API](https://webextension-api.thunderbird.net/en/esr-mv2/messages.html#query-queryinfo) supports account-scoped RFC Message-ID queries; numeric IDs can change after restarts or moves. Thunderbird generates native reply headers; this project does not imitate them with a `Re:` subject or fabricated headers. HTML is normalized by the native editor, and a mismatch between canonicalized input and read-back DOM content fails closed. Mock tests establish request and state boundaries, not real-account delivery or final MIME reply headers.

In Mozilla's source, [nsMsgCompose.cpp](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/compose/src/nsMsgCompose.cpp) passes the original References chain and Message-ID into reply fields; [MimeMessage.sys.mjs](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/compose/src/MimeMessage.sys.mjs) builds References and In-Reply-To. These references explain the native mechanism and do not replace testing on the target Thunderbird version. `beginReply` creates a compose window; the tool does not rely on UI automation or promise windowless operation.

## Native forward boundaries

`forward_email` uses the same RFC Message-ID, source-account, and sender-identity selection rules as replies, but supports only `forward_attachment`. The extension snapshots the source fingerprint with `messages.getRaw(messageId, {data_format: "File"})`, then calls `compose.beginForward(messageId, "forwardAsAttachment", details)`. The send path retains Thunderbird's native `.eml`: it neither removes/re-attaches it nor reads its bytes through `compose.getAttachmentFile`. Preparation and final checks require a stable source fingerprint and exactly one native attachment with an unchanged attachment ID, a `.eml` extension, metadata size equal to the source raw size, and an accepted MIME classification. Caller-added attachments are checked byte-for-byte using actual attachment IDs, without assuming consecutive IDs.

Before sending and during `onBeforeSend`, the extension rechecks the original, source fingerprint, native forward context, identity, recipients, subject, exact body, and attachment manifest. Changes to the source, native attachment metadata, or caller-added attachment bytes cancel sending. The public compose API cannot reliably expose native `.eml` bytes; metadata checks therefore cannot prove byte equality. Final native `.eml` packaging retains limited trust in Thunderbird's `forwardAsAttachment` implementation. There is no forward-draft tool or inline-forward mode.

API references: [compose.beginForward](https://webextension-api.thunderbird.net/en/esr-mv2/compose.html#beginforward-messageid-forwardtype-details) defines native attachment forwarding; [messages.getRaw](https://webextension-api.thunderbird.net/en/esr-mv2/messages.html#getraw-message-options) supports reading raw mail as a `File`. Offline mocks verify boundaries and guards, not actual `.eml` naming, final MIME, or delivery on a target Thunderbird version. Deployment and real-mail testing require their own authorization.

## Query completeness and attachments

Recommended sequence: `list_mail_folders` → `query_email` → follow `next_cursor` to null with unchanged query parameters → `read_emails` → read attachment chunks by attachment ID.

`coverage.local_status=complete` only establishes enumeration of matching records in the selected local mbox files. Unread bodies or attachments have not been processed. Unindexable headers, including invalid dates/senders, appear in `coverage.gaps`, leaving coverage partial. `server_sync_status` is always `unknown`; file timestamps cannot establish completed POP synchronization.

The index caches headers and positions only. Changes to mbox device/inode/size/mtime/ctime invalidate it. Cursors bind the query and snapshot; obtain new locators/cursors after a server restart or mailbox change. RFC Message-IDs may be empty or duplicated and cannot replace locators. Legacy queries skip invalid dates and emit warnings to stderr without message bodies.

Body reads prefer plain text; HTML is converted to text. Quoted-history separation is heuristic: inspect with `include_quoted_history=true` when needed, checking body/history truncation separately. The locator-based `read_emails` / `read_attachment` path limits individual messages to 64 MiB; this limit is not implemented by legacy `read_email`. Reading attachments does not execute files, mark messages read, or connect to a mail server. Reassemble chunks and verify size and SHA-256. Attached messages use `serialized_message_rfc822` (reserialized mail); multipart MIME attachments use `serialized_mime_part`; ordinary attachments use `decoded_payload`.

## Drafts, HTML, and send status

`body_format` accepts `plain` (default) or `html`. Supply actual HTML; Markdown is not converted. The extension uses HTML compose mode and `deliveryFormat: "both"`, letting Thunderbird generate the plain-text alternative. The interface cannot accept two independently authored bodies and does not sanitize arbitrary HTML. Prefer simple tables and inline styles; avoid scripts, forms, remote resources, and tracking images. Previewing a native draft is recommended, not a technical prerequisite for `send_email`.

If sending after a preview, obtain authorization and call `send_email` with a new idempotency key and the final body/attachments. This creates a separate request; it does not read, send, or delete the prior draft. No tool sends an existing draft by ID.

Attachments use `[{"path":"/absolute/file.xlsx","sha256":"<64-hex-digit-SHA-256>"}]`: up to 10 files and 20 MiB combined, using absolute paths to regular files. On first enqueue, the server checks the expected hash of the reviewed bytes and stores an immutable snapshot. The extension verifies sizes/hashes again; bridge chunks are at most 256 KiB.

Use a distinct `idempotency_key` for each logical send or draft, and reuse it after timeouts or when retrying that request. Same-key retries use stored attachment digests without reopening changed/deleted source files. Body, action, attachment filenames/order/expected hashes must still match. A key cannot change from plain to HTML. Status-only queries do not require body or attachments again.

| Status | Meaning |
|---|---|
| `pending` | Waiting for the extension to claim it; neither sent nor saved. |
| `sending` | Claimed; an interruption must not automatically requeue it. |
| `sent` | Thunderbird confirmed submission to the outgoing server; not a delivery guarantee. |
| `drafted` | Thunderbird saved the draft; not authorization to send. |
| `failed` / `expired` | Failed, or remained unclaimed for more than 60 seconds. |
| `unknown` | Outcome cannot be confirmed; investigate without sending again under a new key. A claimed request without a recorded outcome is reported as unknown after 300 seconds. |
| `not_found` | No request exists for the supplied key. |

`copy_status=verified` means the extension read a sent copy with the same Message-ID. `not_verified` is not a reason to resend. Sent/Drafts destinations follow account settings; delivery and local copy-save failures are reported separately.

The queue lives at `~/Library/Application Support/ThunderbirdMailMCP/send.sqlite3`, with directory mode 0700 and database mode 0600. Recording a completion, or cleaning up an expired unclaimed request, clears its payload and releases attachment BLOBs. Interrupted claimed requests without a recorded outcome retain forensic data. SQLite deletion does not guarantee secure erasure; do not delete the database to retry an uncertain send.

## Optional writing deployment (macOS)

Queries need no extension. For native drafts or sending, first install dependencies in the chosen directory as described in the [README](../README.md#1-install-the-server), ensure Thunderbird 153+, then run:

```bash
chmod 700 native-send-launcher
.venv/bin/python scripts/package_send.py --output dist --install-root "$PWD"
mkdir -p "$HOME/Library/Mozilla/NativeMessagingHosts"
install -m 600 dist/native-host.json "$HOME/Library/Mozilla/NativeMessagingHosts/com.thunderbird_mail_mcp.native_send.json"
```

These commands register the native host locally. Run them only in the intended installation directory. Packaging does not enable the extension. In Thunderbird's Add-ons and Themes manager, choose Install Add-on From File, select `dist/thunderbird-native-send.xpi`, review its permissions, and enable it.

Extension permissions are accountsRead, messagesRead, compose, compose.send, compose.save, nativeMessaging, and storage. The native-host allowlist contains only `native-send@thunderbird-mail-mcp.local`. Other programs running as the same OS user remain within the trust boundary.

`native-send-launcher` uses `.venv/bin/python` beside itself and supports installation paths containing spaces. For `scripts/deploy_send.py`, `--target` must match the package's `--install-root`. Both `--check` and actual deployment validate host path, name, stdio type, and the single allowed extension ID. Consult `--help` for arguments. This script updates a fixed file list in an existing installation with a Python runtime; it is not a complete clone/dependency installer.

Reconnect your MCP client to refresh its tools and parameters; source updates do not reload running processes. Use the matching 0.12.0 extension for this source version. Runtime compatibility is checked through advertised features, not an exact version-string gate; new source cannot give an old extension missing features. Direct sending requires `THUNDERBIRD_MCP_PROFILE=direct_send`. Check `get_send_capabilities().ready`, required `attachments_v1`, `draft_v1`, `html_v1`, `reply_v1`, `forward_v1`, `forward_diagnostic_v1` features, and actual account/identity data. Replies and forwards require sending authorization. Do not use real sending as a routine installation check.

Disable the extension in Thunderbird to stop it from taking new work. Unclaimed requests expire, but disabling cannot retract a claimed or submitted message. Queries and `compose_email` do not require the extension. Multiple MCP clients running as the same OS user share the send queue and enabled extension; each client must manage its own permissions.

## Troubleshooting

- **Inbox not found:** `THUNDERBIRD_INBOX_PATH` must point to a real mbox file, not an account directory or Maildir. The server does not discover Thunderbird profiles.
- **Operation not permitted:** grant the launching app or terminal the necessary file access in macOS System Settings → Privacy & Security.
- **The client only accepts a URL:** use a client supporting local stdio. This project has no HTTP/SSE endpoint.
- **Extension offline or missing features:** check Thunderbird/extension versions, native-host path, `.venv/bin/python`, and extension activation. Reinstalling the MCP client cannot add Thunderbird features.
- **Tools unchanged after an upgrade:** refresh/reconnect MCP using the client's procedure, and check in a new conversation if needed. Source version alone does not prove the connected process was updated.
