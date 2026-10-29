# 工具与行为参考

[English](reference.md) | **简体中文** · [返回工程介绍](../README.zh-CN.md)

## 16 个 MCP 工具（总目录）

| 工具 | 最低档位 | 用途与主要参数 |
|---|---|---|
| `list_mail_folders()` | `read_only` | 返回已配置的 Inbox/Sent 本地 mbox 及可用性；待发 Outbox 未接入 |
| `query_email(keyword="", senders=None, start=None, end=None, folders=None, page_size=50, cursor=None)` | `read_only` | 分页查询；省略 `folders` 时只查 Inbox，可显式选择 Sent 或 Inbox+Sent；空关键词允许枚举，发件人按完整地址匹配，时间为带时区的 ISO 半开区间 `start ≤ date < end`，每页 1–200 封 |
| `read_emails(locators, include_quoted_history=False, max_body_chars=30000)` | `read_only` | 一次读取 1–20 封，返回逐封结果、当前正文、引用正文、截断标记及附件 ID/哈希；正文限制参数范围 1000–100000 字符 |
| `read_attachment(locator, attachment_id, offset=0, max_bytes=262144)` | `read_only` | 分段返回 base64、完整附件 SHA-256、总长度和 `next_offset`；单段最多 1 MiB |
| `search_email(keyword, days=None, sender=None)` | `read_only` | 旧搜索接口：关键词必填、发件人子串匹配、无分页；新集成优先使用 `query_email` |
| `read_email(message_id)` | `read_only` | 读取 Inbox 中首封匹配 Message-ID 的邮件，返回正文和附件元数据；省略识别出的历史引用，没有切换开关 |
| `list_recent_email(limit=20)` | `read_only` | 旧列表接口，按日期倒序，范围为 1–100 封 |
| `compose_email(to, subject, body, cc=None, bcc=None)` | `review` | 打开 Thunderbird 原生写信窗口，不自动发送 |
| `create_draft(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format="plain")` | `review` | 通过扩展保存原生草稿，绝不调用发送；轮询至 `drafted`、`failed`、`expired` 或 `unknown` |
| `send_email(to, subject, body, from_email, idempotency_key, cc=None, bcc=None, attachments=None, body_format="plain")` | `direct_send` | 通过扩展实际发送用户授权的邮件；返回入队结果后须查询状态 |
| `reply_email(to, subject, body, from_email, idempotency_key, source_message_id, source_account_id, identity_id, reply_mode="reply_all", cc=None, bcc=None, attachments=None, body_format="plain")` | `direct_send` | 用原生回复上下文发送；支持 `reply_all` / `reply_sender`；收件范围须与 Thunderbird 原生结果完全一致，需要 `reply_v1` |
| `forward_email(to, subject, body, from_email, idempotency_key, source_message_id, source_account_id, identity_id, forward_mode="forward_attachment", cc=None, bcc=None, attachments=None, body_format="plain")` | `direct_send` | 用原生附件转发上下文发送；已授权说明是精确正文，原邮件保留为 Thunderbird 原生 `.eml`；需要 `forward_v1` |
| `diagnose_forward_preparation(source_message_id, source_account_id, from_email, identity_id, diagnostic_key, body_format="plain")` | `review` | 独立 prepare-only 诊断；真实创建并尝试关闭原生转发 tab，但绝不发送或保存草稿，只记录有界的非敏感大小、哈希与分类结果；附件分类最多保留 16 项，并以 `count` / `truncated` 表示完整数量；需要 `forward_diagnostic_v1` |
| `get_forward_diagnostic_status(diagnostic_key)` | `read_only` | 查询独立诊断队列；不读取或改变发送队列 |
| `get_send_status(idempotency_key)` | `read_only` | 查询同一请求的持久状态、Message-ID、发送副本验证结果，并清理过期的未领取请求 |
| `get_send_capabilities()` | `read_only` | 查询扩展心跳、可用发件身份、特性和当前服务档位；不发送邮件 |

`to`、`cc`、`bcc` 在草稿/自动发送接口中是纯邮箱地址数组；`from_email` 必须匹配唯一的现有身份。`compose_email` 的收件人字段则为字符串。完整输入 schema 由 MCP `tools/list` 返回。

