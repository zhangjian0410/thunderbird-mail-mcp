# Development and verification

**English** | [简体中文](development.zh-CN.md) · [Project overview](../README.md)

## Locked environment

Use uv **0.13.0** and Node **22.23.0**. `.python-version` selects Python 3.11; CI tests Python 3.10 and 3.11. The runtime dependency is the official MCP Python SDK v1, `mcp>=1,<2`. `uv.lock` pins exact transitive dependencies, setuptools/wheel build tools, and download hashes. JavaScript uses only Node built-ins; there are no npm dependencies.

Run in a fresh checkout or separate development directory to avoid changing a live service's environment:

```bash
uv lock --check
uv sync --locked --no-install-project
uv sync --locked --no-build-isolation
uv run --no-sync python -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

The first sync installs locked build tools. The second installs the project with build isolation disabled, avoiding a separately resolved build environment. `--check` / `--locked` reject an outdated lockfile instead of silently updating it.

For intentional dependency updates, run `uv lock --upgrade` or `uv lock --upgrade-package <name>`. Review the lockfile diff, run the full checks, and commit the necessary `pyproject.toml` and `uv.lock` changes.

## Automated tests and CI

GitHub Actions runs three jobs on push, pull request, and manual dispatch:

- Linux / Python 3.10: lockfile validation, locked installation, Python/Node tests, and extension packaging.
- macOS / Python 3.11: the same installation, tests, and packaging checks.
- Sensitive information: real-scanner self-tests, followed by scans of complete Git history and tracked checkout files.

Actions are pinned to full commit SHAs, receive only `contents: read`, and do not persist checkout credentials. Jobs have timeouts and cancel superseded runs through concurrency settings. Tests use temporary mbox files, mocked sending APIs, and temporary artifacts; they do not deploy the extension, read real mailboxes, or send mail.

`tests/test_mcp_protocol.py` substitutes fixture paths into the [generic configuration](../examples/mcp-stdio.json), then uses the official MCP client to launch real `server.py` subprocesses. Two arbitrary client identities exercise initialization, 13-tool discovery under `review`, queries, message bodies, and attachments. The working directory differs from the source directory and contains spaces; the tests verify that mbox bytes remain unchanged. A separate case checks the 10-tool `read_only` profile; explicit `direct_send` cases exercise reply/forward schemas, queueing, and idempotency. These tests establish standard-protocol behavior, not Qoder/QwenWork GUI compatibility or actual Thunderbird delivery.

`python -m unittest discover -s tests` does not run `scripts/test_secret_scanner.py`. Run the real-scanner self-tests and sensitive-data scans separately as shown below; CI also executes them in separate steps.

## Maintaining bilingual documentation

The English entry points are `README.md`, `docs/reference.md`, and `docs/development.md`. Their Chinese counterparts are `README.zh-CN.md`, `docs/reference.zh-CN.md`, and `docs/development.zh-CN.md`. Keep interfaces, limits, environment versions, and commands synchronized. README links should lead to documents in the same language, with language switches at the top of each page. `CHANGELOG.md` and historical research reports currently remain in Chinese.

Use `server.py` for tool signatures and minimum profiles; `mail_reader.py`, `mail_store.py`, `mail_sender.py`, and `extension/` for input limits and state semantics. Check deployment commands against `scripts/package_send.py` / `scripts/deploy_send.py`, and development versions/checks against `pyproject.toml`, `uv.lock`, and `.github/workflows/ci.yml`. `tests/test_server.py` checks both README versions/tool counts and both tool catalogs' signatures, defaults, and minimum profiles. The deployment file list includes these bilingual entry points.

## Sensitive-data checks

Checks use Gitleaks **8.30.1** default secret rules plus independent checks for private home-directory paths, non-example email addresses, and local configuration files. The Python rules apply independently of generic secret-rule path exceptions. History scans include merge diffs. Tests and lockfiles are not excluded wholesale from Gitleaks.

Download the appropriate binary from the [official Gitleaks release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1) and verify its checksum. CI pins the version and Linux archive SHA-256. To verify locally:

```bash
export GITLEAKS_BIN="/absolute/path/to/gitleaks"
uv run --no-sync python scripts/test_secret_scanner.py
uv run --no-sync python scripts/check_secrets.py
```

Self-tests create synthetic tokens and private paths only inside temporary repositories. They verify that deleted historical secrets, merge-only configuration, and inline allow comments still cause failure, with diagnostics that do not reveal complete tokens. The real scan does not traverse untracked virtual environments, home directories, or real mailboxes. It does not use repository fingerprint ignores or inline `gitleaks:allow` exceptions.

Content rules permit only reserved example/test/invalid email domains, the fixed extension ID, and GitHub noreply identities. Diagnostics report locations and rules. Do not use real configuration as test fixtures. If a real credential is exposed, revoke or rotate it and inspect history; deleting the file or adding an exception is insufficient.

## Keep local data out of Git

`.gitignore` excludes virtual environments, caches, environment files, databases/mbox files, `dist/`, build artifacts, XPI packages, generated native-host manifests, rollback records, and `deployment-backups/`. The scanner also rejects force-tracked local configuration such as `prefs.js`, `profiles.ini`, `logins.json`, `key4.db`, and Inbox/Sent/Drafts.

Use `scripts/package_send.py` with a temporary output directory to verify packaging. Its generated manifest contains the actual installation path and must not be committed. `scripts/deploy_send.py` changes installation files and native-host registration; use it only for an authorized deployment. Tests exercise it against temporary fixtures, not a live installation.
