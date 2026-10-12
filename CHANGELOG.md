# Changelog

本文件记录 chinese-nlp-mcp 的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.0] - 2026-10-12

### Added

- Pro license verification via Gumroad API. Requires CHINESE_NLP_LICENSE_KEY
  environment variable. When unset, the server remains fully offline.
- Local license cache with 24-hour TTL (paid) and 1-hour TTL (invalid).
- 7-day offline grace period for transient network failures.
- CHINESE_NLP_STORE_KEY=1 opt-in to persist license key in plaintext
  (default: not persisted).

### Changed

- README updated to clarify network behavior: offline by default, one
  network call at startup only when a license key is configured.

<details>
<summary>详细说明（中文）</summary>

首次引入**唯一的一条出网请求**：当用户配置了 license key 时，
服务器**启动时**向 Gumroad 校验一次。

#### 行为变化

- **未配置 key（默认）**：行为与 0.2.0 完全一致，**零网络请求**。
- **配置了 key**：启动时校验一次，结果缓存 24h；
  之后 24h 内每次启动都不联网，直接读缓存。
- **断网宽限 7 天**：上次成功验证在 7 天内且网络故障 → 保持 Pro 功能。
  HTTP 404 / 4xx / `success:false` / 退款 / 争议 / 拒付**一律立即降级，不给宽限**。
- **license 失效是静默的**：不会抛错、不会弹窗、不改变任何工具的返回结构，
  只是退回到免费层配额（表现为原有的配额超限文案）。
- **无效 key 的缓存只保留 1 小时**（付费缓存 24h）——
  输错 key 后立刻改对、或后台解封 key，最多等 1 小时。

#### 配置方式

```bash
# 推荐：不落盘，由用户在 shell 里配
export CHINESE_NLP_LICENSE_KEY=<你的 key>

# 可选：明确同意把 key 存在本地（0600 + HMAC）
export CHINESE_NLP_STORE_KEY=1

# 诊断：把 tier / 缓存状态打到 stderr
export CHINESE_NLP_LICENSE_DEBUG=1

# 自解锁：清除本地缓存与凭证
export CHINESE_NLP_LICENSE_RESET=1
```

⚠️ **默认不保存 key 明文**。隐私承诺要成立就得做到这一点 ——
HMAC 只防篡改不防读取，状态目录可能被云盘同步或备份软件扫描。
本地缓存只存 `sha256(key)` 的前 16 位十六进制，**永不存明文**。

#### 隐私

验证请求**只发送 `license_key` 与 `product_id` 两个字段**，
不发送任何用户数据（文本、工具名、调用计数、设备 ID、遥测一律不上报）。

缓存与日志中**永不出现**明文 key、邮箱、referrer、IP 国家 —— 这些字段
在 Gumroad 响应里确实存在，实现按字段白名单挑取，不整体落盘或打日志。

</details>

## [0.2.0] - 2026-10-11

P1 付费层 —— 本地计量（⚠️ 行为变化，升级必读）。

P1 引入**每日调用配额**。所有工具仍然免费可用，只是有次数上限。
本阶段**完全离线**：没有 license key 校验、没有网络请求、不发送任何数据。

### 行为变化

- **免费层新增每日配额**（每个自然日按 UTC 00:00 重置）：

  | 工具 | 每日上限 |
  |---|---|
  | `segment_chinese` | 500 次 |
  | `convert_pinyin` | 300 次 |
  | `extract_keywords` | 100 次 |
  | `detect_sensitive_words` | 200 次 |

- **`hello_world` 不受配额影响**：健康检查工具永不拦截，
  否则客户端会误判服务器故障。

- **达到上限时**：对应工具返回 `isError: true`，并给出包含四要素的引导文案
  —— 当前限制、重置时间、升级权益、升级链接（`$19` 买断，
  链接指向 https://wolfmanchao.gumroad.com/l/chinese-nlp-mcp-pro）。
  批量 API 属Pro 功能，免费层调用会返回升级引导错误。

- **网络完全离线**：P1 不做任何 license 校验，不发送任何数据。
  所有计数只写在本地状态文件里。
  ⚠️ License Key 的 Gumroad 在线验证属**后续版本**（P3）才会引入。

- **单次输入上限**（免费层）：

  | 约束 | 上限 | 适用工具 |
  |---|---|---|
  | 文本长度 | 20,000 字符 | `segment_chinese` / `convert_pinyin` / `extract_keywords` / `detect_sensitive_words` |
  | 自定义词库条数 | 1,000 条 | `detect_sensitive_words` |
  | `topN` | 50 | `extract_keywords` |

### 新增