草稿、发送、回复及转发请求的每个收件人列表最多接收 100 项；在各字段内按完全相同的字符串去重后，To/Cc/Bcc 合计最多 100 个地址，且至少有一个 To 地址。主题和正文必须包含非空白文本，分别不超过 998 和 100000 个 UTF-8 字节；这里的字节限制与 `read_emails` 的字符限制不同。主题拒绝控制字符，正文拒绝 NUL。`idempotency_key` 和 `diagnostic_key` 均为 1–128 个 ASCII 字符，首字符必须是字母或数字，其余仅允许字母、数字、`.`、`_`、`:` 或 `-`。

`compose_email` 通过 Thunderbird CLI 启动窗口，不走队列；拒绝空白必填字段，以及收件人/主题中的 CR/LF/NUL。返回 `opened=true` 只确认进程启动成功，不代表已观察到窗口或窗口已经就绪。

## 服务端能力档位

在 MCP 客户端的 `env` 中设置 `THUNDERBIRD_MCP_PROFILE`。值必须精确为以下之一；变量省略时默认为 `review`，空值、大小写变体和未知值都会使服务拒绝启动。

| 档位 | 工具数 | 服务端公布的能力 |
|---|---:|---|
| `read_only` | 10 | 邮件查询、正文/附件读取，以及发送与诊断状态查询；不公布打开写信窗口、保存草稿、prepare-only 诊断或直接发送工具 |
| `review`（默认） | 13 | `read_only` 加 `compose_email`、`create_draft`、`diagnose_forward_preparation`；不公布任何直接发送工具 |
| `direct_send` | 16 | 全部工具，包括 `send_email`、`reply_email`、`forward_email` |

档位在服务进程启动时确定。修改配置后须重新连接或重启 MCP 服务并刷新工具列表；客户端保存着旧连接时，编辑 JSON 本身不会改变现有进程。`get_send_capabilities()` 返回 `mcp_profile`、`review_enabled`、`direct_send_enabled`，可用于核对实际连接。档位只控制 MCP 服务公布哪些工具，不代替逐封授权、幂等检查或 Thunderbird 扩展能力检查。

`ready=true` 只表示扩展最近一次心跳在 15 秒以内，不代表已开放直接发送或已取得发送授权。状态/能力工具可能初始化本地日志数据库，`get_send_status` 还会清理过期的未领取请求；因此 `read_only` 限制邮件操作，并非禁止全部文件系统写入。降低档位不会取消其他连接或旧进程已经入队的请求。

## Inbox 与已发送副本查询

`THUNDERBIRD_INBOX_PATH` 指向收件箱 mbox；`THUNDERBIRD_SENT_PATH` 可单独指定已发送副本 mbox，省略时使用 Inbox 同目录的 `Sent`。这只是显式路径配置及默认路径派生，不会发现账户、读取账户密码或自动核验 FCC 设置；实际发送副本位置由 Thunderbird 决定。

`query_email()` 默认仍只查询 Inbox，即使 Sent 文件不可用也不影响此默认范围。传入 `folders=["Sent"]` 可枚举已发送副本，`folders=["Inbox", "Sent"]` 合并查询；每条结果保留 `folder`，其 locator 可继续传给 `read_emails` / `read_attachment`。旧 `search_email`、`read_email`、`list_recent_email` 保持仅限 Inbox。

`query_email` 的关键词匹配主题、From 和解码正文（含历史引用），不搜索附件内容。发件人筛选忽略大小写并精确匹配地址；提供 `senders` 时列表不能为空。结果按日期倒序排列。旧 `search_email` 使用 From 子串，可选正整数 `days` 限定回溯天数，省略则查询全部日期；旧 `read_email` 精确匹配 Message-ID 头（包括尖括号）并返回首个匹配结果，ID 重复时应优先使用 locator。

Sent 查询链只读取本地 mbox，不触发 `send_email`，不移动或标记邮件。Sent 是已保存的发送副本，不是待发 Outbox；Outbox、空范围、重复或未知文件夹名称均不接受。`server_sync_status` 仍为 unknown，副本存在不能证明对方收到邮件。

## 写信、回复、转发与诊断接口的执行路径

