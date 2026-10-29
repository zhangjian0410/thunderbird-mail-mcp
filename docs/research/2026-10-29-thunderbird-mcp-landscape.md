# GitHub 上 Thunderbird MCP 项目差异调研

日期：2026-10-29
对照项目：[`zhangjian0410/thunderbird-mail-mcp`](https://github.com/zhangjian0410/thunderbird-mail-mcp)，公开基线 `a98b224`（0.11.0）

> Historical comparison against 0.11.0, not the current capability catalog. Version 0.12.0 added server profiles, and later documentation updates added English primary pages with Chinese companions. Recommendations below retain their original context; see the [current reference](../reference.md) and [changelog](../../CHANGELOG.md).
> 本文保留 0.11.0 时的对比快照；0.12.0 已增加服务端能力档位，后续文档已改为英文主版、中文辅版。下文建议保留原调研语境，当前能力以[工具参考](../reference.zh-CN.md)及[版本变更](../../CHANGELOG.zh-CN.md)为准。

## 结论先行

GitHub 上目前可见的 Thunderbird MCP 形成了四条技术路线：

1. **Thunderbird 扩展内原生操作**：TKasperczyk、thunderbird-cli、U-C4N、Commonpost、Zileo、tears-mysthrala、ThunderSend，以及本项目。它们都把 Thunderbird 当执行主体，但桥接方式、安全默认值和权限宽度差异很大。
2. **直接读取 Thunderbird 本地数据**：agimenezdev 只读 GLODA；本项目只读显式 Inbox/Sent mbox。前者搜索面广，后者不依赖索引完整性且能按原始 mbox 读取附件。
3. **读取 Thunderbird profile 后直连 IMAP/SMTP**：localai-org 无扩展、可在 Thunderbird 关闭时运行，但需要读取并解密 Thunderbird 保存的凭据，发送也不走 Thunderbird 原生 compose 流程。
4. **通用 IMAP/SMTP 邮件 MCP**：mario-hernandez/mail-mcp 不是 Thunderbird 专属，但其服务端写权限门禁、内容不可信封装、稳定错误码和速率限制值得借鉴。

本项目最鲜明的定位不是“全功能 Thunderbird 自动化”，而是：**不读取凭据、不直连 IMAP/SMTP，以较小工具面完成本地邮件读取和 Thunderbird 原生发送，并对重复发送、回复来源、收件人、发件身份、转发原始邮件及附件完整性作强绑定。** 在本次样本中，持久幂等状态机、`unknown` 防重复语义，以及 prepare-only 原生转发诊断是最有辨识度的能力。[本项目工具清单](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/reference.md#L5-L24)和[执行路径](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/reference.md#L36-L49)对此已有准确说明。

最需要补的不是日历或联系人，而是三个基础面：

- **服务端安全默认值**：当前 16 个工具始终公布，服务端不校验人工确认令牌；这一点弱于主要直接竞品。
- **真实 Thunderbird 端到端证据**：现有自动测试验证协议、队列和模拟扩展逻辑，但没有验证真实 Thunderbird 最终写出的草稿、回复/转发 MIME 与投递结果。
- **发布与部署体验**：当前写信部署面向 macOS、安装较手工，且没有 GitHub Release；头部项目已经提供签名扩展、npm/一键 bootstrap、跨平台安装或配套 Release。

## 样本与活跃度

Star、Fork 和最近活动日期来自 2026-10-29 的 GitHub REST API 快照；表内按措辞区分 commit 与 push。它们只是关注度/活跃度指标，不等于质量。功能与安全结论来自各仓库 README、架构文档和源码，未在本机重新执行对方测试。

| 项目 | GitHub 状态 | 架构与工具面 | 写入/发送安全默认值 | 相对定位 |
|---|---|---|---|---|
| **本项目** | [0 Star / 0 Fork，2026-10-29 push](https://api.github.com/repos/zhangjian0410/thunderbird-mail-mcp)；无 Release；MIT | Python stdio；显式 Inbox/Sent mbox 只读；Native Messaging 扩展负责草稿、发送、原生回复/附件转发；16 工具 | 工具描述要求授权，但服务端没有只读模式、发送开关或人工确认令牌；调用端负责审批 | 工具面适中，发送事务完整性最突出；部署、审批和实机证据偏弱 |
| [`TKasperczyk/thunderbird-mcp`](https://github.com/TKasperczyk/thunderbird-mcp) | [407 / 116，2026-10-23 push](https://api.github.com/repos/TKasperczyk/thunderbird-mcp)；[v0.10.0](https://github.com/TKasperczyk/thunderbird-mcp/releases/tag/v0.10.0)；MIT | Node stdio bridge → token 化 localhost HTTP → Thunderbird 扩展；49 工具，覆盖邮件、文件夹、过滤器、联系人、日历 | 默认阻止 `skipReview`；发送/回复/转发先开审阅窗口，用户显式关闭设置后才允许直发；有 Tool Access、加密邮件和附件路径限制 | 最大社区和功能成熟度基准；覆盖广，但权限面与复杂度更大 |
| [`vitalio-sh/thunderbird-cli`](https://github.com/vitalio-sh/thunderbird-cli) | [65 / 14，最近提交 2026-09-14](https://api.github.com/repos/vitalio-sh/thunderbird-cli)；[v1.1.0](https://github.com/vitalio-sh/thunderbird-cli/releases/tag/v1.1.0)；MIT | 扩展 → WebSocket/HTTP bridge → CLI/MCP；38 CLI 命令、12 个精选 MCP 工具；多账户 | compose/reply/forward 默认存草稿，显式 `mode="send"` 才发送；代码实现可选 bearer token 及 Host/Origin/WebSocket 防护；安全文档另描述只读、审计、限流和信任标记，但本次源码抽查未确认这些后者已落地 | **与本项目产品形态最接近的直接竞品**：同样无凭据、工具面克制，覆盖和安装更成熟；部分安全宣称仍应按设计文档看待 |
| [`U-C4N/Thunderbird-MCP`](https://github.com/U-C4N/Thunderbird-MCP) | [5 / 8，2026-09-08 push](https://api.github.com/repos/U-C4N/Thunderbird-MCP)；[v1.3.0](https://github.com/U-C4N/Thunderbird-MCP/releases/tag/v1.3.0)；MIT | Python stdio → daemon → WebSocket → MailExtension + 高权限 Experiment API；112 工具、10 个 toolset | 发送/删除/配置要求 `confirm=true`；支持 `dry_run_only`；`--read-only` 不注册写工具；`mail_send` 默认先存可审阅草稿 | 功能最宽、诊断/安装体验好；高权限 Experiment 与 112 工具增加攻击面和维护成本 |
| [`commonpost/thunderbird-mcp`](https://github.com/commonpost/thunderbird-mcp) | [2 / 2，2026-10-26 push](https://api.github.com/repos/commonpost/thunderbird-mcp)；[v0.17.3](https://github.com/commonpost/thunderbird-mcp/releases/tag/v0.17.3)；MIT（另含一个 MPL-2.0 衍生文件） | 从 TKasperczyk 0.7.5 延续的社区分支；同类 localhost bridge；40 工具 | 默认任何发送/事件创建都需用户审阅；工具和账户可在扩展设置中限制 | 与 TK 属同一代码家族；真正值得借鉴的是发布供应链和真实 Thunderbird 离线 E2E lab |
| [`localai-org/thunderbird-mcp`](https://github.com/localai-org/thunderbird-mcp) | [6 / 3，2026-10-27 push](https://api.github.com/repos/localai-org/thunderbird-mcp)；[v0.3.2](https://github.com/localai-org/thunderbird-mcp/releases/tag/v0.3.2)；MIT | 静态 Go 二进制；直接读 profile/GLODA/联系人/日历 SQLite，解密 `key4.db`/`logins.json`；IMAP/SMTP 做实时读写；3 个 MCP 工具、17 个 action | 默认不开放 send action；`THUNDERBIRD_ALLOW_SEND=true` 才出现，`THUNDERBIRD_READ_ONLY=true` 去掉全部写 action | 无扩展、易部署、Thunderbird 可关闭；但进入凭据与网络协议边界，不符合本项目核心定位 |
| [`assistance-micro-design/zileo-mcp-thunderbird`](https://github.com/assistance-micro-design/zileo-mcp-thunderbird) | [1 / 0，最近提交 2026-06-11](https://api.github.com/repos/assistance-micro-design/zileo-mcp-thunderbird)；[v1.5.1](https://github.com/assistance-micro-design/zileo-mcp-thunderbird/releases/tag/v1.5.1)；Apache-2.0 | TypeScript MCP → localhost WebSocket → MV3 扩展/Experiment；56 工具，另有 MCP resources | read/modify 默认开启，8 个 delete/send destructive 工具默认关闭；扩展设置可切换 Read Only / Read + Modify / Enable All | 广覆盖 beta；权限 tier 值得参考，但默认开放 modify 的风险高于 draft-first 路线 |
| [`agimenezdev/thunderbird-mcp`](https://github.com/agimenezdev/thunderbird-mcp) | [0 / 2，2026-06-17 push](https://api.github.com/repos/agimenezdev/thunderbird-mcp)；无 Release；MIT | Python FastMCP；原子快照 `global-messages-db.sqlite`，LIKE 查询 GLODA 预计算字段；7 个只读工具 | 物理上无写/发信代码，也不读取凭据 | 最小只读搜索基准；全历史/全账户搜索优于本项目，但依赖 GLODA 新鲜度，只返回附件名称 |
| [`tears-mysthrala/thunderbird-local-mcp`](https://github.com/tears-mysthrala/thunderbird-local-mcp) | [0 / 0，2026-10-05 push](https://api.github.com/repos/tears-mysthrala/thunderbird-local-mcp)；无 Release；未声明许可证 | Windows、MV3、Native Messaging、named pipe、Node stdio；24 工具 | 完全无 send 权限；草稿可保存，其他写操作必须在独立终端核对精确计划并一次性批准，MCP 没有批准工具 | 安全隔离思路最强；平台窄、能力早期、无发信，但审批模式值得吸收 |
| [`emercons/thundersend-mcp`](https://github.com/emercons/thundersend-mcp) | [0 / 0，2026-10-07 push](https://api.github.com/repos/emercons/thundersend-mcp)；无 Release；MIT | 从 TKasperczyk v0.9.0 裁剪；仅账户/访问查询、草稿、发信 4 工具 | 默认只能打开 compose 窗口人工发送；bridge 和扩展双重硬编码 allowlist；需显式关闭设置才可直发 | 证明“删除不必要代码”本身可形成清晰产品；没有读、回复、转发 |

历史源头 [`bb1/thunderbird-mcp`](https://github.com/bb1/thunderbird-mcp) 明确标记为不再维护并引导用户转向 TKasperczyk；它只有搜索、发送、日历、联系人 4 个工具，不应再作为当前实现基准。[README 原文](https://github.com/bb1/thunderbird-mcp/blob/9e93dd160addb593165ae9857ae8a461af143eff/README.md#L2-L13)及[工具清单](https://github.com/bb1/thunderbird-mcp/blob/9e93dd160addb593165ae9857ae8a461af143eff/README.md#L32-L50)

## 逐项差异

### 1. 产品边界：本项目位于“只读”与“全能”之间

本项目的 16 工具能查 Inbox/Sent、读正文和附件、打开 compose、存草稿、直发、原生回复和附件转发，但不提供邮件移动/删除/标记、文件夹管理、联系人、日历、过滤器或 Thunderbird 配置。[公开 README](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/README.md#L10-L26)

- 与 7 工具只读 GLODA 项目相比，本项目多了可验证附件读取和完整写信链；agimenez 明确不发送、不修改、不返回附件二进制。[来源](https://github.com/agimenezdev/thunderbird-mcp/blob/a24e60960cf6642da8da7ed056b52c0d527b968b/README.md#L95-L103)
- 与 4 工具 ThunderSend 相比，本项目形成“检索 → 读取 → 授权后回复/转发”闭环；ThunderSend 有意从代码删除读取、移动、回复、转发等能力。[来源](https://github.com/emercons/thundersend-mcp/blob/338e3764a6a193d19752eb1b6999620aa638d5e4/README.md#L3-L19)
- 与 49/40/56/112 工具的全能项目相比，本项目上下文成本、权限面和维护面更小。U-C4N 用 toolset 缓解 112 工具的上下文开销。[来源](https://github.com/U-C4N/Thunderbird-MCP/blob/5f774a0d3bf3a0172d4e95c3b8d2a3a11896af4d/README.md#L76-L89)
- thunderbird-cli 的 12 MCP 工具是更直接的产品基准：跨账户搜索、线程、草稿优先 compose/reply/forward、归档/移动和附件均在一个精选工具面内，另把长尾能力放在 38 个 CLI 命令中。[工具清单](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/mcp/README.md#L12-L31)

判断：**暂不追求联系人、日历、过滤器和 100+ 工具是合理取舍。** 更值得扩展的是邮件主链直接相关的全文件夹发现、线程检索、回复/转发草稿与人工审阅。

### 2. 读取路径：本项目更可控，但覆盖面窄

本项目读取显式配置的 Inbox/Sent mbox，不连接服务器、不标记已读，并报告本地覆盖与 `server_sync_status=unknown`。优势是没有凭据、没有 GLODA 索引陈旧问题，附件可按块返回并校验 SHA-256；不足是只覆盖两个显式文件，不自动发现账户和所有文件夹。[配置与覆盖边界](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/reference.md#L28-L34)

其他路线：

- agimenez 对 GLODA 做只读原子快照，统一搜索所有账户、归档和本地文件夹，但正文和附件信息受索引内容与新鲜度限制。[架构](https://github.com/agimenezdev/thunderbird-mcp/blob/a24e60960cf6642da8da7ed056b52c0d527b968b/README.md#L73-L103)
- TK/Commonpost/thunderbird-cli 通过正在运行的 Thunderbird 读账户、文件夹和消息，可覆盖多账户、线程和更多 provider，但必须保持扩展与 bridge 正确配对。[TK 架构](https://github.com/TKasperczyk/thunderbird-mcp/blob/8910dbf4300a7ea7ebf1edd0bdd0d22996531b88/README.md#L27-L37)；[thunderbird-cli 架构](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/README.md#L115-L141)
- localai-org 读 profile 数据库，并解密 Thunderbird NSS 凭据后走 IMAP/SMTP；覆盖与部署灵活性最高，但进入凭据处理和外部网络信任边界。[来源](https://github.com/localai-org/thunderbird-mcp/blob/e83ab752ecd6a9921734bb9969652740256270d8/README.md#L12-L44)

判断：优先通过**扩展或 profile 元数据做账户/文件夹发现**，不要自行解密凭据或转向 IMAP/SMTP；这样能扩大覆盖，同时保留现有隐私边界。

### 3. 回复/转发：完整性约束强，但没有审阅型工作流

本项目回复在指定账户内唯一定位 RFC Message-ID，校验 Thunderbird 原生计算的 To/Cc/Bcc 与显式授权范围完全一致，再绑定身份、正文、主题和附件；失配即停止，不回退成普通新邮件。[回复边界](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/reference.md#L51-L59)

附件转发还冻结来源 raw fingerprint，要求唯一原生 `.eml` 附件、稳定 attachment ID/metadata，并在发送前和 `onBeforeSend` 重验；文档也说明公开 API 无法证明原生 `.eml` 最终字节完全等同。[转发边界](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/reference.md#L65-L71)

这比多数项目单纯调用 `beginReply`/`beginForward` 更强调“授权对象与最终发送内容不可漂移”。但 `reply_email` / `forward_email` 只有直接发送，没有回复草稿、转发草稿或审阅窗口模式：

- TK 默认打开审阅窗口，回复还能 `saveAsDraft`。[来源](https://github.com/TKasperczyk/thunderbird-mcp/blob/8910dbf4300a7ea7ebf1edd0bdd0d22996531b88/README.md#L128-L152)
- Commonpost 提供 `window`、`draft`、`send` 三种 mode。[来源](https://github.com/commonpost/thunderbird-mcp/blob/4ef89f81311f597cdd406f5c2ae660ec1750ffac/README.md#L111-L132)
- thunderbird-cli 的 compose/reply/forward 都默认 draft，显式 `mode="send"` 才直发。[来源](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/mcp/README.md#L14-L31)

判断：最有价值的功能补齐是 **`reply_draft` / `forward_draft` 或 review-window 模式**，并复用现有强绑定；直发作为显式高级模式。

### 4. 发送事务：这是本项目最强的差异点

本项目每次逻辑发送/草稿绑定独立 `idempotency_key`；超时重试必须复用原 key，附件摘要和正文/动作/格式不可漂移。状态明确区分 `pending`、`sending`、`sent`、`drafted`、`failed/expired`、`unknown`，未知结果不得换 key 重发；持久 SQLite 队列保留异常中断取证数据。[幂等与状态](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/reference.md#L83-L104)

抽查的直接竞品普遍有“超时后检查 Sent/Outbox”“draft-first”“发送状态”等安全说明，但没有发现与本项目等价的、由调用者提供并持久绑定完整请求的发送事务键，以及跨进程可查询的 `unknown` 状态机。这个结论限于本报告检查到的公开代码，不能证明所有竞品都不存在内部去重。

这一能力应作为 README 首屏和英文介绍的核心卖点，而不是埋在参考文档里。

### 5. 安全默认值：这是相对最明显的短板

本项目文档明确写出：16 个工具始终公布，没有服务端只读开关；发送授权由调用方管理，服务端不检查逐封人工审批记录或确认令牌。[公开边界](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/README.md#L145-L149)

对照：

- TK 默认阻止 `skipReview`；即便允许直发，也会对加密策略、原邮件分类、收件人数和估算大小继续 fail closed。[默认审阅](https://github.com/TKasperczyk/thunderbird-mcp/blob/8910dbf4300a7ea7ebf1edd0bdd0d22996531b88/README.md#L128-L148)及[附加门禁](https://github.com/TKasperczyk/thunderbird-mcp/blob/8910dbf4300a7ea7ebf1edd0bdd0d22996531b88/README.md#L291-L306)
- U-C4N 的危险操作要求 `confirm=true`，支持 `dry_run_only`，并能用 `--read-only` 让写工具不注册。[来源](https://github.com/U-C4N/Thunderbird-MCP/blob/5f774a0d3bf3a0172d4e95c3b8d2a3a11896af4d/README.md#L67-L74)
- thunderbird-cli 的代码和测试能确认可选 `TB_AUTH_TOKEN`、Host/Origin/CORS 与 WebSocket 来源防护。[bridge 实现](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/bridge/bridge.js#L14-L20)及[安全回归测试](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/test/bridge-security.mjs#L109-L169)；其 `SECURITY.md` 还描述只读模式、写审计、速率限制和 trusted/untrusted 标记，但本次在该提交的运行时代码中未确认对应实现，因此只把它们视作**文档化设计**，不作为已交付能力。[设计文档](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/SECURITY.md#L99-L138)
- Zileo 把 56 工具分 read/modify/destructive 三层，delete/send 默认关闭，设置页可切换整组权限。[来源](https://github.com/assistance-micro-design/zileo-mcp-thunderbird/blob/cdbe6005318510413b8dede306e4b1f388339c5e/README.md#L480-L508)
- tears-mysthrala 不提供发送；除草稿外的写操作必须在独立终端显示精确计划、输入与 ID/hash 绑定的短时一次性批准，MCP 本身没有批准能力。[来源](https://github.com/tears-mysthrala/thunderbird-local-mcp/blob/ec8f0d97c5181d47f915dc2f2a9a557c598a680f/README.md#L25-L49)
- 通用 mail-mcp 在未设置环境开关时不注册破坏性工具，发送还需要两个开关和 `confirm=true`；邮件正文包入不可信边界并中和闭合标签/零宽字符。[来源](https://github.com/mario-hernandez/mail-mcp/blob/638fc5248aca307a5032ff1ca594eaf6b185b766/README.md#L24-L36)及[工具门禁](https://github.com/mario-hernandez/mail-mcp/blob/638fc5248aca307a5032ff1ca594eaf6b185b766/README.md#L73-L81)

本项目已有很强的**内容完整性和重复发送防护**，但这不能替代**授权门禁**。推荐分三层：

1. 默认 `read_only`：只注册查询/读取/状态工具。
2. `review`：额外注册 compose、草稿、回复/转发草稿或审阅窗口；仍不允许后台直发。
3. `direct_send`：部署时显式开启；每次发送再要求 `confirm=true` 或与幂等键/收件人/正文摘要绑定的一次性 approval token。

这属于基于对比证据的建议，不是现有代码能力。

### 6. 可靠性：离线验证扎实，实机验证落后

本项目 CI 覆盖 Python 3.10/3.11、Node、扩展打包、完整 Git 历史和敏感信息扫描；协议测试会启动真实 MCP 子进程并核对 16 工具、查询、附件和 mbox 不变。[开发文档](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/docs/development.md#L23-L37)

但测试使用临时邮箱和模拟发送接口，不部署扩展、不访问真实邮箱、不验证真实 Thunderbird 发送。回复/转发的最终 MIME、窗口绑定和 provider 行为仍是未知项。

thunderbird-cli 自述有 80 项测试，其中 46 项覆盖 CLI/bridge、34 项为基于 mock bridge 的 MCP 集成测试；这证明其协议层回归面较宽，但同样不能替代真实 Thunderbird 实机证据。[测试说明](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/README.md#L28-L30)及[MCP 测试说明](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/mcp/README.md#L210-L218)

值得直接借鉴的是 Commonpost 的独立 [`thunderbird-mcp-lab`](https://github.com/commonpost/thunderbird-mcp-lab)：它在无网络、只读、无 capability 的容器里启动真实 Thunderbird、真实扩展和真实 bridge，检查 mbox 草稿、回复线程头、附件字节、默认禁止直发和账户/工具限制。[实验室机制](https://github.com/commonpost/thunderbird-mcp-lab/blob/8ad42c58c87746f00be20454676b7c04e8a7df39/README.md#L1-L31)及[公共场景](https://github.com/commonpost/thunderbird-mcp-lab/blob/8ad42c58c87746f00be20454676b7c04e8a7df39/README.md#L78-L103)

建议先覆盖：

- `create_draft` 只写一个草稿且附件字节一致；
- `reply_email` 的 `In-Reply-To` / `References`、收件人和主题正确；
- `forward_email` 真实生成一个 `message/rfc822` 附件且不丢附件；
- `diagnose_forward_preparation` 不留草稿、不投递、关闭目标 tab；
- timeout/断连后的 `unknown` 不被自动重放。

### 7. 发布、跨平台与可发现性

本项目查询服务是标准 stdio，但原生写信部署面向 macOS，扩展/native host 需手工打包、注册和安装；GitHub 没有正式 Release。[平台边界](https://github.com/zhangjian0410/thunderbird-mail-mcp/blob/a98b22434ef39fe8988105a9f8d26301aba04306/README.md#L63-L83)

对照：

- thunderbird-cli 从 npm 安装 CLI/bridge，扩展已签名并获 addons.thunderbird.net 批准，README 报告 22 账户/249k+ 邮件规模验证。[来源](https://github.com/vitalio-sh/thunderbird-cli/blob/465613daecb3228cc588ba90c77f395d9c92e375/README.md#L15-L30)
- U-C4N 的 `bootstrap.py` 一次完成环境、扩展安装、客户端注册和链路校验，并支持 Windows/macOS/Linux。[来源](https://github.com/U-C4N/Thunderbird-MCP/blob/5f774a0d3bf3a0172d4e95c3b8d2a3a11896af4d/README.md#L36-L54)
- Commonpost 在 Release 同时发布匹配版本的 XPI 和 bridge，并提供 provenance attestation及版本不匹配诊断。[来源](https://github.com/commonpost/thunderbird-mcp/blob/4ef89f81311f597cdd406f5c2ae660ec1750ffac/README.md#L22-L66)
- localai-org 发布静态 Go 二进制和容器镜像，profile 可只读挂载。[来源](https://github.com/localai-org/thunderbird-mcp/blob/e83ab752ecd6a9921734bb9969652740256270d8/README.md#L64-L100)

本项目文档的行为边界比多数仓库更细，对 unknown、幂等、来源指纹和无法证明的部分尤其诚实；但中文单语 README、无 Release、无截图/演示，会限制 GitHub 用户快速理解。建议保留中文主文档，增加简洁英文 overview。

## 建议路线图

### P0：先补安全与证据

1. **服务端 capability profile**：`read_only` / `review` / `direct_send`，默认至少 `review`，直接发送必须显式启用。
2. **逐封发送确认**：`confirm=true` 只能防误调用；若要强绑定人类确认，使用与幂等键、收件人和正文摘要绑定的一次性 approval token。
3. **真实 Thunderbird E2E lab**：覆盖草稿、回复、附件转发、诊断 no-send 和 unknown 不重放。
4. **正式 Release**：XPI、native host/launcher、校验和、版本握手说明；最好加构建 provenance。

### P1：补邮件主链，而不是横向膨胀

1. **回复/转发草稿或审阅窗口**：复用现有强绑定，默认人工审阅；直发成为高级模式。
2. **账户/文件夹自动发现**：扩展返回可读账户和 folder URI，逐步支持 Inbox/Sent 外的 Archive/自定义文件夹；不要解密 Thunderbird 凭据。
3. **邮件内容不可信边界**：在结果和 server instructions 中标明哪些字段受发件人控制，处理 closing-tag breakout、零宽/双向控制字符；保留显式原始读取能力。
4. **稳定错误码**：区分 `AUTHORIZATION_REQUIRED`、`SEND_DISABLED`、`STALE_SOURCE`、`RECIPIENT_MISMATCH`、`UNKNOWN_OUTCOME`、`CAPABILITY_MISSING`，避免客户端解析自由文本。

### P2：提高采用率

1. 跨平台 native-host 安装，至少先支持 Windows。
2. 双语 overview、架构图、短演示和“与其他 Thunderbird MCP 的区别”章节。
3. 可选 tool profiles，减少只读用户看到的写工具和上下文成本。

### 暂不建议

- 不建议为了工具数量立即加入联系人、日历、过滤器、偏好设置和 SMTP 服务器管理；这些能力会显著扩大权限面并削弱当前定位。
- 不建议读取 `key4.db` / `logins.json` 或另建 IMAP/SMTP 客户端；它会破坏“认证和投递完全交给 Thunderbird”的核心边界。
- 不建议把文档中的“调用方应取得授权”当成长期安全机制；公开 MCP 服务无法假定每个客户端都执行同一套 Harness 规则。

## 方法与限制

- 只使用 GitHub 仓库、README、源码、架构文档、发布页和 GitHub REST API 等一手来源。
- Star/Fork/最近 push 是 2026-10-29 的瞬时值，会变化。
- TKasperczyk、Commonpost、ThunderSend 有代码继承关系，不能当作三份完全独立的实现证据。
- 对方 README 中的测试数量、实机验证和安全声明为项目自述；本次没有重新运行其测试，也没有授予任何项目真实邮箱凭据。
- “本项目独有/更强”的判断仅针对本报告检查的样本和公开代码，不能证明不存在未被搜索到或未公开的实现。
