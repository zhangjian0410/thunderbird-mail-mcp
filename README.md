# Thunderbird Mail MCP

## 0.5.0：HTML 正文

`send_email` 和 `create_draft` 新增 `body_format="plain"|"html"`，默认 plain 保持旧行为及旧幂等摘要。html 时 body 必须是真实 HTML，不会自动转换 Markdown。扩展使用 HTML 编辑模式及 `deliveryFormat: "both"`，Thunderbird 从 HTML 生成纯文本备用内容；不支持独立提供两份可能互相冲突的正文。

先用 create_draft 检查表格、段落、签名及附件，再按既有授权流程发送。纯文本邮件使用分项列表，不把 Markdown 表格当作已排版邮件。HTML 推荐内联样式及简单 table；不要包含脚本、表单、外部资源或跟踪图片。工具不充当任意 HTML 的安全净化器，调用方必须审阅实际 HTML 与渲染结果。

HTML 请求须有扩展 `html_v1` 能力，入队及领取时均检查，旧扩展不会接管 HTML 请求。同一幂等键不能从 plain 改为 html。保存草稿仍绝不发送；发送状态与送达状态仍严格区分。升级不扩大场景白名单或发送权限。

部署时更新 Python 服务及 0.5.0 XPI（权限与 0.4.0 相同），重新连接 MCP 以刷新参数；检查 get_send_capabilities().features 包含 html_v1。源码更新不表示旧 MCP 进程已刷新。无需修改邮箱数据库或删除幂等记录。

本机、仅 stdio 的 Thunderbird 邮件 MCP 服务。查询直接解析 Thunderbird POP 账户的本地 mbox；compose_email 打开原生写信窗口；send_email 通过已启用的 Thunderbird 扩展发送用户明确委托的邮件。服务不删除、移动或直接修改邮箱文件。

## 安装与测试

维护修复包含部署路径校验、含空格路径的原生主机启动、附件幂等重试，以及旧查询接口的坏日期容错。扩展协议与数据库结构保持兼容。

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

本项目固定使用 `mcp>=1,<2`，以使用官方 MCP Python SDK v1 的 `FastMCP` stdio API。

## 连接 Codex

在 `~/.codex/config.toml` 添加：

```toml
[mcp_servers.thunderbird_mail]
command = "/absolute/path/thunderbird-mail-mcp/.venv/bin/python"
args = ["/absolute/path/thunderbird-mail-mcp/server.py"]

[mcp_servers.thunderbird_mail.env]
THUNDERBIRD_INBOX_PATH = "/absolute/path/to/Inbox"
```

服务只通过 stdio 工作，不监听网络端口。

将以上路径替换为实际安装目录和 Thunderbird 的本地 mbox Inbox 文件。也可在启动服务前设置环境变量 `THUNDERBIRD_INBOX_PATH`；支持绝对路径及 `~`。未配置时仅使用 `~/Library/Thunderbird/Inbox` 作为占位路径，不会自动发现其他账号；查询前应显式配置。该服务当前面向 macOS。

旧版 `search_email`、`list_recent_email`、`read_email` 会跳过缺少或无法解析日期的邮件，并通过 stderr 发出不包含邮件内容的警告；返回类型不变。需要完整性核查时使用 `query_email` 的 `coverage.gaps`，不要把旧版列表当作完整覆盖证明。

## 工具

- `search_email(keyword, days=None, sender=None)`：兼容旧调用，在主题、发件人和正文中搜索；关键词必填、发件人子串匹配、无分页。新工作流使用 `query_email`。
- `read_email(message_id)`：读取一封邮件的当前正文和附件元数据，自动省略历史回复引用。
- `list_recent_email(limit=20)`：按日期倒序返回近期邮件，`limit` 为 1 到 100。
- `compose_email(to, subject, body, cc=None, bcc=None)`：通过 Thunderbird 原生 CLI 打开已填写的写信窗口；不会自动发送，用户可在 Thunderbird 中复核后发送或保存草稿。

### 0.2 新增只读接口

| 工具 | 参数与用途 |
|---|---|
| `list_mail_folders()` | 返回显式配置的本地文件夹及可用性；默认只有 Inbox。其他文件夹由服务端 `READER` 映射登记，不接受任意文件路径。 |
| `query_email(keyword="", senders=None, start=None, end=None, folders=None, page_size=50, cursor=None)` | 空关键词按范围枚举；精确邮箱地址列表（大小写不敏感）；带时区的ISO起止时间，`start ≤ date < end`；每页1—200封。 |
| `read_emails(locators, include_quoted_history=False, max_body_chars=30000)` | 一次1—20封，返回逐封成功/错误、当前正文、可选引用历史、截断标记、RFC ID与附件ID/哈希。正文上限1000—100000字符；完整性任务检查截断标记。 |
| `read_attachment(locator, attachment_id, offset=0, max_bytes=262144)` | 返回base64内容、完整附件SHA-256、总长度及`next_offset`；单次最多1 MiB。调用方自行保存到获授权的临时路径，勿直接信任附件文件名。 |

