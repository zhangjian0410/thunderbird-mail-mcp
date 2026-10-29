# 版本变更

[English](CHANGELOG.md) | **简体中文** · [工程介绍](README.zh-CN.md)

公开源码历史从 [0.5.0](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/272e1702e30f900a2761457e7b869fbd02cad5f8) 开始，随后升级至 0.11.0 和 0.12.0。更早的里程碑沿用导入的项目记录；0.6.0、0.8.0、0.9.0 和 0.10.0 的说明随 0.11.0 源码一起公开，并非各自独立的公开版本提交。本文不据此推定单独的发布日期或标签。

## 文档维护（0.12.0 不变）

- README 改为英文主版并保留完整中文版，增加语言导航。见 [README 更新](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/d5aa5329d1185d5ac4dc6ae8ad2fc5c6fa7ee6a1)。
- 工具参考和开发文档增加英文主版及完整中文版。按实现澄清心跳就绪、状态清理、诊断窗口关闭、原生 `.eml` 验证限制，以及部署和测试范围。见[详细文档更新](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/36696370d6fa95c43d68a103a108e53f5f46813e)。
- 增加双语工具目录与注册签名、默认值、最低档位的一致性检查；部署文件清单及导航检查覆盖双语文档和通用 MCP 配置示例。
- CHANGELOG 增加英文主版及中文辅版，同步导航和部署覆盖，并区分历史里程碑与公开源码修订。服务端和扩展仍为 0.12.0。

## 0.12.0 · 服务端能力档位

源码：[能力档位提交](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/ce6c045f2660d9faae5fe3d53d57d760126ff715)。

- 新增严格的 `THUNDERBIRD_MCP_PROFILE=read_only|review|direct_send` 服务端档位；省略时使用 `review`，空值、大小写变体和未知值拒绝启动，不再默认向客户端公布全部工具。
- `read_only` 公布 10 个查询、读取和状态工具；`review` 增加写信窗口、保存草稿和 prepare-only 诊断，共 13 个；只有 `direct_send` 额外公布 `send_email`、`reply_email`、`forward_email`，共 16 个。
- `get_send_capabilities` 返回 `mcp_profile`、`review_enabled` 和 `direct_send_enabled`，便于客户端核对实际运行的服务。
- 通用 stdio 示例和协议测试默认使用 `review`；直接发送的协议测试显式启用 `direct_send`，并验证默认服务拒绝调用隐藏的发送工具。

## 0.11.0 · 原生 `.eml` metadata 验证

