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

### 已实现工具

| 工具 | 签名 | 说明 |
|---|---|---|
| `hello_world` | `() -> str` | 健康检查，返回 `Hello from Chinese NLP MCP` |
| `segment_chinese` | `(text: str, mode: str = "default") -> list[str]` | jieba 分词，`mode` 支持 `default` / `search` / `index` |
| `convert_pinyin` | `(text: str, style: str = "tone", separator: str = " ") -> str` | pypinyin 拼音转换，`style` 支持 `tone` / `tone2` / `initials` / `first_letter` |
| `extract_keywords` | `(text: str, topN: int = 10) -> list[dict]` | TF-IDF 关键词提取，返回 `[{word, weight}]`，按权重降序 |
| `detect_sensitive_words` | `(text: str, words: list[str] \| None = None) -> dict` | **自定义**敏感词检测，Aho-Corasick 自动机 |

> 🔴 **`detect_sensitive_words` 红线（不可协商）**
>
> 本工具**不含任何内置词库，也不内置任何示例词**。词库唯一来源是调用方传入的
> `words` 参数。传 `[]` 或 `None` 等同于不检测，直接返回
> `{"matches": [], "clean": true}`。
> 这是项目级设计红线：内容安全策略必须由使用者自己掌控，工具不得替他预设。
>
> **重叠匹配策略：返回全部命中，不去重、不做最长/最短优先裁剪。**
> 理由：调用方是自己词库的负责人，最清楚"命中什么"才是关心的信号。
> 若工具替他裁剪（例如只留最长匹配），他既无法知道被裁掉的短词也命中了，
> 也无法对重叠区间做差异化处置。拿到全部命中后，调用方完全可以按 `index`
> 自行裁剪或聚合，而工具不做这个预设立场。
>
> 例：`text="中华人民共和国"`, `words=["中国人民","人民"]`
> → 返回 2 条命中，`index` 分别为 `0` 和 `2`。
>
> **实现方案**：pyahocorasick（实测 Windows + Python 3.13 有预编译 wheel，
> 无需本地编译；4813 词库 × 10 万字文本耗时 0.008 秒）。
> `index` 是**字符索引**（中文按 1 字计，非字节索引）。

> **`extract_keywords` 说明**：
> - 底层 jieba 的参数名是 `topK`（非 `topN`），且需 `withWeight=True` 才会返回权重。
> - `weight` 是 **TF-IDF 原始分，未归一化**，值域通常 0 ~ 6，**可大于 1.0**
>   （例："天安门广场" → 1.6316）。它表示该词在当前语料中的重要程度，
>   不是概率或百分比。
> - 返回顺序已按权重降序；`topN` 超过可提取词数时返回全部词，**不报错**。
> - 本工具是四个业务工具中唯一返回 `list[dict]` 的，属有意设计。
> - **中英混合文本中，英文单词会被 jieba 作为独立 token 保留并参与 TF-IDF 计算，
>   不会被过滤**（例：`Python 编程语言很强大` → 提取出 `Python`，weight 3.98）。

> **`style` 四种风格说明**：实测 pypinyin 0.55.0 的 `lazy_pinyin(text, style="bad")`
> **不会报错**，而是静默降级为 `Style.NORMAL`（带调拼音）。因此本工具在入口处
> 强制白名单校验，不把非法style 透传给底层库。
>
> 取值参考：`tone` → `zhōng`、`tone2` → `zho1ng`、`initials` → `zh`、`first_letter` → `z`。
>
> **`tone2` 标注规则**：遵循 pypinyin 原生命名规则，声调数字标注在**元音后**
> （如 `zho1ng`），而非词尾（`zhong1`）。这是 pypinyin 的既有行为，非缺陷。

> **`mode` 三模式说明**：jieba 0.42.1 顶层**没有** `cut_for_index`，
> 且 `tokenize(mode=...)` 内部只区分 `default` 与"其他"，传 `index` 会
> **静默降级为 search**。本项目显式将 `index` 映射到 `cut_for_search`，
> 行为与 `search` 一致，避免给调用方"index 是独立模式"的错觉。
>
> `search` / `index` 下jieba 内部计算的 `(word, start, end)` 位置信息**不返回**，
> 返回值统一为 `list[str]`。

> **错误处理**：参数非法抛 `ValueError`，内部失败抛 `RuntimeError`，
> 均由 fastmcp 转成 `isError=true`，工具签名保持纯净、不返回错误包装体。

> **测试规约**（Day 3 锁定）：
> 1. 反例必须同时断言 `isError=true` **且** 错误文案包含预期片段。只看标志位会漏过
>    "底层库静默降级"类回归——错误可能被包装成别的异常，`isError` 照样为true。
> 2. stdio 子进程的 `stderr` 必须接文件或 `DEVNULL`，**绝不接 `subprocess.PIPE`**。
>    fastmcp 报错时 rich 会打印几十 KB traceback，塞满管道会导致 server 侧写阻塞、
>    响应永远发不出（表现为假死/超时，而非真实崩溃）。
> 3. **提交前必须用 `git status` 检查暂存区**，确认不含本地临时文件；
>    **禁止 `git add -A` 后直接 commit**。本地取证脚本、stderr 日志等
>    必须先确认已被 `.gitignore` 覆盖。

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
- [x] Day 3 — `convert_pinyin`（pypinyin 四 style）
- [x] Day 4 — `extract_keywords`（TF-IDF）
- [x] Day 5 — `detect_sensitive_words`（Aho-Corasick）

每个工具独立实现、独立验收、独立提交。

## License

MIT
