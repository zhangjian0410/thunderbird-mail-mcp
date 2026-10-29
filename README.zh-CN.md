# Thunderbird Mail MCP

[English](README.md) | **简体中文**

让 AI Agent 通过 [Model Context Protocol（MCP）](https://modelcontextprotocol.io/) 查询本机 Thunderbird 收件箱和已发送邮件（Sent）、读取附件、创建草稿，以及在显式启用后直接发送用户明确授权的邮件。服务默认使用 `review` 档位，不公布直接发送工具。
**发送类工具各自独立：`send_email` 发送新邮件，`reply_email` / `forward_email` 发送来源绑定的原生回复或附件转发，`create_draft` 只保存草稿，`compose_email` 只打开写信窗口。保存草稿不是发送的前置条件。**

这是一个独立的 Python MCP server，使用标准 **stdio** 传输。它不依赖 Codex、Qoder、QwenWork 或任何模型供应商的 SDK、账号、API Key、Skill、私有配置目录。客户端负责启动服务、选择模型和管理工具调用权限；服务负责邮件数据与 Thunderbird 的交互。

## 能做什么

| 能力 | MCP 工具 | 已实现的行为 |
|---|---|---|
| 搜索和分页查询邮件 | `list_mail_folders`、`query_email`、`search_email`、`list_recent_email` | 新查询接口支持精确发件人、时间范围及 Inbox/Sent 文件夹选择，默认只查 Inbox；旧接口仍只读 Inbox |
| **查询已发送邮件（Sent）** | **`query_email(folders=["Sent"])`** | 枚举已保存的发送副本；结果可继续用于读取正文和附件，调用示例见[Sent 查询](#查询已发送邮件sent) |
| 读取邮件正文 | `read_emails`、`read_email` | 批量或单封读取，分离历史引用；新接口返回截断信息及附件 ID/哈希 |
| 读取附件 | `read_attachment` | 按附件 ID 分段返回内容，提供大小和 SHA-256 校验信息 |
| 打开写信窗口 | `compose_email` | 调用 Thunderbird 原生 CLI 打开已填写的窗口，由用户继续编辑、保存或发送；接口本身不发送 |
| 保存原生草稿 | `create_draft` | 通过扩展保存纯文本或 HTML 草稿，支持附件；只保存，不发送 |
| **直接发送邮件** | **`send_email`** | 通过扩展调用 `compose.sendMessage(..., {mode: "sendNow"})`，支持纯文本、HTML 和附件；无需先调用 `create_draft` 或手动点击发送 |
| 原生回复或全部回复 | `reply_email` | 用 RFC Message-ID 和账户唯一定位原邮件，通过 `compose.beginReply` 创建真实回复；必须显式提供授权收件人、正文与发件身份，需要扩展 `reply_v1` |
| 原生附件转发 | `forward_email` | 用 RFC Message-ID 和账户唯一定位原邮件，通过 `compose.beginForward(..., "forwardAsAttachment")` 保留 Thunderbird 原生 `.eml`，并用来源 raw fingerprint、附件 ID 与 metadata 约束；需要扩展 `forward_v1` |
| Prepare-only 转发诊断 | `diagnose_forward_preparation`、`get_forward_diagnostic_status` | 创建并检查原生附件转发后关闭目标窗口，不保存草稿或发送；诊断队列与发送队列隔离，需要扩展 `forward_diagnostic_v1` |
| 查询发送条件和结果 | `get_send_capabilities`、`get_send_status` | 查询扩展在线状态、发件身份、特性及持久请求状态，提供幂等去重和发送副本验证信息 |

查询不修改 mbox，也不标记已读。服务不直接连接 SMTP、POP 或 IMAP；账号认证和真实投递由 Thunderbird 处理。当前版本 **0.12.0**，总计 **16 个工具**；默认 `review` 公布 13 个，`read_only` 公布 10 个，只有 `direct_send` 公布全部 16 个。详见[工具与行为参考](docs/reference.md)。回复、转发和 prepare-only 诊断须加载对应新版扩展并重新连接 MCP；更新文件不代表旧进程已生效。

## 服务端能力档位

通过客户端启动环境变量 `THUNDERBIRD_MCP_PROFILE` 选择档位：

| 值 | 工具数 | 行为 |
|---|---:|---|
| `read_only` | 10 | 仅查询、读取和状态工具，不打开写信窗口、不保存草稿、不运行 prepare-only 诊断、不发送 |
| `review`（默认） | 13 | 在只读能力上增加 `compose_email`、`create_draft`、`diagnose_forward_preparation`，仍不公布直接发送工具 |
| `direct_send` | 16 | 再增加 `send_email`、`reply_email`、`forward_email` |

值必须精确匹配；空值或未知值会使服务拒绝启动。修改后要重新连接或重启 MCP 服务并刷新工具列表。`get_send_capabilities` 会返回当前 `mcp_profile` 及 `review_enabled` / `direct_send_enabled`，供客户端核对实际进程。服务档位限制工具可见性，但不代替逐封发送授权。

## 查询已发送邮件（Sent）

**Sent 是已发送副本文件夹，查询入口为 `query_email` 的 `folders` 参数。** 当前没有独立的 `sent()` 工具。直接发送新邮件的工具是 `send_email`；下面的查询调用只读取本地邮件。

先调用 `list_mail_folders`，确认返回的 `Sent` 项为 `available=true`。然后调用 **`query_email`**，传入以下参数：

```json
{
  "folders": ["Sent"],
  "page_size": 50
}
```

合并查询收件箱和已发送邮件时，仍调用同一个工具：

```json
{
  "folders": ["Inbox", "Sent"],
  "page_size": 50
}
```

结果中的 `folder` 标明来源，`locator` 可继续传给 `read_emails` 读取正文，再使用附件 ID 调用 `read_attachment`。有后续页面时，把 `next_cursor` 作为 `cursor`，保留相同查询条件继续调用。省略 `folders` 仍只查询 Inbox；旧的 `search_email`、`read_email`、`list_recent_email` 也只读取 Inbox。

Sent 默认使用 Inbox 同目录的 `Sent` mbox。若实际存放位置不同，在客户端启动配置的 `env` 中显式设置：

```json
{
  "THUNDERBIRD_INBOX_PATH": "/absolute/path/to/Inbox",
  "THUNDERBIRD_SENT_PATH": "/absolute/path/to/Sent"
}
```

这些调用不发送、移动或标记邮件。Sent 只包含已保存的发送副本，不包含待发 Outbox；副本存在不等于对方已经收到。完整参数和边界见[Inbox 与已发送副本查询](docs/reference.md#inbox-与已发送副本查询)。

## Harness 与客户端兼容性

接入条件是：客户端能在邮件所在机器上启动本地进程，并支持 MCP stdio 的握手、工具发现和调用。更换客户端不需要修改服务代码。`mcpServers`、TOML 或其他配置外层属于客户端约定，不是 MCP 协议统一规定的文件格式。

| 客户端 | 当前依据与验证范围 |
|---|---|
| 通用 MCP 客户端 | 自动测试使用官方 MCP Python SDK 和两个任意客户端身份，实际完成 stdio 握手、三档工具发现、临时邮件查询、正文及附件读取 |
| Codex | 已有本机接入使用；同样运行 `server.py`，服务不读取 Codex 配置或规则 |
| Qoder IDE / CLI | [IDE 官方文档](https://docs.qoder.com/user-guide/chat/model-context-protocol)与 [CLI 官方文档](https://docs.qoder.com/cli/mcp-reference)均支持本地 stdio；符合接入条件，尚未做本项目的客户端端到端实测 |
| QwenWork 桌面端（千问办公） | [官方连接器文档](https://docs.qwenwork.cn/features/connectors)支持自定义 STDIO 服务；符合接入条件，尚未做本项目的客户端端到端实测 |
| 其他支持本地 MCP stdio 的 Agent | 使用相同启动参数；具体客户端版本需自行验证连接和工具调用 |
| 仅支持远程 HTTP/SSE 的客户端或云端 Agent | 当前不能直接接入；本项目没有 HTTP/SSE 端点，也没有远程网关 |

Harness 无关不等于操作系统无关。**当前原生部署面向 macOS**：写信程序路径、Native Messaging 注册位置和发送状态目录采用 macOS 约定。Linux CI 验证协议与模拟逻辑，不代表 Linux/Windows 原生 Thunderbird 部署已支持。

## 环境要求

- Python **3.10+**，推荐 **3.11**；依赖通过 uv **0.13.0** 和 `uv.lock` 安装。
- 查询需要可读的本地 **mbox 文件**，支持 Inbox 和 Sent 已发送副本，适用于已有 Thunderbird 本地 POP 邮件。Sent 默认取 Inbox 同目录的 `Sent` 文件，也可单独配置；不会自动发现账户或待发 Outbox，不支持直接读取 Maildir。
- 打开原生写信窗口需要 Thunderbird 安装在 `/Applications/Thunderbird.app`。
- 创建草稿、直接发送、回复、转发或 prepare-only 诊断需要 Thunderbird **153+**、与源码匹配的 **0.12.0** 扩展及 native host；查询功能不需要扩展。
- Node **22.23.0** 仅用于开发测试，日常运行 Python 服务不需要 Node。

## 快速开始

### 1. 安装服务

安装 Git、Python 和指定版本的 uv 后，在新的检出目录执行：

```bash
git clone https://github.com/zhangjian0410/thunderbird-mail-mcp.git
cd thunderbird-mail-mcp
uv lock --check
uv sync --locked --no-install-project
uv sync --locked --no-build-isolation
```

两步同步先安装锁定的构建工具，再用这些工具安装本项目；不会另外解析未锁定的构建环境。不要在已有服务使用的目录里直接升级；先在独立检出中验证。

### 2. 配置本地 MCP 客户端

打开 Thunderbird 的账户设置，找到本地目录并确认真实的 mbox Inbox **文件**。将[通用配置示例](examples/mcp-stdio.json)中的三个绝对路径替换为自己的路径：

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

`command` 是 Python 可执行文件，`args` 中的 `server.py` 是单独参数，`env` 传入服务进程。绝对路径使启动不依赖客户端工作目录；路径含空格时也不要把 Python 与脚本合并成 JSON 的一个 `command` 字符串。

Qoder IDE 在设置 → MCP → My Servers → Add 中添加配置；CLI 按其官方说明放入 `mcpServers`。QwenWork 桌面端在扩展 → 连接器 → 添加中导入 JSON，或选择 STDIO 手动填写等价的启动命令及环境变量。其他客户端按自己的格式填写相同的 `command`、`args`、`env`。

`THUNDERBIRD_INBOX_PATH` 指定收件箱；省略时使用 `~/Library/Thunderbird/Inbox` 占位路径。可选的 `THUNDERBIRD_SENT_PATH` 指定已发送副本 mbox，省略时取 Inbox 同目录的 `Sent`。两者都支持绝对路径及 `~`，不会自动扫描账户或核验 Thunderbird 的 FCC 保存位置；Sent 实际位置不同应显式配置。`THUNDERBIRD_MCP_PROFILE` 省略时为 `review`；只有确实需要直接发送且调用方会管理逐封授权时才设为 `direct_send`。无需填写邮箱密码或模型 API Key。

### 3. 验证查询

在客户端启用服务并刷新工具列表，默认 `review` 应发现 13 个工具；`read_only` 为 10 个，`direct_send` 为 16 个。先调用 `get_send_capabilities` 核对 `mcp_profile`，再用 `list_mail_folders` 确认 Inbox 可用并查询邮件，例如：

> 查询发件人为 sender@example.test 的邮件，列出主题和日期；读取我指定的一封邮件，不创建草稿或发送。

工具调用成功只证明本地数据可读；Thunderbird 是否已与邮件服务器同步需要另外确认。要使用草稿和发送能力，继续阅读[可选写信部署](docs/reference.md#可选写信部署macos)。

查询已发送邮件和合并范围的参数示例见[Sent 查询](#查询已发送邮件sent)。Sent 未配置到有效文件时，不影响默认 Inbox 查询。

### 4. 使用写信能力

`compose_email` 只需本机 Thunderbird。`create_draft`、`send_email`、`reply_email`、`forward_email` 和 prepare-only 诊断都需要已启用的扩展及 native host；先通过 `get_send_capabilities` 确认 `ready=true`、实际发件身份和档位。直接发送、回复或转发还要求服务以 `direct_send` 启动。附件、草稿、HTML、回复、转发、诊断分别要求扩展支持 `attachments_v1`、`draft_v1`、`html_v1`、`reply_v1`、`forward_v1`、`forward_diagnostic_v1`。

按任务选择接口：只需保存草稿时调用 `create_draft`；用户已明确授权直接发送时调用 `send_email`。两者提交请求后，都用 `get_send_status` 查询结果：`drafted` 表示保存成功，`sent` 表示 Thunderbird 确认提交至发件服务器。`pending` 只是受理请求，不能据此宣称已经发送。

保存草稿不会自动触发后续发送。若先预览草稿再发送，后续发送是单独的 `send_email` 请求，使用新的幂等键；本项目没有按草稿 ID 发送的 MCP 接口。HTML 先保存草稿检查排版是使用建议，服务不会强制执行该步骤。

## 使用边界

- 服务端按 `read_only` / `review` / `direct_send` 只注册所选档位允许的工具；默认 `review` 不公布直接发送工具。档位在进程启动时固定，修改环境变量后须重连。隐藏工具的 MCP 调用会失败。
- 发送权限由调用方管理。服务不读取任何 Harness 的审批白名单，也不解析自然语言授权；调用方须在调用发送、回复或转发工具前取得收件对象与用途的明确授权。服务端没有逐封人工审批记录或确认令牌校验；客户端是否弹出确认由所用 Harness 配置决定。
- `pending` / `sending` 不代表发送成功；`sent` 表示 Thunderbird 确认提交，不保证收件人收到。同一封邮件重试必须复用幂等键，结果不明时不能换键重发。
- 本地完整枚举不等于服务器同步完成；检查查询返回的 `coverage`、分页和正文截断信息。
- mbox、原生配置、发送数据库、XPI 和部署备份可能含私人数据，不能提交到 Git。自动扫描覆盖受版本控制的当前文件与 Git 历史。

## 项目结构与文档

| 路径 | 用途 |
|---|---|
| `server.py` | MCP stdio 入口与 16 个工具定义 |
| `mail_reader.py` / `mail_store.py` | 本地 mbox 查询、正文与附件读取，及旧接口兼容 |
| `mail_composer.py` | 打开 Thunderbird 写信窗口 |
| `mail_sender.py` / `native_host.py` | 持久发送队列、幂等状态与扩展桥接 |
| `extension/` / `native-send-launcher` | Thunderbird 扩展与 native host 启动器 |
| `scripts/` / `tests/` | 打包、部署检查、敏感信息扫描与自动测试 |
| `examples/mcp-stdio.json` | 与 Harness 无关的本地启动参数示例 |

- [工具、数据边界与写信部署](docs/reference.md)
- [开发、依赖更新、CI 与敏感信息检查](docs/development.md)
- [版本变更](CHANGELOG.md)

完整测试命令：

```bash
uv run --no-sync python -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

测试使用临时邮箱和模拟发送接口，协议测试直接启动独立 MCP 子进程，不调用模型 API、不部署扩展、不发送真实邮件。

## 许可证

本项目采用 [MIT License](LICENSE)。
