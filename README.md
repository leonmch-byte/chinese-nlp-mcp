# chinese-nlp-mcp

mcp-name: io.github.leonmch-byte/chinese-nlp-mcp

中文 NLP 能力的 MCP Server：分词、关键词提取、拼音转换、自定义敏感词检测。
本地 stdio 运行，全部推理在进程内完成。

📝 **Tutorial:** [How to Add Chinese NLP to Your AI Agent in 5 Minutes](https://dev.to/leonmch/how-to-add-chinese-nlp-to-your-ai-agent-in-5-minutes-57l6)

## 特性

- **纯本地推理** — 未配置 license key 时零网络请求、无遥测，文本不离开本机
- **stdio transport** — 本地进程通信，不开放任何端口
- **协议干净** — 日志一律走 stderr，不污染 stdout 的 JSON-RPC 流

## 环境要求

Python 3.10 或更高版本。

## 安装

### 方式一：uvx 一键运行（推荐，无需安装）

```bash
uvx chinese-nlp-mcp
```

需要先安装 uv：<https://docs.astral.sh/uv/getting-started/installation/>
（macOS/Linux 用 `curl -LsSf https://astral.sh/uv/install.sh | sh`，
Windows 用 `irm https://astral.sh/uv/install.ps1 | iex`）

### 方式二：pip 安装

```bash
pip install chinese-nlp-mcp
# 安装后同样可用命令行启动
chinese-nlp-mcp
```

### 方式三：从源码安装（备选，开发用）

```bash
git clone https://github.com/leonmch-byte/chinese-nlp-mcp
cd chinese-nlp-mcp

# Windows (Git Bash)
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# macOS / Linux
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

## 客户端接入

推荐用 `uvx`，无需关心 Python 环境：

```json
{
  "mcpServers": {
    "chinese-nlp-mcp": {
      "command": "uvx",
      "args": ["chinese-nlp-mcp"]
    }
  }
}
```

若用 pip 安装（方式二）：

```json
{
  "mcpServers": {
    "chinese-nlp-mcp": {
      "command": "chinese-nlp-mcp"
    }
  }
}
```

若从源码安装（方式三）：

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

> VS Code 用 `servers` 键，Claude Desktop / Cursor 用 `mcpServers` 键。

## 工具

| 工具 | 签名 | 说明 |
|---|---|---|
| `hello_world` | `() -> str` | 健康检查，返回 `Hello from Chinese NLP MCP` |
| `segment_chinese` | `(text: str, mode: str = "default") -> list[str]` | 中文分词，`mode` 支持 `default` / `search` / `index` |
| `convert_pinyin` | `(text: str, style: str = "tone", separator: str = " ") -> str` | 拼音转换，`style` 支持 `tone` / `tone2` / `initials` / `first_letter` |
| `extract_keywords` | `(text: str, topN: int = 10) -> list[dict]` | TF-IDF 关键词提取，返回 `[{word, weight}]`，按权重降序 |
| `detect_sensitive_words` | `(text: str, words: list[str] \| None = None) -> dict` | 自定义敏感词检测（Aho-Corasick 自动机） |

> 🔴 **`detect_sensitive_words` 不含任何内置词库**
>
> 本工具**不内置任何词库，也不内置任何示例词**。词库唯一来源是调用方传入的
> `words` 参数。传 `[]` 或 `None` 等同于不检测，直接返回
> `{"matches": [], "clean": true}`。
> 内容安全策略必须由使用者自己掌控，工具不会替他预设。

### 你需要知道的行为细节

这些直接影响你怎么解析返回值，所以列在这里。

**`detect_sensitive_words` — 重叠匹配返回全部命中**

不去重、不做最长/最短优先裁剪。调用方是自己词库的负责人，
最清楚"命中什么"才是关心的信号；拿到全部命中后可按 `index` 自行裁剪或聚合。

例：`text="中华人民共和国"`, `words=["中国人民","人民"]` → 返回 2 条命中，
`index` 分别为 `0` 和 `2`。`index` 是**字符索引**（中文按 1 字计，非字节索引）。

**`extract_keywords` — `weight` 是未归一化的 TF-IDF 原始分**

值域通常 0 ~ 6，**可大于 1.0**（例："天安门广场" → 1.6316）。
它表示该词在当前语料中的重要程度，**不是概率或百分比**。

返回顺序已按权重降序；`topN` 超过可提取词数时返回全部词，不报错。
中英混合文本中，英文单词会作为独立 token 保留并参与计算，不会被过滤
（例：`Python 编程语言很强大` → 提取出 `Python`，weight 3.98）。

**`convert_pinyin` — `tone2` 的数字标在元音后**

`zhong` → `zho1ng`，不是 `zhong1`。这是 pypinyin 的既有命名规则。
`style` 只接受上表四个值，传入其他值会抛错（底层库本会静默降级，
本项目在入口处拦下，避免你拿到"看起来对但不是你要的结果"）。

**`segment_chinese` — `index` 与 `search` 行为一致**

jieba 没有独立的 index 模式，本项目把 `index` 映射为搜索模式。
两种模式都不返回位置信息，返回值统一是 `list[str]`。

**返回值怎么读**

返回 `dict` 的工具（`detect_sensitive_words`）会被 fastmcp **直接展开**为
`structuredContent`，**不额外加 `result` 包装层**；
返回 `list` / `str` 的工具则会被包成 `structuredContent.result`。

例：从 `structuredContent.matches` 与 `structuredContent.clean` 取值，
而不是 `structuredContent.result.matches`。

**错误处理**

参数非法抛 `ValueError`，内部失败抛 `RuntimeError`，
均由 fastmcp 转成 `isError=true`，工具签名保持纯净。

## 免费层每日配额（v0.2.0 起）

所有工具都可免费使用，但有每日次数上限（按 UTC 00:00 重置）：

| 工具 | 每日上限 |
|---|---|
| `hello_world` | **无限制**（健康检查永不拦截） |
| `segment_chinese` | 500 |
| `convert_pinyin` | 300 |
| `extract_keywords` | 100 |
| `detect_sensitive_words` | 200 |

单次输入上限：文本 20,000 字符、自定义词库 1,000 条、`topN` 最大 50。

达到上限时该工具返回 `isError: true`，并附带当前限制、重置时间、
Pro 权益与升级链接。`hello_world` 始终不受影响，避免客户端误判服务器故障。

## Pro License（v0.3.0 起）

```bash
export CHINESE_NLP_LICENSE_KEY=<你的 key>   # Windows: $env:CHINESE_NLP_LICENSE_KEY="..."
```

| 项目 | 值 |
|---|---|
| 验证频率 | 每次启动校验一次，结果缓存 24 小时 |
| 断网宽限 | 7 天（上次成功验证在 7 天内且网络故障时保持 Pro） |
| 超时 | 8 秒，不重试 |
| 本地保存 | 默认**不保存**明文 key |

如果你希望免去每次配环境变量，可显式同意把 key 存在本地
（权限 0600 + HMAC 签名）：

```bash
export CHINESE_NLP_STORE_KEY=1
```

诊断用 `CHINESE_NLP_LICENSE_DEBUG=1`（tier 与缓存状态打到 stderr），
自解锁用 `CHINESE_NLP_LICENSE_RESET=1`（清除本地缓存与凭证）。

**License 失效是静默的**：不会弹窗、不会改变工具返回结构，
只是退回免费层配额（表现为原有的配额超限文案）。

每日计数保存在你本机的状态文件里：

- Windows: `%LOCALAPPDATA%\chinese-nlp-mcp\`
- macOS: `~/Library/Application Support/chinese-nlp-mcp/`
- Linux: `$XDG_STATE_HOME/chinese-nlp-mcp/`

需要更高额度与批量 API：<https://wolfmanchao.gumroad.com/l/chinese-nlp-mcp-pro>
（$19 买断，非订阅）

## Privacy

**Without a license key:** Fully offline. No network calls, no telemetry.
Your text never leaves the machine.

**With a Pro license key:** The key is verified against Gumroad once at
startup, cached for 24 hours. Only `product_id` and `license_key` are sent.
No text content, no usage statistics, no machine identifiers.

Verification can be disabled entirely by not setting `CHINESE_NLP_LICENSE_KEY`.

工具调用本身在两种情况下都**完全离线** —— 网络请求只发生在服务器启动时，
且仅在配置了 license key 时。每 24 小时至多一次。

本地只保存 license key 的 SHA-256 摘要（前 16 位十六进制），
**不保存明文**。缓存、日志、错误信息中都不含明文 key、邮箱或 IP。

> 这个项目是 MIT 开源的本地软件，**没有 DRM**。
> 每日计数是防篡改（tamper-resistant）而非防破解（tamper-proof）——
> 有决心的人总能从源码层面绕过任何本地机制。
> 我们卖的是便利（批量 API、长文本、自定义词典），不是锁。

## 开发

验收方式、测试规约、实现层踩坑记录见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## License

MIT