典型顺序：列出文件夹 → 精确发件人和日期枚举 → 使用相同条件跟随`next_cursor`至null → 批量读取相关正文 → 按附件ID分段读取并验证总长度及SHA-256。

分页返回`total_matches`、`has_more`、`coverage`。`coverage.local_status=complete`只证明选定本地mbox的匹配结果已枚举完；未读正文、未读附件的业务抽取不能因此声称完成。坏日期/发件人等无法索引记录会进入`gaps`并保持partial。POP同步状态没有可靠来源，始终返回`server_sync_status=unknown`，不拿文件mtime当同步时间。

索引缓存只保留邮件头和字节位置，不将整份邮箱或附件常驻内存。邮箱device/inode/size/mtime/ctime变化会失效缓存。cursor绑定查询与邮箱快照；locator与cursor只在当前服务进程及邮箱快照内有效，重启/追加/压缩邮箱后需要重新查询。`rfc_message_id`来自实际邮件头，可为空或重复，不能替代唯一locator。

正文优先纯文本，HTML仅做文字转换；中文/英文回复头分离属于启发式，`include_quoted_history=true`可核查被分离部分。正文/引用截断分别标记；正文哈希对应完整已解码文本，而不是截断显示文本。大小超过64 MiB的单封邮件明确报错。附件读取不执行附件、不修改Thunderbird标记，也不连接邮件服务器。附加.eml不并入本次正文；其返回字节按`serialized_message_rfc822`标明为解析后重新序列化的邮件，不冒充原始封装字节。普通附件标为`decoded_payload`。

当前版本新启动的 stdio 服务提供 12 个工具；已运行的客户端需要重新连接MCP以刷新工具列表，不能仅凭源文件已更新宣称旧进程已重载。

## 写信安全边界

- MCP 不读取或保存邮箱用户名、密码，也不直接连接 SMTP、POP 或 IMAP。
- MCP 不直接写入 Drafts、Sent 或其他 Thunderbird mbox 文件。
- `compose_email` 只打开 Thunderbird 写信窗口；工具返回成功不代表邮件已发送。
- 实际发送、账户认证和 Sent 归档由 Thunderbird 完成。send_email 可自动发送；compose_email 仍仅打开窗口。
- 当前固定使用 `/Applications/Thunderbird.app/Contents/MacOS/thunderbird`。

## 0.3 自动发送

需要 Thunderbird 153+、本地 Native Send 扩展和配套 native host。使用 compose.beginNew + compose.sendMessage 原生API自动撰写和发送；不依赖Computer Use点击发送。扩展使用 compose.send 权限。

| 工具 | 行为 |
|---|---|
| get_send_capabilities() | 查看扩展在线状态和实际发件身份；不发送邮件。 |
| send_email(to, subject, body, from_email, idempotency_key, cc=None, bcc=None) | 受理发送请求。收件人是纯邮箱地址数组，正文支持 plain/html，from_email 必须匹配唯一的现有身份。返回 pending 不等于已发送。 |
| get_send_status(idempotency_key) | 查询同一请求的持久状态、Message-ID、发送副本验证结果。 |

调用约定：仅在用户明确授权收件对象和用途时调用 send_email。每次逻辑发送使用独立 idempotency_key；调用超时或重试必须复用原 key。不得为同一封结果不明的邮件换 key 重发。

状态说明：pending=等待扩展，sending=已领取，sent=Thunderbird 确认提交至发件服务器，failed=发送前检查失败，expired=60 秒内未被领取已过期，unknown=无法确认投递。sent 不保证收件人最终收到。claimed 请求永不重新入队，进程中断可能导致邮件没有发出，需要核查而非自动重试。

copy_status=verified 表示扩展读到了相同 Message-ID 的发送副本，copies 返回所在文件夹。not_verified 表示未核实到副本，不能因此重发。继承账户 FCC 设置，不强制修改用户归档配置。发送副本位置继承各账号自己的 FCC 配置；不读取邮箱密码。客户端副本保存失败与邮件投递失败分开报告。

本地队列：`~/Library/Application Support/ThunderbirdMailMCP/send.sqlite3`，目录0700、数据库0600。持久记录用于去重；正常完成/过期后清除队列中的正文，只保留摘要和状态。扩展仅保留未确认结果，不保存正文。程序不开放网络端口。native host 的允许列表只包含 `native-send@thunderbird-mail-mcp.local`；所有同用户权限的本地程序仍应视为可信边界内。

安装：

在源码根目录创建 `.venv` 并安装依赖后：

```bash
chmod 700 native-send-launcher
.venv/bin/python scripts/package_send.py --output dist --install-root "$PWD"
mkdir -p "$HOME/Library/Mozilla/NativeMessagingHosts"
install -m 600 dist/native-host.json "$HOME/Library/Mozilla/NativeMessagingHosts/com.thunderbird_mail_mcp.native_send.json"
```