| 接口 | 服务与 Thunderbird 执行路径 | 最终行为 |
|---|---|---|
| `compose_email` | `MailComposer` → Thunderbird CLI `-compose` | 打开写信窗口；接口不自动保存或发送 |
| `create_draft` | 入队时指定 `action="draft"` → 扩展 `compose.saveMessage(..., {mode: "draft"})` | 只保存草稿，状态为 `drafted` |
| `send_email` | 入队使用默认 `action="send"` → 扩展 `compose.sendMessage(..., {mode: "sendNow"})` | 直接发信，成功后状态为 `sent`；不会先调用保存草稿接口 |
| `reply_email` | 入队保留不可变 `reply` → 账户内唯一定位 RFC Message-ID → `compose.beginReply(..., "replyToAll" / "replyToSender")` → `sendMessage(..., {mode: "sendNow"})` | 发送真实回复；任何定位、身份或收件范围失配都停止，不回退到新邮件 |
| `forward_email` | 入队保留不可变 `forward` → 账户内唯一定位 RFC Message-ID → 冻结原始邮件字节 → `compose.beginForward(..., "forwardAsAttachment")` → 设置精确说明正文 → `sendMessage(..., {mode: "sendNow"})` | 发送真实附件式转发；保留 Thunderbird 原生 `.eml`，检查来源和最终内容，不回退到新邮件；原生附件验证限于下文所述 metadata 检查 |
| `diagnose_forward_preparation` | 独立诊断队列 → 读取来源 raw → 原生 `forwardAsAttachment` → 临时替换并回读 `.eml` → 尝试关闭精确 tab | 只验证准备链；代码路径不调用发送或保存草稿，结果与发送队列隔离 |

`create_draft` 与 `send_email` 不是一条必须顺序执行的调用链。保存草稿是独立动作；直接发送不要求草稿 ID，也不要求用户再在 Thunderbird 窗口中点击发送。扩展离线、发件身份不匹配或缺少所需特性时，新请求会拒绝入队；Thunderbird 的发送过程仍可能失败或返回未知结果。

服务端检查参数、扩展在线状态、身份、特性、附件完整性和幂等键，不检查人工审批记录或确认令牌。调用方负责取得用户授权及执行客户端权限策略；工具描述中的授权要求不是服务端的人工审批机制。

诊断结果包含 `close_confirmed`。窗口关闭失败时返回 `status="failed"` 和 `failure_stage="close_not_confirmed"`，扩展保留该 tab 的发送阻断 guard；不能假定每次诊断都成功关闭窗口。

诊断状态为 `pending`、`running`、`prepared`、`failed` 或 `not_found`。使用同一 key 轮询 `get_forward_diagnostic_status`；读取状态不会推进任务。待领取诊断没有自动过期机制；扩展下次领取诊断时，会把运行超过 15 秒的记录标为失败，返回 `failure_stage="interrupted"`，但这不代表窗口已经关闭。诊断不使用发送/草稿的过期或恢复机制。日志保留发件人、来源、身份等请求上下文，尽管诊断结果不包含邮件正文、地址、主题、路径或原始字节。

## 原生回复边界

`source_message_id` 是原邮件 RFC Message-ID，可带一对尖括号，不能传本地查询 locator 或 Thunderbird 临时数字 ID。先读原邮件并确认用户授权，再从 `get_send_capabilities()` 返回的 `accounts[{id,type,name}]` 按实际账户名称/类型选择原邮件账户，使用 `identities[{id,email,account_id}]` 中与 `from_email` 唯一匹配的 `id`。原邮件可能位于 Local Folders，其账户可以与发件身份账户不同。账户不明确时先核实，不能猜测。

扩展只在指定账户内本地查询 Message-ID，遍历结果页（超过 1000 次续页时失败），要求唯一且非外部文件邮件；原邮件缺失、重复、账户或身份变化、正文读取失败都不发送。使用原生 `beginReply` 后回读 `type="reply"` 和 `relatedMessageId`；先将 Thunderbird 自动计算的 To/Cc/Bcc 与显式授权范围逐字段比较（忽略地址大小写与字段内顺序），不同就尝试关闭准备中的窗口并失败。当前接口不支持在回复时增删或移动收件人字段，原生附带的 Bcc 也必须得到显式授权。

