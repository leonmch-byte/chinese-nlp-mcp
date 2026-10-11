# Changelog

本文件记录 chinese-nlp-mcp 的重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
