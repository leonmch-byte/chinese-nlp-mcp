# chinese-nlp-mcp

中文 NLP 能力的 MCP Server，面向海外开发者。本地 stdio 运行，纯离线推理。

## 特性

- **stdio transport** — 本地进程通信，不开放任何端口
- **纯本地** — 关闭 fastmcp 版本检查，启动零网络请求
- **协议安全** — 日志一律写 stderr，绝不污染 stdout 的 JSON-RPC 流

## 环境要求

- Python 3.13+
- 依赖装在项目专用 venv，不污染系统 Python

## 安装

```bash
# Windows (Git Bash)
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# macOS / Linux
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

## 客户端接入

在 MCP 客户端（如 Claude Desktop / Cursor / VS Code）的配置中填入：

```json
{
  "mcpServers": {
    "chinese-nlp-mcp": {
      "command": "/absolute/path/to/chinese-nlp-mcp/.venv/Scripts/python.exe",
      "args": ["/absolute/path/to/chinese-nlp-mcp/server.py"]
    }
  }
}
```

## 工具

### Day 1 状态

| 工具 | 状态 | 说明 |
|---|---|---|
| `hello_world` | ✅ 已实现 | 健康检查，返回 `Hello from Chinese NLP MCP` |

### Day 2 状态

| 工具 | 签名 | 状态 | 说明 |
|---|---|---|---|
| `segment_chinese` | `(text: str, mode: str = "default") -> list[str]` | ✅ 已实现 | jieba 分词，`mode` 支持 `default` / `search` / `index` |

### 计划中

| 工具 | 签名 | 说明 |
|---|---|---|
| `extract_keywords` | `(text: str, topN: int = 10) -> list[dict]` | 关键词提取，返回 `[{word, weight}]` |
| `convert_pinyin` | `(text: str, style: str = "tone", separator: str = " ") -> str` | 拼音转换，`style` 支持 `tone` / `tone2` / `initials` / `first_letter` |
| `detect_sensitive_words` | `(text: str, words: list[str] = []) -> dict` | **仅检测用户自定义词库**，默认词库为空 |

> **`mode` 三模式说明**：jieba 0.42.1 顶层**没有** `cut_for_index`，
> 且 `tokenize(mode=...)` 内部只区分 `default` 与"其他"，传 `index` 会
> **静默降级为 search**。本项目显式将 `index` 映射到 `cut_for_search`，
> 行为与 `search` 一致，避免给调用方"index 是独立模式"的错觉。
>
> `search` / `index` 下jieba 内部计算的 `(word, start, end)` 位置信息**不返回**，
> 返回值统一为 `list[str]`。

> **错误处理**：参数非法抛 `ValueError`，内部失败抛 `RuntimeError`，
> 均由 fastmcp 转成 `isError=true`，工具签名保持纯净、不返回错误包装体。

> `detect_sensitive_words` 刻意不内置任何词库。仅接受调用方传入的 `words`，
> 返回 `{matches: [{word, index}], clean: bool}`。

## 开发

验收统一走 Inspector 手工验证：

```bash
npx @modelcontextprotocol/inspector \
  ./.venv/Scripts/python.exe server.py
```

浏览器打开提示的地址（默认 http://localhost:6274），在 Tools 面板即可看到并调用工具。

### Day 2 状态

| 工具 | 状态 | 说明 |
|---|---|---|
| `segment_chinese` | ✅ 已实现 | jieba 三模式（default / search / index），mode 白名单校验 |

## 路线图

- [x] Day 1 — 项目骨架 + `hello_world` + Inspector 验收
- [x] Day 2 — `segment_chinese`（jieba 三模式）
- [ ] Day 3 — `convert_pinyin`（pypinyin）
- [ ] Day 4 — `extract_keywords`（TF-IDF）
- [ ] Day 5 — `detect_sensitive_words`（AC 自动机）

每个工具独立实现、独立验收、独立提交。

## License

MIT
