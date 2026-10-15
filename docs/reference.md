# 工具与行为参考

[返回工程介绍](../README.md)

## 12 个 MCP 工具

| 工具 | 用途与主要参数 |
|---|---|
| `list_mail_folders()` | 返回已配置本地 mbox 及可用性；当前入口默认只有 Inbox，其他文件夹须在服务端 `READER` 映射登记 |
| `query_email(keyword="", senders=None, start=None, end=None, folders=None, page_size=50, cursor=None)` | 分页查询；空关键词允许枚举，发件人按完整地址匹配，时间为带时区的 ISO 半开区间 `start ≤ date < end`，每页 1–200 封 |
| `read_emails(locators, include_quoted_history=False, max_body_chars=30000)` | 一次读取 1–20 封，返回逐封结果、当前正文、引用正文、截断标记及附件 ID/哈希；正文限制参数范围 1000–100000 字符 |
| `read_attachment(locator, attachment_id, offset=0, max_bytes=262144)` | 分段返回 base64、完整附件 SHA-256、总长度和 `next_offset`；单段最多 1 MiB |
| `search_email(keyword, days=None, sender=None)` | 旧搜索接口：关键词必填、发件人子串匹配、无分页；新集成优先使用 `query_email` |
| `read_email(message_id)` | 旧单封读取接口，返回正文和附件元数据，默认省略历史引用 |
| `list_recent_email(limit=20)` | 旧列表接口，按日期倒序，最多 100 封 |
| `compose_email(to, subject, body, cc=None, bcc=None)` | 打开 Thunderbird 原生写信窗口，不自动发送 |
| `create_draft(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format="plain")` | 通过扩展保存原生草稿，绝不调用发送；轮询状态直到 `drafted` |
| `send_email(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format="plain")` | 通过扩展实际发送用户授权的邮件；返回入队结果后须查询状态 |
| `get_send_status(idempotency_key)` | 查询同一请求的持久状态、Message-ID、发送副本验证结果 |
| `get_send_capabilities()` | 查询扩展心跳、可用发件身份和特性；不发送邮件 |

`to`、`cc`、`bcc` 在草稿/自动发送接口中是纯邮箱地址数组；`from_email` 必须匹配唯一的现有身份。完整输入 schema 由 MCP `tools/list` 返回。

## 查询完整性与附件

推荐调用顺序：`list_mail_folders` → `query_email` → 保持查询参数并跟随 `next_cursor` 至 null → `read_emails` → 按附件 ID 分段 `read_attachment`。

`coverage.local_status=complete` 只证明选定本地 mbox 的匹配记录已枚举；未读正文、未读附件不能视作已经处理。坏日期、发件人等不可索引记录进入 `coverage.gaps`，覆盖仍为 partial。`server_sync_status` 始终为 unknown，不能用文件时间代表 POP 同步完成。

索引仅缓存邮件头和位置。mbox device/inode/size/mtime/ctime 改变会使缓存失效；cursor 绑定查询及快照，locator/cursor 在服务重启或邮箱变化后须重新获取。RFC Message-ID 可能为空或重复，不能替代 locator。旧查询接口会跳过坏日期并向 stderr 发出不含邮件正文的警告。

正文优先取纯文本；HTML 读取只做文字转换。引用分离属于启发式，可用 `include_quoted_history=true` 核查，正文/引用的截断标记分别检查。单封邮件读取上限 64 MiB。附件读取不执行文件、不标记邮件、不连接邮件服务器；调用方须合并分段并校验大小与 SHA-256。附加 `.eml` 标为 `serialized_message_rfc822`，是重新序列化后的邮件；普通附件标为 `decoded_payload`。

## 草稿、HTML 与发送状态

`body_format` 接受 plain（默认）或 html。HTML 必须是真实 HTML，不自动转换 Markdown；扩展使用 HTML 编辑模式和 `deliveryFormat: "both"`，由 Thunderbird 生成纯文本备用内容。接口不支持独立提交两份正文，也不净化任意 HTML。使用简单 table、内联样式，避免脚本、表单、外部资源与跟踪图片；先保存原生草稿检查实际呈现。

附件参数格式为 `[{"path":"/absolute/file.xlsx","sha256":"<64位SHA-256>"}]`，最多 10 个、合计 20 MiB，只接受绝对路径的普通文件。首次入队核验用户已审阅文件的 SHA-256 并保存不可变快照，扩展再校验字节数及哈希；桥接每次最多传 256 KiB。

