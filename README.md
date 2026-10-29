# Thunderbird Mail MCP

**English** | [简体中文](README.zh-CN.md)

Give AI agents access to local Thunderbird mail through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/): search Inbox and Sent, read messages and attachments, save drafts, and send explicitly authorized mail when enabled. The server defaults to the `review` profile, which does not expose direct-send tools.

**Each writing tool has a separate purpose:** `send_email` sends a new message; `reply_email` and `forward_email` send a native reply or attachment forward bound to a source message; `create_draft` only saves a draft; and `compose_email` only opens a compose window. Saving a draft is not a prerequisite for sending.

This is a standalone Python MCP server using standard **stdio** transport. It does not depend on Codex, Qoder, QwenWork, any model provider's SDK or account, API keys, skills, or private client configuration directories. The client starts the server, selects a model, and manages tool-call permissions. The server handles local mail data and its interaction with Thunderbird.

## Features

| Capability | MCP tools | Behavior |
|---|---|---|
| Search and paginate mail | `list_mail_folders`, `query_email`, `search_email`, `list_recent_email` | The newer query API supports exact sender addresses, date ranges, and Inbox/Sent selection; it defaults to Inbox. Legacy tools read Inbox only. |
| Query sent copies | `query_email(folders=["Sent"])` | Enumerate saved sent copies, then read their bodies and attachments. See [Sent queries](#query-sent-mail). |
| Read message bodies | `read_emails`, `read_email` | Read messages individually or in batches, with quoted history separated. The newer API reports truncation and attachment IDs/hashes. |
| Read attachments | `read_attachment` | Return attachment content in chunks, with size and SHA-256 verification data. |
| Open a compose window | `compose_email` | Use Thunderbird's native CLI to open a prefilled window for the user to edit, save, or send. The tool itself does not send. |
| Save native drafts | `create_draft` | Save plain-text or HTML drafts with attachments through the extension. Never sends. |
| Send new mail | `send_email` | Use the extension's `compose.sendMessage(..., {mode: "sendNow"})` with plain text, HTML, or attachments. No draft or manual Send click is required. |
| Reply or reply all | `reply_email` | Locate the source uniquely by RFC Message-ID and account, then use `compose.beginReply`. Authorized recipients, body, and sender identity must be explicit. Requires `reply_v1`. |
| Forward as attachment | `forward_email` | Locate the source by RFC Message-ID and account, then use `compose.beginForward(..., "forwardAsAttachment")`. Preserve Thunderbird's native `.eml` and check the source raw fingerprint, attachment ID, and metadata. Requires `forward_v1`. |
| Diagnose forward preparation | `diagnose_forward_preparation`, `get_forward_diagnostic_status` | Prepare and inspect a native attachment forward without saving or sending, then attempt to close its window. Check `close_confirmed`. Uses a separate diagnostic queue. Requires `forward_diagnostic_v1`. |
| Inspect capabilities and outcomes | `get_send_capabilities`, `get_send_status` | Read extension health, sender identities, features, the active server profile, and durable request status, including idempotency and sent-copy verification. |

Queries do not modify mbox files or mark messages as read. The server does not connect directly to SMTP, POP, or IMAP; Thunderbird handles account authentication and delivery. Current version: **0.12.0**, with **16 tools** in total. The default `review` profile exposes 13, `read_only` exposes 10, and `direct_send` exposes all 16. See the [tool and behavior reference](docs/reference.md).

Replies, forwards, and preparation diagnostics require an extension with the corresponding features and a refreshed MCP connection. Updating files does not update a running process.

## Capability profiles

Set `THUNDERBIRD_MCP_PROFILE` in the environment used to launch the server:

| Value | Tools | Behavior |
|---|---:|---|
| `read_only` | 10 | Queries, message/attachment reads, and status checks only. No compose windows, draft creation, preparation diagnostics, or sending. |
| `review` (default) | 13 | Adds `compose_email`, `create_draft`, and `diagnose_forward_preparation`. Direct-send tools remain unavailable. |
| `direct_send` | 16 | Also exposes `send_email`, `reply_email`, and `forward_email`. |

Values must match exactly. An empty or unknown value prevents startup. After changing the setting, restart or reconnect the MCP server and refresh the tool list. `get_send_capabilities` reports `mcp_profile`, `review_enabled`, and `direct_send_enabled` so clients can verify the connected process.

Profiles control which tools the server registers. They do not replace authorization for individual messages or cancel queued work. Status/capability calls may initialize or update the local journal even in `read_only`.

## Query sent mail

**Sent contains saved sent copies. Query it with the `folders` parameter of `query_email`.** There is no separate `sent()` tool. `send_email` sends new mail; the queries below only read local data.

First call `list_mail_folders` and confirm that the `Sent` entry has `available=true`. Then call `query_email` with:

```json
{
  "folders": ["Sent"],
  "page_size": 50
}
```

To search Inbox and Sent together, use the same tool:

```json
{
  "folders": ["Inbox", "Sent"],
  "page_size": 50
}
```

Each result includes its source `folder` and a `locator`. Pass locators to `read_emails`, then use attachment IDs with `read_attachment`. Follow `next_cursor` by passing it as `cursor` with the same query parameters. Omitting `folders` searches Inbox only; the legacy `search_email`, `read_email`, and `list_recent_email` tools also read Inbox only.

By default, Sent is the `Sent` mbox beside the configured Inbox file. If it lives elsewhere, set its path explicitly in the client's launch environment:

```json
{
  "THUNDERBIRD_INBOX_PATH": "/absolute/path/to/Inbox",
  "THUNDERBIRD_SENT_PATH": "/absolute/path/to/Sent"
}
```

These calls do not send, move, or mark messages. Sent does not include pending Outbox messages, and a saved copy does not prove recipient delivery. Full parameters and boundaries are documented in the [Inbox and Sent reference](docs/reference.md#inbox-and-sent-queries).

## Client compatibility

A compatible client must be able to start a local process on the machine holding the mail and support MCP stdio initialization, tool discovery, and calls. Switching clients does not require server code changes. Configuration wrappers such as `mcpServers` or TOML are client conventions, not a universal MCP configuration format.

| Client | Evidence and verification scope |
|---|---|
| Generic MCP clients | Automated tests use the official MCP Python SDK and two arbitrary client identities to exercise stdio initialization, tool discovery, fixture-mail queries, body reads, and attachment reads. Separate tests cover the capability profiles. |
| Codex | Used in a local setup with the same `server.py`. The server does not read Codex settings or rules. |
| Qoder IDE / CLI | The [IDE documentation](https://docs.qoder.com/user-guide/chat/model-context-protocol) and [CLI documentation](https://docs.qoder.com/cli/mcp-reference) describe local stdio support. Meets the connection requirements; client-specific end-to-end testing has not been performed for this project. |
| QwenWork desktop | The [connector documentation](https://docs.qwenwork.cn/features/connectors) describes custom STDIO services. Meets the connection requirements; client-specific end-to-end testing has not been performed for this project. |
| Other agents supporting local MCP stdio | Use the same launch parameters. Verify the connection and tool calls with your client version. |
| HTTP/SSE-only clients or cloud agents | Cannot connect directly. This project provides no HTTP/SSE endpoint or remote gateway. |

**Native deployment currently targets macOS.** The Thunderbird executable path, Native Messaging registration location, and send-state directory follow macOS conventions. Linux CI verifies the protocol and mocked behavior; it does not establish support for native Thunderbird deployment on Linux or Windows.

## Requirements

- Python **3.10+**, preferably **3.11**. Install dependencies with uv **0.13.0** and the checked-in `uv.lock`.
- Readable local **mbox files** for Inbox and saved Sent copies, such as an existing Thunderbird POP mail store. Sent defaults to a sibling of Inbox and can be configured separately. There is no automatic account discovery, Outbox support, or direct Maildir reading.
- Thunderbird at `/Applications/Thunderbird.app` to open native compose windows.
- Thunderbird **153+**, the matching **0.12.0** extension, and the native host for drafts, sending, replies, forwards, or preparation diagnostics. Mail queries do not require the extension.
- Node **22.23.0** for development tests only; the Python server does not require Node at runtime.

## Quick start

### 1. Install the server

Install Git, Python, and the specified uv version, then use a fresh checkout:

```bash
git clone https://github.com/zhangjian0410/thunderbird-mail-mcp.git
cd thunderbird-mail-mcp
uv lock --check
uv sync --locked --no-install-project
uv sync --locked --no-build-isolation
```

The first sync installs the locked build tools; the second uses them to install this project without resolving a separate build environment. Validate upgrades in a separate checkout before changing an installation used by a running service.

### 2. Configure a local MCP client

Find Thunderbird's local mail directory in Account Settings and identify the actual mbox Inbox **file**. Replace the three absolute paths in the [generic configuration example](examples/mcp-stdio.json):

```json
{
  "mcpServers": {
    "thunderbird_mail": {
      "type": "stdio",
      "command": "/absolute/path/thunderbird-mail-mcp/.venv/bin/python",
      "args": ["/absolute/path/thunderbird-mail-mcp/server.py"],
      "env": {
        "THUNDERBIRD_INBOX_PATH": "/absolute/path/to/Inbox",
        "THUNDERBIRD_MCP_PROFILE": "review"
      }
    }
  }
}
```

`command` is the Python executable; the script path is a separate entry in `args`; `env` is passed to the server process. Absolute paths avoid dependence on the client's working directory. Even when paths contain spaces, do not combine Python and the script into one `command` string.

In Qoder IDE, add the configuration under Settings → MCP → My Servers → Add; for the CLI, follow its documented `mcpServers` format. In QwenWork desktop, import the JSON under Extensions → Connectors → Add, or choose STDIO and enter equivalent launch parameters. Other clients use the same `command`, `args`, and `env` in their own configuration format.

`THUNDERBIRD_INBOX_PATH` selects Inbox; if omitted, the server uses the placeholder `~/Library/Thunderbird/Inbox`. Optional `THUNDERBIRD_SENT_PATH` selects the Sent mbox; otherwise it uses `Sent` beside Inbox. Both paths support absolute paths and `~`. The server does not scan accounts or verify Thunderbird's configured sent-copy (FCC) location. Set Sent explicitly when its actual location differs.

`THUNDERBIRD_MCP_PROFILE` defaults to `review`. Select `direct_send` only when direct sending is needed and the caller manages message authorization. No mailbox password or model API key is required.

### 3. Verify mail queries

Enable the server in your client and refresh its tool list. Expect 13 tools with the default `review` profile, 10 with `read_only`, or 16 with `direct_send`. Call `get_send_capabilities` to verify `mcp_profile`, then `list_mail_folders` to confirm Inbox is available. For example, ask your agent:

> Find messages from sender@example.test and list their subjects and dates. Read a message I select, without creating drafts or sending mail.

Successful queries prove that local data is readable. They do not establish whether Thunderbird has synchronized with the mail server. See [Sent queries](#query-sent-mail) for saved sent copies and combined-folder queries; an unavailable Sent file does not prevent default Inbox queries.

### 4. Use writing tools

`compose_email` only needs the local Thunderbird installation. Drafts, sending, replies, forwards, and preparation diagnostics need the enabled extension and native host. Follow the [optional writing deployment guide](docs/reference.md#optional-writing-deployment-macos).

Check `get_send_capabilities` for `ready=true`, the actual sender identity, and the active profile. Sending, replying, and forwarding also require `direct_send`. Attachments, drafts, HTML, replies, forwards, and diagnostics respectively require `attachments_v1`, `draft_v1`, `html_v1`, `reply_v1`, `forward_v1`, and `forward_diagnostic_v1`.

Use `create_draft` to save a draft, or `send_email` when the user has explicitly authorized sending. After either request, poll `get_send_status`: `drafted` means the draft was saved; `sent` means Thunderbird confirmed submission to the outgoing server. `pending` only means the request was accepted.

Saving a draft does not trigger sending. If a draft is previewed before sending, the later `send_email` call is a separate request with a new idempotency key. There is no MCP tool for sending an existing draft by its ID. Previewing an HTML draft is recommended, but the server does not enforce it as a prerequisite.

## Operational boundaries

- The server registers only the tools allowed by `read_only`, `review`, or `direct_send`. The default `review` profile excludes direct-send tools. Profiles are fixed at process startup; reconnect after changing the environment. MCP calls to hidden tools fail.
- The caller manages sending authorization. The server neither reads a client's approval allowlist nor interprets natural-language permission. Obtain explicit authorization for the recipients and purpose before sending, replying, or forwarding. The server does not validate per-message human approval records or confirmation tokens; client confirmation prompts depend on the client's settings.
- `pending` and `sending` do not mean sent. `sent` confirms Thunderbird's submission, not receipt by the recipient. Retry the same logical message with the same idempotency key. Never use a new key to resend an uncertain outcome.
- Complete local enumeration does not prove server synchronization. Check query `coverage`, pagination, and body truncation metadata.
- Mailboxes, native configuration, send databases, XPI files, and deployment backups may contain private data and must not be committed. Automated scans cover tracked files and Git history.

## Project layout and documentation

| Path | Purpose |
|---|---|
| `server.py` | MCP stdio entry point and 16 tool definitions |
| `mail_reader.py` / `mail_store.py` | Local mbox queries, message/attachment reads, and legacy compatibility |
| `mail_composer.py` | Open Thunderbird compose windows |
| `mail_sender.py` / `native_host.py` | Durable send queue, idempotency state, and extension bridge |
| `extension/` / `native-send-launcher` | Thunderbird extension and native host launcher |
| `scripts/` / `tests/` | Packaging, deployment checks, sensitive-data scans, and automated tests |
| `examples/mcp-stdio.json` | Client-independent local launch example |

This README is the primary English entry point. A complete [Chinese README](README.zh-CN.md) is also available. The tool reference, development guide, and changelog are available in both languages:

- [Tools, data boundaries, and writing deployment](docs/reference.md)
- [Development, dependency updates, CI, and sensitive-data checks](docs/development.md)
- [Changelog](CHANGELOG.md)

Run the full test suite:

```bash
uv run --no-sync python -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

Tests use temporary mailboxes and mocked sending APIs. Protocol tests start independent MCP subprocesses. They do not call model APIs, deploy the extension, or send real mail.

## License

[MIT License](LICENSE).