`native-send-launcher` 从自身所在目录使用 `.venv/bin/python`，支持安装路径含空格。
此步骤只打包和注册主机；仍需在 Thunderbird 手动安装并启用 XPI。
离线测试使用临时邮箱与模拟发送接口，不发送真实邮件。

使用 `scripts/deploy_send.py` 时，打包的 `--install-root` 必须与部署的 `--target` 指向同一目录；`--check` 和实际部署都会检查主机路径、名称、stdio 类型及唯一允许的扩展 ID。部署保留同一份可移植 launcher，不生成包含安装路径的 Python shebang。

生成的 `native-host.json`、`com.thunderbird_mail_mcp.native_send.json`、`rollback.json` 与 XPI 均不应提交；这些名称在 `dist/` 外也已忽略。部署备份放在仓库外或已忽略的 `deployment-backups/`，其中可能包含本机绝对路径及原始配置。

1. 使用 `scripts/package_send.py --output <产物目录> --install-root /absolute/path/thunderbird-mail-mcp` 生成 XPI 和原生主机清单。
2. 部署 Python 文件及 native-send-launcher，在 `~/Library/Mozilla/NativeMessagingHosts/com.thunderbird_mail_mcp.native_send.json` 注册主机。
3. Thunderbird → 附加组件和主题 → 齿轮菜单 → 从文件安装附加组件，选择 XPI 并确认列出的发送、读取邮件和本地桥接权限。启用后每2秒与 native host 通信。程序不绕过附加组件权限提示。
4. 在 Codex 重新连接 MCP 使新工具可见。旧 MCP 进程不会自动刷新工具列表。
5. 先检查 get_send_capabilities().ready；经用户指定测试收件人后再发测试邮件，验证 Message-ID、copy_status 和本地 Sent 中对应记录。

停用自动发送：在 Thunderbird 停用该扩展。未领取的请求最多60秒过期，已经领取/提交的发送不能靠停用撤回。保留去重数据库，切勿通过删除数据库“重试”结果不明的邮件。查询和 compose_email 不依赖扩展。

## 权限排障

如果出现 `Operation not permitted`，在 macOS「系统设置 → 隐私与安全性 → 文件与文件夹」中为 Codex 或所用终端授予访问 Thunderbird 文件夹的权限。邮箱路径为：

```text
/absolute/path/to/Thunderbird/Profiles/<profile>/Mail/<account>/Inbox
```

# 0.4.0：附件与原生草稿

`send_email` 新增可选 `attachments`：`[{"path":"/absolute/file.xlsx","sha256":"<64位SHA-256>"}]`。
创建新请求时，必须先审阅附件内容并计算预期哈希；实际内容与预期哈希不符会拒绝请求。最多10个文件、合计20 MiB（二进制总量；邮件服务自身限制仍适用）。仅接受普通文件，不接受文件符号链接或相对路径。

已有幂等键的重试使用已保存的附件摘要和请求状态，不重新读取原文件，也不覆盖快照；原文件已删除或变化不会导致重复发送。重试仍须提供原正文、动作、附件文件名、顺序及预期 SHA-256，任何变化都会拒绝。仍可用 `get_send_status` 单独查询结果；结果不明时不要换键重发。

`create_draft` 使用与 `send_email` 相同参数，保存到 Thunderbird 账号配置的草稿文件夹，绝不调用发送。返回 pending 后用 `get_send_status` 查询，只有 drafted 才表示已保存，drafts 给出邮件ID。含附件的草稿也不是发信授权。现有 `compose_email` 保持原有打开写信窗口的行为；带附件请使用 `create_draft`。

准备或发送请求把已核验附件做不可变快照，与请求一并写入权限受限的SQLite事务。桥接每次最多传256 KiB；扩展再次校验字节数和SHA-256，挂好附件并核对列表后才保存/发送。完成或未领取超时会释放附件BLOB；异常中断的sending请求保留取证数据，须先查清结果，不能换键重发。SQLite删除不承诺底层存储的安全擦除。

需要更新 Thunderbird 扩展至0.4.0（新增compose.save权限），以及重新连接 Codex MCP。`get_send_capabilities().features` 必须含 `attachments_v1` / `draft_v1`。旧扩展会拒绝新请求；能力检查绑定实际领取请求的连接，防止新旧连接交错时漏附件或把草稿发送。

附件免费发送测试未自动运行。离线测试覆盖不可变快照、哈希错误、20MiB/10文件限制、空文件、断线幂等、旧连接能力与草稿不发送。真实草稿验证不等同于真实SMTP附件发送验证。

信息收集可采用任务级有限委托授权，但接口本身不解析自然语言授权。调用方须保存已批准名单、模板、期限、催办次数与最终提交权限；原则同意自动化不构成本次业务发信许可。