- `licensing/` 包：跨平台状态目录解析、配额闸门、tier 判定、设备记录、
  Gumroad 产品常量。该包**对 MCP 框架零依赖**（AST 级校验通过），
  MCP 耦合集中在 `server.py` 的 `@wrap_quota` 装饰器一处。

- `licensing/gumroad.py`：Gumroad `PRODUCT_ID` / `PRODUCT_URL` /
  `VERIFY_ENDPOINT` 常量。所有引导文案统一引用常量，不再硬编码 URL。

- 计数持久化 + 防篡改：HMAC-SHA256 双层绑定（`machine_id` + 本地密钥），
  日期回拨检测，7 天历史剪枝，原子写（临时文件 + `os.replace`）。
  签名校验失败时**保守按满额处理**（失效安全）。

- 状态目录：
  - Windows: `%LOCALAPPDATA%\chinese-nlp-mcp\`
  - macOS: `~/Library/Application Support/chinese-nlp-mcp/`
  - Linux: `$XDG_STATE_HOME/chinese-nlp-mcp/`（回退 `~/.local/state/...`）

  ⚠️ Windows 刻意**不用** `%APPDATA%`（Roaming）：该目录在企业环境下会随
  登录跨机同步，而 HMAC 密钥绑定 `machine_id`，跨机同步必然导致签名误判为篡改。

- 设备记录（**仅告警，绝不拒绝**）：启动时记录本机 `machine_id`
  （只存 `sha256` 前 16 字符，不存明文）。**允许 3 个设备**——第 1/2/3 台
  正常使用，第 4 台起向 stderr输出告警，功能完全不受影响。
  告警文案中的 N 为出现过的设备总数。误伤已付费用户的代价远高于放过共享者。

  设`CHINESE_NLP_DEVICE_RESET=1` 可清空设备名单（只保留当前机器），
  该操作**不重置配额计数**。

  诚实的能力边界：纯本地架构无法真正检测 key 共享，本机制只降低共享的
  便利性并留下审计痕迹，不构成 DRM。

## [0.1.1] - 2026-10-11

修复 Official MCP Registry 发布校验失败。

### 变更

- README 标题下方新增 `mcp-name: io.github.leonmch-byte/chinese-nlp-mcp`，
  用于通过 Registry 的 PyPI 包归属校验（ownership validation）。
- 新增 MIT `LICENSE`（Copyright (c) 2026 leonmch-byte）。

### 修复

- `server.json` 迁移到官方 `2025-12-11` schema：字段改为 camelCase
  （`registryType` / `registryBaseUrl`），移除已废弃的顶层 `status` 字段。

## [0.1.0] - 2026-10-10

首个版本。5 个 MCP 工具全部实现并逐个独立验收。

### 新增

- `segment_chinese(text, mode="default") -> list[str]`
  jieba 分词，支持 `default` / `search` / `index` 三模式。
  注：jieba 0.42.1 顶层没有 `cut_for_index`，且 `tokenize(mode=...)` 会把
  `index` 静默降级为 `search`，故本项目显式将 `index` 映射到 `cut_for_search`。

- `convert_pinyin(text, style="tone", separator=" ") -> str`
  pypinyin 拼音转换，支持 `tone` / `tone2` / `initials` / `first_letter`。

- `extract_keywords(text, topN=10) -> list[dict]`
  TF-IDF 关键词提取，返回 `[{"word": ..., "weight": ...}]`，按权重降序。
  `weight` 为 TF-IDF 原始分，未归一化，可大于 1.0。

- `detect_sensitive_words(text, words=None) -> dict`
  Aho-Corasick 自动机检测**调用方自定义**词库。
  🔴 **不含任何内置词库，也不含任何示例词**；`words` 为空则不检测。
  重叠匹配返回全部命中，不去重、不做最长/最短裁剪。

- `hello_world() -> str` 健康检查工具。

### 行为约定

- stdio transport，不开放任何端口；启动零网络请求（已关闭 fastmcp 版本检查）。
- 所有日志写 stderr，源码零 `print()`，不污染 JSON-RPC 协议流。
- 参数非法抛 `ValueError`，内部失败抛 `RuntimeError`，均转为 `isError=true`；
  工具签名保持纯净，不返回错误包装体。

### 打包

- hatchling 构建后端，Python >= 3.10。
- 控制台入口 `chinese-nlp-mcp`，支持 `uvx chinese-nlp-mcp` 一键运行。

[Unreleased]: https://github.com/leonmch-byte/chinese-nlp-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/leonmch-byte/chinese-nlp-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/leonmch-byte/chinese-nlp-mcp/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/leonmch-byte/chinese-nlp-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/leonmch-byte/chinese-nlp-mcp/releases/tag/v0.1.0
