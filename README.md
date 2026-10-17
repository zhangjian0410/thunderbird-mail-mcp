# Thunderbird Mail MCP

让 AI Agent 通过 [Model Context Protocol（MCP）](https://modelcontextprotocol.io/) 查询本机 Thunderbird 邮件、读取附件、创建草稿，以及直接发送用户明确授权的邮件。

**当前已实现直接发送：`send_email` 通过 Thunderbird 扩展立即发信；`create_draft` 只保存草稿；`compose_email` 只打开写信窗口。三者是独立接口，保存草稿不是直接发送的前置条件。**

这是一个独立的 Python MCP server，使用标准 **stdio** 传输。它不依赖 Codex、Qoder、QwenWork 或任何模型供应商的 SDK、账号、API Key、Skill、私有配置目录。客户端负责启动服务、选择模型和管理工具调用权限；服务负责邮件数据与 Thunderbird 的交互。

## 能做什么

| 能力 | MCP 工具 | 已实现的行为 |
|---|---|---|
| 搜索和分页查询邮件 | `list_mail_folders`、`query_email`、`search_email`、`list_recent_email` | 读取 Thunderbird 本地 mbox；新查询接口支持精确发件人和时间范围，旧接口保留兼容 |
| 读取邮件正文 | `read_emails`、`read_email` | 批量或单封读取，分离历史引用；新接口返回截断信息及附件 ID/哈希 |
| 读取附件 | `read_attachment` | 按附件 ID 分段返回内容，提供大小和 SHA-256 校验信息 |
| 打开写信窗口 | `compose_email` | 调用 Thunderbird 原生 CLI 打开已填写的窗口，由用户继续编辑、保存或发送；接口本身不发送 |
| 保存原生草稿 | `create_draft` | 通过扩展保存纯文本或 HTML 草稿，支持附件；只保存，不发送 |
| **直接发送邮件** | **`send_email`** | 通过扩展调用 `compose.sendMessage(..., {mode: "sendNow"})`，支持纯文本、HTML 和附件；无需先调用 `create_draft` 或手动点击发送 |
| 查询发送条件和结果 | `get_send_capabilities`、`get_send_status` | 查询扩展在线状态、发件身份、特性及持久请求状态，提供幂等去重和发送副本验证信息 |

查询不修改 mbox，也不标记已读。服务不直接连接 SMTP、POP 或 IMAP；账号认证和真实投递由 Thunderbird 处理。当前版本 **0.5.0**，提供 **12 个工具**，详见[工具与行为参考](docs/reference.md)。

## Harness 与客户端兼容性

接入条件是：客户端能在邮件所在机器上启动本地进程，并支持 MCP stdio 的握手、工具发现和调用。更换客户端不需要修改服务代码。`mcpServers`、TOML 或其他配置外层属于客户端约定，不是 MCP 协议统一规定的文件格式。

| 客户端 | 当前依据与验证范围 |
|---|---|
| 通用 MCP 客户端 | 自动测试使用官方 MCP Python SDK 和两个任意客户端身份，实际完成 stdio 握手、12 工具发现、临时邮件查询、正文及附件读取 |
| Codex | 已有本机接入使用；同样运行 `server.py`，服务不读取 Codex 配置或规则 |
| Qoder IDE / CLI | [IDE 官方文档](https://docs.qoder.com/user-guide/chat/model-context-protocol)与 [CLI 官方文档](https://docs.qoder.com/cli/mcp-reference)均支持本地 stdio；符合接入条件，尚未做本项目的客户端端到端实测 |
| QwenWork 桌面端（千问办公） | [官方连接器文档](https://docs.qwenwork.cn/features/connectors)支持自定义 STDIO 服务；符合接入条件，尚未做本项目的客户端端到端实测 |
| 其他支持本地 MCP stdio 的 Agent | 使用相同启动参数；具体客户端版本需自行验证连接和工具调用 |
| 仅支持远程 HTTP/SSE 的客户端或云端 Agent | 当前不能直接接入；本项目没有 HTTP/SSE 端点，也没有远程网关 |

Harness 无关不等于操作系统无关。**当前原生部署面向 macOS**：写信程序路径、Native Messaging 注册位置和发送状态目录采用 macOS 约定。Linux CI 验证协议与模拟逻辑，不代表 Linux/Windows 原生 Thunderbird 部署已支持。

## 环境要求

- Python **3.10+**，推荐 **3.11**；依赖通过 uv **0.13.0** 和 `uv.lock` 安装。
- 查询需要一个可读的本地 **mbox 文件**。当前入口配置一个 Inbox，适用于已有 Thunderbird 本地 POP 邮件；不会自动发现账户，不支持直接读取 Maildir。
- 打开原生写信窗口需要 Thunderbird 安装在 `/Applications/Thunderbird.app`。
- 创建草稿或自动发送需要 Thunderbird **153+**、本仓库 **0.5.0** 扩展及 native host；查询功能不需要扩展。
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
        "THUNDERBIRD_INBOX_PATH": "/absolute/path/to/Inbox"
      }
    }
  }
}
```

`command` 是 Python 可执行文件，`args` 中的 `server.py` 是单独参数，`env` 传入服务进程。绝对路径使启动不依赖客户端工作目录；路径含空格时也不要把 Python 与脚本合并成 JSON 的一个 `command` 字符串。

Qoder IDE 在设置 → MCP → My Servers → Add 中添加配置；CLI 按其官方说明放入 `mcpServers`。QwenWork 桌面端在扩展 → 连接器 → 添加中导入 JSON，或选择 STDIO 手动填写等价的启动命令及环境变量。其他客户端按自己的格式填写相同的 `command`、`args`、`env`。

唯一的邮件路径环境变量是 `THUNDERBIRD_INBOX_PATH`。省略时服务使用 `~/Library/Thunderbird/Inbox` 占位路径，不会自动扫描账户。无需填写邮箱密码或模型 API Key。

### 3. 验证查询

在客户端启用服务并刷新工具列表，应能发现 12 个工具。先调用 `list_mail_folders` 确认 Inbox 可用，再查询和读取邮件，例如：

> 查询发件人为 sender@example.test 的邮件，列出主题和日期；读取我指定的一封邮件，不创建草稿或发送。

工具调用成功只证明本地数据可读；Thunderbird 是否已与邮件服务器同步需要另外确认。要使用草稿和发送能力，继续阅读[可选写信部署](docs/reference.md#可选写信部署macos)。

### 4. 使用写信能力

`compose_email` 只需本机 Thunderbird。`create_draft` 和 `send_email` 都需要已启用的扩展及 native host；先通过 `get_send_capabilities` 确认 `ready=true` 和实际发件身份。附件、草稿、HTML 分别要求扩展支持 `attachments_v1`、`draft_v1`、`html_v1`。

按任务选择接口：只需保存草稿时调用 `create_draft`；用户已明确授权直接发送时调用 `send_email`。两者提交请求后，都用 `get_send_status` 查询结果：`drafted` 表示保存成功，`sent` 表示 Thunderbird 确认提交至发件服务器。`pending` 只是受理请求，不能据此宣称已经发送。

保存草稿不会自动触发后续发送。若先预览草稿再发送，后续发送是单独的 `send_email` 请求，使用新的幂等键；本项目没有按草稿 ID 发送的 MCP 接口。HTML 先保存草稿检查排版是使用建议，服务不会强制执行该步骤。

## 使用边界

- 当前服务始终公布所有 12 个工具，没有服务端只读模式开关。仅需查询时，应在客户端限制 `compose_email`、`create_draft` 和 `send_email` 的使用。
- 发送权限由调用方管理。服务不读取任何 Harness 的审批白名单，也不解析自然语言授权；调用方须在调用 `send_email` 前取得收件对象与用途的明确授权。服务端没有逐封人工审批记录或确认令牌校验；客户端是否弹出确认由所用 Harness 配置决定。
- `pending` / `sending` 不代表发送成功；`sent` 表示 Thunderbird 确认提交，不保证收件人收到。同一封邮件重试必须复用幂等键，结果不明时不能换键重发。
- 本地完整枚举不等于服务器同步完成；检查查询返回的 `coverage`、分页和正文截断信息。
- mbox、原生配置、发送数据库、XPI 和部署备份可能含私人数据，不能提交到 Git。自动扫描覆盖受版本控制的当前文件与 Git 历史。

## 项目结构与文档

| 路径 | 用途 |
|---|---|
| `server.py` | MCP stdio 入口与 12 个工具定义 |
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
