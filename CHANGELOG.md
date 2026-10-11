# Changelog

本文件记录 chinese-nlp-mcp 的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### P1 付费层 —— 本地计量（⚠️ 行为变化，升级必读）

P1 引入**每日调用配额**。所有工具仍然免费可用，只是有次数上限。
本阶段**完全离线**：没有 license key、没有 Gumroad 验证、没有任何网络请求。

#### 行为变化

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
  —— 当前限制、重置时间、升级权益、升级链接（`$19` 买断，Gumroad 链接为占位符，
  产品页创建后替换）。批量 API 属Pro 功能，免费层调用会返回升级引导错误。

- **网络完全离线**：P1 不做任何 license 验证，不发送任何数据。
  所有计数只写在本地状态文件里。

- **单次输入上限**（免费层）：

  | 约束 | 上限 | 适用工具 |
  |---|---|---|
  | 文本长度 | 20,000 字符 | `segment_chinese` / `convert_pinyin` / `extract_keywords` / `detect_sensitive_words` |
  | 自定义词库条数 | 1,000 条 | `detect_sensitive_words` |
  | `topN` | 50 | `extract_keywords` |

#### 新增

- `licensing/` 包：跨平台状态目录解析、配额闸门、tier 判定、设备记录。
  该包**对 MCP 框架零依赖**（AST 级校验通过），MCP 耦合集中在 `server.py`
  的 `@wrap_quota` 装饰器一处。
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
  正常使用，第 4 台起向 stderr 输出告警，功能完全不受影响。
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

[Unreleased]: https://github.com/leonmch-byte/chinese-nlp-mcp/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/leonmch-byte/chinese-nlp-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/leonmch-byte/chinese-nlp-mcp/releases/tag/v0.1.0
