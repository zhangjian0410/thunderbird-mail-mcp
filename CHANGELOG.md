# 版本变更

## 0.12.0 · 服务端能力档位

- 新增严格的 `THUNDERBIRD_MCP_PROFILE=read_only|review|direct_send` 服务端档位；省略时使用 `review`，未知值拒绝启动，不再把所有工具默认公布给客户端。
- `read_only` 仅公布 10 个查询、读取和状态工具；`review` 在此基础上公布写信窗口、保存草稿和 prepare-only 诊断，共 13 个；`direct_send` 才额外公布 `send_email`、`reply_email`、`forward_email`，共 16 个。
- `get_send_capabilities` 现在返回当前 `mcp_profile`、`review_enabled` 和 `direct_send_enabled`，便于客户端核对实际服务进程，而不是根据配置文件猜测。
- 通用 stdio 示例和测试默认使用 `review`；直接发送的协议测试显式启用 `direct_send`，并验证默认服务不能调用隐藏的发送工具。

## 0.11.0 · 原生 `.eml` metadata 验证

- 真实诊断确认 Thunderbird 的原生 `.eml` 可能无法通过 `compose.getAttachmentFile` 回读。发送路径因此保留 `forwardAsAttachment` 生成的继承附件，不再删除、重附 raw File 或声称原生附件字节等价。
- 准备及发送事件内复核来源 raw fingerprint、原生上下文和唯一 `.eml` 的扩展名、metadata size、固定 MIME 分类；调用方附件仍保持逐字节 SHA-256 校验。
- 原生 `.eml` 的 attachment ID 也纳入内部 manifest；remove+replace 即使 metadata 相同仍会取消。调用方附件使用实际 ID 映射，不依赖连续编号。
- 公开 API 的 metadata 校验不能证明 Thunderbird 原生 `.eml` 的逐字节内容，最终封装依赖 Thunderbird 原生实现。
- Prepare-only 诊断单独公布 `forward_diagnostic_v1`；仅支持早期 `forward_v1` 的旧扩展不会接收无法执行的诊断请求。
- 诊断附件分类最多保留 16 项，并对计数、shape、size 和整条 JSON 设置上限；异常数量以 `count` / `truncated` 表达，不再让结果增长到 native frame 边界。

## 0.10.0 · Prepare-only 转发诊断

- 新增独立 `diagnose_forward_preparation` / `get_forward_diagnostic_status` 工具与诊断队列；真实执行 source lookup、getRaw、原生 forwardAsAttachment、清空继承附件、重新附加和回读，但代码路径不调用 sendMessage 或保存草稿，并关闭精确 compose tab。
- 诊断结果仅保留固定失败阶段、大小、SHA-256、相等布尔值、附件数量、扩展名与 MIME 分类；不保存正文、地址、主题、路径或原始字节，也不进入发送恢复域。

## 0.9.0 · 原始邮件附件兼容性修复

- 保留原生 `forwardAsAttachment` 上下文，但不再信任 Thunderbird 重新序列化后的继承附件：清空全部继承附件后，附加 `messages.getRaw(..., {data_format: "File"})` 返回的原始 File，并在准备及发送前核对大小和 SHA-256。
- 失败结果新增有界、无敏感内容的 `failure_code`，区分来源定位、raw 读取、原生窗口、上下文、正文、原生附件、raw 不一致、调用方附件和最终 guard；不会返回邮件正文、附件名称或本地路径。
- 旧的 failed/unknown 请求及幂等键语义不变，不会因升级重新入队或重发。

## 0.8.0 · 可验证的原生附件转发

- 新增 `forward_email` / `forward_v1`，以 RFC Message-ID、来源账户和明确身份绑定真实 `compose.beginForward(..., "forwardAsAttachment")`；不使用新邮件模拟，也不支持无法完整校验的内联转发。
- 转发前通过 `messages.getRaw(..., {data_format: "File"})` 取得独立原始字节证据；原邮件 `.eml` 附件、精确说明正文及调用方附件在准备和发送前均重新校验。
- 发送前及 `onBeforeSend` 复核原邮件、原生上下文、身份、收件人、主题、最终正文和全部附件；未知结果不重发。本地离线验证不代表扩展已部署或真实转发已验收。

## 0.6.0 · 原生回复与全部回复

- 新增 `reply_email` / `reply_v1`，以 RFC Message-ID、原邮件账户及明确发件身份绑定真实 `beginReply`，支持 `reply_all` / `reply_sender`；不回退新邮件。
- 回读原生回复上下文、授权收件范围、发件信息、正文和附件，发送前及发送事件内检查源变化；继承持久幂等与 unknown 不重发。
- capabilities 增加账户 ID 及身份所属账户，旧工具与旧摘要保持兼容。需要加载 0.6.0 扩展并重新连接 MCP；本地验证不代表生产已更新或真实发送验收。

## 工程维护（0.5.0 之后，运行接口版本不变）

- 同步本地已实现的 Sent 只读查询：默认仅查 Inbox，显式选择已发送副本或合并范围；支持可移植的 Sent 路径配置，不接入待发 Outbox，工具数量仍为 12。
- 以工程介绍、安装和通用 stdio 接入重写 README；将工具/部署和开发说明移至 `docs/`。
- 添加通用客户端配置及真实 MCP stdio 回归测试，区分协议兼容、官方客户端支持与端到端实测范围。
- 添加 `uv.lock`、锁定构建工具、Linux/macOS CI、当前/历史敏感信息扫描及合成反例。
- 修复含空格路径的原生主机启动与部署清单校验；忽略生成配置、XPI 和部署备份。
- 附件重试沿用持久摘要，无需重新打开原文件；旧查询接口容忍无法解析的日期并输出不含邮件正文的警告。

## 0.5.0 · HTML 正文

`send_email` 和 `create_draft` 增加 `body_format="plain"|"html"`。plain 默认行为及旧幂等摘要保持兼容；HTML 使用真实 HTML 与 Thunderbird 生成的纯文本备用正文，需要 `html_v1`。扩展权限与 0.4.0 相同。先检查原生草稿，升级后重新连接所用 MCP 客户端。

## 0.4.0 · 附件与原生草稿

添加最多 10 个、合计 20 MiB 的校验附件快照；通过原生草稿 API 保存草稿。需要 `attachments_v1` / `draft_v1`，扩展新增 `compose.save` 权限。草稿保存与发送授权分开，旧扩展不会接管不支持的新请求。

## 0.3 · Thunderbird 扩展发送

通过 native host 和 Thunderbird 扩展提供自动发送、持久幂等键、状态查询与发送副本验证。认证和 Sent 归档沿用 Thunderbird 账户配置，不直接实现邮件服务器连接。

## 0.2 · 分页只读接口

增加本地文件夹列举、精确发件人/时间范围查询、cursor/locator、批量读取、附件分段及显式 coverage；保留旧查询接口兼容性。

## 初始功能

本地 mbox 搜索、单封读取、最近邮件列表，以及打开 Thunderbird 写信窗口。

当前使用与限制见[中文工程介绍](README.zh-CN.md)、[English overview](README.md)和[行为参考](docs/reference.md)。