公开源码导入：[原生回复与转发](https://github.com/zhangjian0410/thunderbird-mail-mcp/commit/a98b22434ef39fe8988105a9f8d26301aba04306)。该提交同时包含下列更早的回复、转发里程碑。

- 调整发送路径，以处理无法通过 `compose.getAttachmentFile` 回读的原生 `.eml`。保留 `forwardAsAttachment` 生成的继承附件，不删除、重附 raw File，也不声称原生附件字节等价。
- 准备及发送事件内复核来源 raw fingerprint、原生上下文，以及唯一 `.eml` 的扩展名、metadata size 和可接受的 MIME 分类；调用方附件仍保持逐字节 SHA-256 校验。
- 原生附件 ID 纳入内部 manifest；即使 metadata 相同，删除后替换附件仍会取消发送。调用方附件使用实际 ID，不依赖连续编号。
- 公开 API 的 metadata 校验不能证明原生 `.eml` 的逐字节内容；最终封装仍信任 Thunderbird 原生实现。
- Prepare-only 诊断单独公布 `forward_diagnostic_v1`；仅支持 `forward_v1` 的旧扩展不会接收诊断请求。
- 诊断附件分类最多保留 16 项，对计数、结构、大小和整条 JSON 设置上限，并以 `count` / `truncated` 表达省略的分类。

## 0.10.0 · Prepare-only 转发诊断

- 新增 `diagnose_forward_preparation`、`get_forward_diagnostic_status` 和独立诊断队列。执行来源定位、getRaw、原生 forwardAsAttachment、清空继承附件、重新附加 raw 来源并回读；不调用 sendMessage 或保存草稿，并尝试关闭精确 compose tab。
- 结果只包含有界的失败阶段、大小、SHA-256、相等标记、附件数量、扩展名与 MIME 分类，不包含正文、地址、主题、路径或原始字节；诊断队列仍保存请求上下文。诊断与发送恢复隔离。
- 通过 `close_confirmed` 报告窗口关闭结果。关闭失败返回 `close_not_confirmed` 并保留该 tab 的发送阻断 guard，不保证每次都成功关闭窗口。

## 0.9.0 · 原始邮件附件兼容性修复

- 导入的里程碑记录描述了当时的方案：保留原生 `forwardAsAttachment` 上下文，清空继承附件后，附加 `messages.getRaw(..., {data_format: "File"})` 返回的原始 File，并在发送前核对大小和 SHA-256。0.11.0 的发送路径已取代此替换方案。
- 新增有界的 `failure_code`，区分来源定位、raw 读取、原生窗口、上下文、正文、原生附件、raw 不一致、调用方附件和最终 guard；这些代码不暴露邮件正文、附件名称或本地路径。
- 既有 failed/unknown 请求和幂等键语义不变，升级不会使其重新入队或重发。

## 0.8.0 · 原生附件转发

- 新增 `forward_email` / `forward_v1`，以 RFC Message-ID、来源账户及明确身份绑定 `compose.beginForward(..., "forwardAsAttachment")`，不回退为新邮件，也不支持内联转发。
- 导入的设计通过 `messages.getRaw(..., {data_format: "File"})` 取得独立来源，在准备及发送前检查原邮件附件、精确说明正文和调用方附件。原生附件处理在 0.9.0、0.11.0 再次调整，当前保证见 0.11.0。
- 发送前及 `onBeforeSend` 检查原邮件、原生上下文、身份、收件人、主题、最终正文和附件；未知结果不重发。离线检查不代表已部署或真实账户投递成功。

## 0.6.0 · 原生回复与全部回复

- 新增 `reply_email` / `reply_v1`，以 RFC Message-ID、原邮件账户及明确发件身份绑定原生 `beginReply`，支持 `reply_all` / `reply_sender`，不回退为新邮件。
- 回读原生回复上下文、授权收件范围、发件信息、正文和附件，在发送前及发送事件内检查来源变化，保留持久幂等与 unknown 处理。
- capabilities 增加账户 ID 及身份所属账户，旧工具与请求摘要保持兼容。回复需要扩展公布 `reply_v1` 并刷新 MCP 连接；本地验证不代表已部署或真实发送成功。

## 工程维护（0.5.0 之后，版本不变）

以下变更位于[首个 0.5.0 源码与回复/转发导入之间](https://github.com/zhangjian0410/thunderbird-mail-mcp/compare/272e1702e30f900a2761457e7b869fbd02cad5f8...ad7d70f6390effc13bba3a8ee60e50ac030707c9)，期间服务端和扩展版本均保持 0.5.0。

- 公开 Sent 只读查询：默认仅查 Inbox，显式选择已发送副本或合并范围；增加可移植的 Sent 路径配置，不接入待发 Outbox，工具数量仍为 12。
- 围绕工程介绍、安装和通用 stdio 接入重组 README，将工具/部署和开发说明移至 `docs/`；澄清直接发送和保存草稿是独立动作。
- 添加通用客户端配置及真实 MCP stdio 回归测试，区分协议覆盖、GUI 兼容和端到端实测范围。
- 添加 `uv.lock`、锁定构建工具、Linux/macOS CI、当前/历史敏感信息扫描及合成反例。
- 修复部署生成的 native launcher 对含空格路径的支持，按部署目标校验 native host 清单；忽略生成配置、XPI 和部署备份。
- 附件重试使用持久摘要，无需重新打开原文件；旧查询工具跳过无效日期并输出不含邮件正文的警告。
- 添加 MIT 许可证。

## 0.5.0 · HTML 正文

`send_email` 和 `create_draft` 增加 `body_format="plain"|"html"`。plain 默认行为及旧幂等摘要保持兼容；HTML 使用真实标记及 Thunderbird 生成的纯文本备用正文，需要 `html_v1`，扩展权限与 0.4.0 相同。建议通过原生草稿预览，但这不是发送的前置条件。升级后重新连接 MCP 客户端。

## 0.4.0 · 附件与原生草稿

添加校验附件快照，最多 10 个文件、合计 20 MiB。原生草稿保存需要 `draft_v1`，附件需要 `attachments_v1`，扩展增加 `compose.save` 权限。保存草稿不构成发送授权；旧扩展不会领取需要其尚未支持特性的请求。

## 0.3 · Thunderbird 扩展发送

通过 native host 和 Thunderbird 扩展提供发送、持久幂等键、状态查询及发送副本验证。Thunderbird 负责账户认证和 Sent 归档；服务端不直接实现邮件服务器连接。

## 0.2 · 分页只读接口

增加本地文件夹列举、精确发件人/时间范围查询、cursor/locator、批量读取、附件分段和显式 coverage，并保留旧查询接口兼容性。

## 初始功能

本地 mbox 搜索、单封读取、最近邮件列表，以及打开 Thunderbird 写信窗口。

当前使用与限制见[工程介绍](README.zh-CN.md)和[工具参考](docs/reference.zh-CN.md)。