正文参数替换原生自动引用与署名，调用方须提交完整的已授权正文和署名。扩展清理继承附件、关闭自动 vCard/公钥附件，只添加参数指定的已校验快照；发件 From、身份、主题、正文、附件元数据和字节哈希在发送前核对。原邮件 MIME 内容/位置、身份与收件范围在准备后及 `onBeforeSend` 再次核对，检测到变化就取消。此防护不隔离同一系统用户或其他扩展的恶意操作，也不是多方审批系统。

原邮件、模式、身份 ID、发件地址、To/Cc/Bcc、主题、正文及附件摘要均绑定同一幂等键。`reply_email` 共享既有持久日志、领取与 unknown 恢复机制，未知结果不能换 key 重发。没有回复草稿接口；`create_draft` 继续创建独立新邮件草稿。

官方依据与限制：Thunderbird [compose API](https://webextension-api.thunderbird.net/en/esr-mv2/compose.html#beginreply-messageid-replytype-details) 支持 `beginReply` 和两种回复模式，并提供只读回复类型/关联原邮件；[messages API](https://webextension-api.thunderbird.net/en/esr-mv2/messages.html#query-queryinfo) 支持账户内 RFC Message-ID 查询，数字 ID 在重启或移动后会变化。原生回复头由 Thunderbird 生成，不通过 `Re:` 主题或伪造自定义头模拟。HTML 会经原生编辑器规范化；回读与输入 DOM 内容不一致时安全失败。本地模拟测试证明请求边界与状态机制，不证明已在真实 Thunderbird 账户中发送或核验最终 MIME 回复头。

Mozilla 官方源码中，[nsMsgCompose.cpp](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/compose/src/nsMsgCompose.cpp) 将原 References 链与原 Message-ID 交给回复字段；[MimeMessage.sys.mjs](https://github.com/mozilla/releases-comm-central/blob/master/mailnews/compose/src/MimeMessage.sys.mjs) 生成 References 和 In-Reply-To。此源码核对说明原生机制，不代替目标 Thunderbird 版本的真实发送验收。`beginReply` 原生 API 会创建写信窗口；本接口不依靠 UI 自动化，也不承诺无窗口运行。

## 原生转发边界

`forward_email` 与回复使用相同的 RFC Message-ID、来源账户及发件身份选择规则，但只支持 `forward_attachment`。扩展通过 `messages.getRaw(messageId, {data_format: "File"})` 冻结来源 fingerprint，再调用 Thunderbird 官方 `compose.beginForward(messageId, "forwardAsAttachment", details)` 创建原生转发。发送路径保留 Thunderbird 生成的原生 `.eml`，不删除、重附或用 `compose.getAttachmentFile` 读取它；准备和发送前要求来源 fingerprint 稳定，原生附件恰好一个且 attachment ID 不变、扩展名为 `.eml`、metadata size 等于来源 raw size，固定 MIME 分类可接受。调用方新增附件按实际 attachment ID 逐字节校验，不假设 ID 连续。

发送前及 `onBeforeSend` 会重新核对原邮件、来源 fingerprint、原生转发上下文、身份、收件人、主题、精确正文和附件 manifest。任何来源变化、原生附件 metadata 变化或调用方附件字节变化都取消发送。公开 compose API 无法可靠读取 Thunderbird 原生 `.eml` 的字节，因此 metadata 校验不能证明其逐字节内容；最终 `.eml` 封装对 Thunderbird 原生 `forwardAsAttachment` 实现保留有限信任。当前没有转发草稿接口，也不支持内联转发。

官方依据：Thunderbird [compose API](https://webextension-api.thunderbird.net/en/esr-mv2/compose.html#beginforward-messageid-forwardtype-details) 定义 `beginForward(messageId, forwardType, details)` 与 `forwardAsAttachment`；[messages API](https://webextension-api.thunderbird.net/en/esr-mv2/messages.html#getraw-message-options) 推荐 `File` 格式读取原始邮件。离线模拟测试验证边界和防护，不证明目标 Thunderbird 版本的实际 `.eml` 命名、最终 MIME 或投递行为，部署和真实测试仍需单独授权。

## 查询完整性与附件

推荐调用顺序：`list_mail_folders` → `query_email` → 保持查询参数并跟随 `next_cursor` 至 null → `read_emails` → 按附件 ID 分段 `read_attachment`。

`coverage.local_status=complete` 只证明选定本地 mbox 的匹配记录已枚举；未读正文、未读附件不能视作已经处理。坏日期、发件人等不可索引记录进入 `coverage.gaps`，覆盖仍为 partial。`server_sync_status` 始终为 unknown，不能用文件时间代表 POP 同步完成。

索引仅缓存邮件头和位置。mbox device/inode/size/mtime/ctime 改变会使缓存失效；cursor 绑定查询及快照，locator/cursor 在服务重启或邮箱变化后须重新获取。两套读取器都会跳过 Thunderbird 标记为已删除的记录（`X-Mozilla-Status` 的 `0x0008` 位）。RFC Message-ID 可能为空或重复，不能替代 locator。旧查询接口会跳过坏日期并向 stderr 发出不含邮件正文的警告。

正文优先取纯文本；HTML 读取只做文字转换。引用分离属于启发式，可用 `include_quoted_history=true` 核查，正文/引用的截断标记分别检查。基于 locator 的 `read_emails` / `read_attachment` 路径限制单封邮件为 64 MiB；关键词查询使用同一上限，并将无法读取的候选记入 `coverage.gaps`。旧 `read_email` 没有实现此上限。附件读取不执行文件、不标记邮件、不连接邮件服务器；调用方须合并分段并校验大小与 SHA-256。附加 `.eml` 标为 `serialized_message_rfc822`，是重新序列化后的邮件；multipart MIME 附件标为 `serialized_mime_part`，普通附件标为 `decoded_payload`。

## 草稿、HTML 与发送状态

`body_format` 接受 plain（默认）或 html。HTML 必须是真实 HTML，不自动转换 Markdown；扩展使用 HTML 编辑模式和 `deliveryFormat: "both"`，由 Thunderbird 生成纯文本备用内容。接口不支持独立提交两份正文，也不净化任意 HTML。使用简单 table、内联样式，避免脚本、表单、外部资源与跟踪图片。建议先保存原生草稿检查实际呈现；这是预览建议，不是 `send_email` 的技术前置条件。诊断的 `body_format` 只选择写信窗口模式，不提供自定义正文，也不保存或发送。

若预览后选择发送，须取得发送授权，再以新的幂等键调用 `send_email` 并提供最终正文和附件。该调用创建独立发送请求，不会自动读取、发送或删除先前保存的草稿；目前没有按草稿 ID 发送的工具。

附件参数格式为 `[{"path":"/absolute/file.xlsx","sha256":"<64位SHA-256>"}]`，最多 10 个、合计 20 MiB，只接受绝对路径的普通文件。首次入队核验用户已审阅文件的 SHA-256 并保存不可变快照，扩展再校验字节数及哈希；桥接每次最多传 256 KiB。

每次逻辑发送或草稿使用独立 `idempotency_key`；超时或重试须复用原 key。相同 key 重试使用已保存的附件摘要，不重新读取已删除或变化的原文件；仍须提供相同正文、动作、附件文件名/顺序/预期哈希。不能将同一 key 的 plain 改成 html。单独查询状态无需再次提供正文和附件。

| 状态 | 含义 |
|---|---|
| `pending` | 等待扩展领取；尚未发送或保存草稿 |
| `sending` | 已领取；中断后不能自动重新入队 |
| `sent` | Thunderbird 确认提交至发件服务器，不保证最终送达 |
| `drafted` | Thunderbird 已保存草稿；不是发送授权 |
| `failed` / `expired` | 请求失败，或超过 60 秒仍未被领取而过期 |
| `unknown` | 结果无法确认，须核查，不能换 key 重发；已领取但未记录结果的请求在 300 秒后对外报告为 unknown |
| `not_found` | 没有找到该 key 对应的请求 |

既有发送/草稿请求的 `safe_to_retry` 始终为 false，表示服务不会授权重新投递；复用同一 key 只返回原请求。`copy_status=verified` 表示扩展读到了相同 Message-ID 的发送副本；`not_verified` 不能作为重发理由。Sent/Drafts 位置沿用账户设置，投递与客户端副本保存失败分开报告。

发送队列位于 `~/Library/Application Support/ThunderbirdMailMCP/send.sqlite3`，目录权限 0700、数据库 0600。记录完成结果或清理过期未领取请求时会清除 payload 并释放附件 BLOB；已领取且中断、尚未记录结果的请求保留取证数据。SQLite 删除不保证底层安全擦除；不要删除数据库来重试结果不明的发送。

## 可选写信部署（macOS）

查询功能不需要安装扩展。需要创建原生草稿或发送时，先在目标安装目录完成[README 中的依赖安装](../README.zh-CN.md#1-安装服务)，确保 Thunderbird 153+，然后手动执行：

```bash
chmod 700 native-send-launcher
.venv/bin/python scripts/package_send.py --output dist --install-root "$PWD"
mkdir -p "$HOME/Library/Mozilla/NativeMessagingHosts"
install -m 600 dist/native-host.json "$HOME/Library/Mozilla/NativeMessagingHosts/com.thunderbird_mail_mcp.native_send.json"
```

这些命令会在本机注册 native host；仅在明确选择的安装目录部署。打包本身不启用扩展。在 Thunderbird → 附加组件和主题 → 从文件安装附加组件，选择 `dist/thunderbird-native-send.xpi`，审阅权限后启用。

扩展权限包括 accountsRead、messagesRead、compose、compose.send、compose.save、nativeMessaging、storage。原生主机允许列表仅包含固定扩展 ID `native-send@thunderbird-mail-mcp.local`；同一系统用户下的本地程序仍处于信任边界内。

`native-send-launcher` 使用自身目录下的 `.venv/bin/python`，支持含空格的安装路径。`scripts/deploy_send.py` 的 `--target` 必须与打包时 `--install-root` 一致；`--check` 和实际部署都检查主机路径、名称、stdio 类型和唯一扩展 ID。脚本的参数以 `--help` 为准。该脚本只在已有 Python runtime 的安装目录更新固定文件清单，并非完整的 clone 或依赖安装器。

重新连接所用 MCP 客户端以刷新参数；源码更新不会让已运行进程自动重载。本版本建议使用匹配的 0.12.0 扩展。运行时按扩展公布的特性检查兼容性，不按精确版本号阻断；新源码不能让旧扩展自动获得缺失能力。直接发送还须以 `THUNDERBIRD_MCP_PROFILE=direct_send` 启动服务。`get_send_capabilities().ready` 应为 true，按所需功能检查 `attachments_v1`、`draft_v1`、`html_v1`、`reply_v1`、`forward_v1`、`forward_diagnostic_v1` 和返回的账户/身份信息。发件身份使用返回的实际身份；可按需预览普通草稿，回复和转发直接发送须有用户授权。不得用真实发信作为普通安装自检。

停用自动发送可在 Thunderbird 中停用扩展；未领取的发送/草稿请求在 60 秒后过期，待领取诊断不会自动过期；已领取或提交的邮件不能靠停用撤回。查询和原生 `compose_email` 不依赖扩展。多个本地 MCP 客户端使用同一系统用户时，共用该用户的发送队列与已启用扩展；各客户端须管理自己的调用权限。

## 常见问题

- **找不到 Inbox**：核对 `THUNDERBIRD_INBOX_PATH` 指向真实 mbox 文件，不是账户目录或 Maildir；服务不会自动发现 Thunderbird profile。
- **Operation not permitted**：在 macOS 系统设置 → 隐私与安全性中，为实际启动服务的应用或终端授予所需文件访问权限。
- **客户端只有 URL 输入框**：确认其支持本地 stdio；本项目没有可填写的 HTTP/SSE 地址。
- **扩展离线或能力缺失**：核对 Thunderbird/扩展版本、native host 路径、`.venv/bin/python` 与扩展是否启用。不会通过重装客户端补齐 Thunderbird 能力。
- **升级后工具未变化**：按所用客户端的流程刷新或重新连接 MCP，必要时在新对话中检查；不要仅凭源码版本判断旧进程已更新。