每次逻辑发送或草稿使用独立 `idempotency_key`；超时或重试须复用原 key。相同 key 重试使用已保存的附件摘要，不重新读取已删除或变化的原文件；仍须提供相同正文、动作、附件文件名/顺序/预期哈希。不能将同一 key 的 plain 改成 html。单独查询状态无需再次提供正文和附件。

| 状态 | 含义 |
|---|---|
| `pending` | 等待扩展领取；尚未发送或保存草稿 |
| `sending` | 已领取；中断后不能自动重新入队 |
| `sent` | Thunderbird 确认提交至发件服务器，不保证最终送达 |
| `drafted` | Thunderbird 已保存草稿；不是发送授权 |
| `failed` / `expired` | 请求失败，或 60 秒内未被领取而过期 |
| `unknown` | 结果无法确认，须核查，不能换 key 重发 |

`copy_status=verified` 表示扩展读到了相同 Message-ID 的发送副本；`not_verified` 不能作为重发理由。Sent/Drafts 位置沿用账户设置，投递与客户端副本保存失败分开报告。

发送队列位于 `~/Library/Application Support/ThunderbirdMailMCP/send.sqlite3`，目录权限 0700、数据库 0600。完成或未领取超时会清除正文并释放附件 BLOB；异常中断的 sending 请求保留取证数据。SQLite 删除不保证底层安全擦除；不要删除数据库来重试结果不明的发送。

## 可选写信部署（macOS）

查询功能不需要安装扩展。需要创建原生草稿或发送时，先在目标安装目录完成 README 中的依赖安装，确保 Thunderbird 153+，然后手动执行：

```bash
chmod 700 native-send-launcher
.venv/bin/python scripts/package_send.py --output dist --install-root "$PWD"
mkdir -p "$HOME/Library/Mozilla/NativeMessagingHosts"
install -m 600 dist/native-host.json "$HOME/Library/Mozilla/NativeMessagingHosts/com.thunderbird_mail_mcp.native_send.json"
```

这些命令会在本机注册 native host；仅在明确选择的安装目录部署。打包本身不启用扩展。在 Thunderbird → 附加组件和主题 → 从文件安装附加组件，选择 `dist/thunderbird-native-send.xpi`，审阅权限后启用。

扩展权限包括 accountsRead、messagesRead、compose、compose.send、compose.save、nativeMessaging、storage。原生主机允许列表仅包含固定扩展 ID `native-send@thunderbird-mail-mcp.local`；同一系统用户下的本地程序仍处于信任边界内。

`native-send-launcher` 使用自身目录下的 `.venv/bin/python`，支持含空格的安装路径。`scripts/deploy_send.py` 的 `--target` 必须与打包时 `--install-root` 一致；`--check` 和实际部署都检查主机路径、名称、stdio 类型和唯一扩展 ID。脚本的参数以 `--help` 为准。

重新连接所用 MCP 客户端以刷新参数；源码更新不会让已运行进程自动重载。`get_send_capabilities().ready` 应为 true，特性包含 `attachments_v1`、`draft_v1`、`html_v1`。发件身份使用返回的实际身份；先检查草稿，再在用户授权下发送。不得用真实发信作为普通安装自检。

停用自动发送可在 Thunderbird 中停用扩展；未领取请求会过期，但已领取或提交的邮件不能靠停用撤回。查询和原生 `compose_email` 不依赖扩展。多个本地 MCP 客户端使用同一系统用户时，共用该用户的发送队列与已启用扩展；各客户端须管理自己的调用权限。

## 常见问题

- **找不到 Inbox**：核对 `THUNDERBIRD_INBOX_PATH` 指向真实 mbox 文件，不是账户目录或 Maildir；服务不会自动发现 Thunderbird profile。
- **Operation not permitted**：在 macOS 系统设置 → 隐私与安全性中，为实际启动服务的应用或终端授予所需文件访问权限。
- **客户端只有 URL 输入框**：确认其支持本地 stdio；本项目没有可填写的 HTTP/SSE 地址。
- **扩展离线或能力缺失**：核对 Thunderbird/扩展版本、native host 路径、`.venv/bin/python` 与扩展是否启用。不会通过重装客户端补齐 Thunderbird 能力。
- **升级后工具未变化**：按所用客户端的流程刷新或重新连接 MCP，必要时在新对话中检查；不要仅凭源码版本判断旧进程已更新。
