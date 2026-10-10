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
| `check_license` | ✅ 已实现 | 占位实现，恒返回 `free` 计划 |

### 计划中

| 工具 | 签名 | 说明 |
|---|---|---|
| `segment_chinese` | `(text: str, mode: str = "default") -> list[str]` | 分词，`mode` 支持 `default` / `search` / `index` |
| `extract_keywords` | `(text: str, topN: int = 10) -> list[dict]` | 关键词提取，返回 `[{word, weight}]` |
| `convert_pinyin` | `(text: str, style: str = "tone", separator: str = " ") -> str` | 拼音转换，`style` 支持 `tone` / `tone2` / `initials` / `first_letter` |
| `detect_sensitive_words` | `(text: str, words: list[str] = []) -> dict` | **仅检测用户自定义词库**，默认词库为空 |

> `detect_sensitive_words` 刻意不内置任何词库。仅接受调用方传入的 `words`，
> 返回 `{matches: [{word, index}], clean: bool}`。

## 开发

### 独立验收（无需 GUI）

```bash
./.venv/Scripts/python.exe _verify_day1.py
```

脚本以 stdio 客户端协议直连 server.py，验证 `tools/list` 与 `tools/call`。

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector \
  ./.venv/Scripts/python.exe server.py
```

浏览器打开提示的地址（默认 http://localhost:6274），在 Tools 面板即可看到并调用 `hello_world`。

## 路线图

- [x] Day 1 — 项目骨架 + `hello_world` + Inspector 验收
- [ ] Day 2 — `segment_chinese`（jieba）
- [ ] Day 3 — `convert_pinyin`（pypinyin）
- [ ] Day 4 — `extract_keywords`（TF-IDF）
- [ ] Day 5 — `detect_sensitive_words`（AC 自动机）

每个工具独立实现、独立验收、独立提交。

## License

MIT
