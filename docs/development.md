# 开发与验证

[返回工程介绍](../README.md)

## 锁定环境

使用 uv **0.13.0**、Node **22.23.0**；`.python-version` 默认 Python 3.11，CI 同时验证 Python 3.10 和 3.11。运行依赖为官方 MCP Python SDK v1 的 `mcp>=1,<2`，精确传递版本、setuptools/wheel 构建工具和下载哈希由 `uv.lock` 固定。JavaScript 只用 Node 内置模块，没有 npm 依赖。

在新的检出或独立开发目录运行，避免改变已有服务的环境：

```bash
uv lock --check
uv sync --locked --no-install-project
uv sync --locked --no-build-isolation
uv run --no-sync python -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

第一步同步安装锁定的构建工具；第二步关闭构建隔离后安装本项目，避免另行下载未锁定的构建依赖。`--check` / `--locked` 拒绝过期锁文件，不静默更新它。

有意更新依赖时执行 `uv lock --upgrade`，或 `uv lock --upgrade-package <name>`；审阅锁文件差异、运行完整检查，再提交必要的 `pyproject.toml` 变更与 `uv.lock`。

## 自动测试与 CI

GitHub Actions 在 push、pull request、手动运行时执行三组任务：

- Linux / Python 3.10：锁文件检查、锁定安装、Python/Node 测试、扩展打包。
- macOS / Python 3.11：同样的安装、测试与打包检查。
- 敏感信息：真实扫描器自检，以及完整 Git 历史和受控当前文件扫描。

Actions 固定到完整 commit SHA，仅授予 `contents: read`，不保留 checkout 凭据，设有超时和并发取消。测试使用临时 mbox、模拟发送接口与临时产物；不会部署扩展、访问真实邮箱或发送邮件。

`tests/test_mcp_protocol.py` 从[通用配置示例](../examples/mcp-stdio.json)替换测试路径，使用官方 MCP 客户端启动真实 `server.py` 子进程。它以两个任意客户端身份完成初始化、默认 `review` 档位的 13 个工具发现、查询、正文与附件读取，使用与源码不同且含空格的工作目录，并检查 mbox 原字节不变；另一个用例验证 `read_only` 只公布 10 个工具，独立协议用例在显式 `direct_send` 下核对 reply / forward 的 schema、入队和幂等边界。此检查证明标准协议可用，不等同于 Qoder/QwenWork GUI 端到端测试，也不验证真实 Thunderbird 发送。

## 敏感信息检查

检查使用 Gitleaks **8.30.1** 默认密钥规则，以及独立的私人 home 路径、非示例邮箱、本地配置文件检查。Python 规则独立于通用密钥规则的路径例外，完整历史包含 merge diff。Gitleaks 的测试和锁文件也不会整体排除。

从 [Gitleaks 官方发布](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1)下载适合平台的程序，核对 checksums 文件。CI 固定版本与 Linux 压缩包的 SHA-256；本地验证：

```bash
export GITLEAKS_BIN="/absolute/path/to/gitleaks"
uv run --no-sync python scripts/test_secret_scanner.py
uv run --no-sync python scripts/check_secrets.py
```

自检仅在临时仓库构造合成 token 和私人路径，验证已删除的历史密钥、merge-only 配置和行内放行注释仍会导致检查失败，诊断不输出完整 token。真实扫描不遍历未跟踪的虚拟环境、用户目录或真实邮箱；不采用仓库指纹忽略或行内 `gitleaks:allow`。

内容规则仅允许保留的 example/test/invalid 示例地址、固定扩展 ID 和 GitHub noreply 身份；诊断只报告位置与规则。不要将真实配置用作测试 fixture。若发现真实凭据泄露，须撤销或轮换并核查历史，不能只删文件或增加放行规则。

## 不提交本地数据

`.gitignore` 忽略虚拟环境、缓存、环境变量文件、数据库/mbox、`dist/`、构建产物、XPI、生成的 native-host 清单、回滚记录和 `deployment-backups/`。扫描器还会拒绝强制跟踪的本地配置，例如 `prefs.js`、`profiles.ini`、`logins.json`、`key4.db` 和 Inbox/Sent/Drafts。

`scripts/package_send.py` 可在临时输出目录验证打包；生成的清单包含实际安装路径，不应提交。`scripts/deploy_send.py` 会改变目标安装文件及 native host 注册，只在明确部署时使用，普通测试不调用部署。
