# 开发文档

面向贡献者与维护者。**普通用户请看 [README.md](README.md)** —— 那里只有安装、
用法与行为约定，没有实现细节与开发过程记录。

本文件记录三类内容：
1. **测试规约** —— 写测试时必须遵守的规则，以及每条规则背后的真实案例
2. **实现层踩坑** —— 底层库的实测行为与由此产生的设计决策
3. **开发流程** —— 验收方式与分阶段约定

---

## 测试规约

> 1. 反例必须同时断言 `isError=true` **且** 错误文案包含预期片段。只看标志位会漏过
>    "底层库静默降级"类回归——错误可能被包装成别的异常，`isError` 照样为 true。
> 2. stdio 子进程的 `stderr` 必须接文件或 `DEVNULL`，**绝不接 `subprocess.PIPE`**。
>    fastmcp 报错时 rich 会打印几十 KB traceback，塞满管道会导致 server 侧写阻塞、
>    响应永远发不出（表现为假死/超时，而非真实崩溃）。
> 3. **提交前必须用 `git status` 检查暂存区**，确认不含本地临时文件；
>    **禁止 `git add -A` 后直接 commit**。本地取证脚本、stderr 日志等
>    必须先确认已被 `.gitignore` 覆盖。
> 4. **库行为 / 协议行为必须实测，不能凭记忆写断言。**
>    反例：写 `convert_pinyin` 断言时曾以为 `first_letter` 是"整词取首字母"，
>    实测 pypinyin 是**逐字**处理 —— `中华` → `z h`（非 `zh`），
>    `initials` 同理为 `zh h`。断言按直觉写会全盘皆错，而项目实现是对的。
>    同类教训：`FastMCP 4.1.0` 对普通异常会加 `Error calling tool 'x': ` 前缀，
>    只有 `ToolError` 分支输出纯净文案 —— 这也是靠 stdio 实测确认的。
>    **任何第三方库或协议的返回值/异常语义，先跑一次最小实验验证，再写断言。**
> 5. **错误文案不引入新的用户可见概念。** 付费层失效一律**静默降级到免费层**，
>    表现为原有的配额超限文案，而不是新造一个 "license invalid" 错误类型 ——
>    用户不需要知道 license 出了什么问题，只需要工具还能用。
> 6. **测试脚本自身的 bug 必须与实现 bug 区分开。**
>    反例：P3 验收中因 `from .gumroad import verify_license_online` 的绑定语义，
>    monkeypatch 模块属性不生效，导致用例结论完全不可信。
>    又因 `tier()` 的铁律是吞掉全部异常，无法用 `pytest.raises` 判断"是否联网"。
>    **验证"某段代码有没有被调用"必须用调用计数，不能靠异常传播。**
> 7. **请求构造必须基于实测。**
>    不得因为"响应里有这个字段"就推测它也是请求参数（详见下方「can_contact 事件」）。
>    **新增任何请求参数前，必须先用探测脚本实测**真实 key 与无效 key
>    两个分支均不返回异常；并用 `ALLOWED_REQUEST_FIELDS` 白名单断言兜住。

### 规约背后的三个真实案例

#### 案例一：子串断言的误伤（规约 3 的延伸）

用 `"print(" not in src` 检查「源码里没有 print」时，P3 新增的
`key_fingerprint()` 函数名里含 `print(` 子串，直接把断言打挂。

**修法**：改用词边界匹配 `re.search(r"(?<![\w.])print\s*\(", src)`。

**教训**：字符串子串断言在代码库变大后必然误伤。检查"某个标识符不存在"
要用词边界；检查"某个词不存在"要评估它在其他语境下是否合法。

#### 案例二：写死版本号的断言必然假失败

`_verify_p1a.py` 里有 `licensing.__version__ == "0.2.0"`。每次 bump 版本都会失败。

**修法不是把 `0.2.0` 改成 `0.3.0`**（那只是把同一个坑推迟到下次），
而是把断言改成**跨文件一致性**：

```python
check("licensing.__version__ == pyproject", licensing.__version__ == pv)
check("server.json 顶层 version 一致", sj["version"] == pv)
check("server.json packages version 一致", all(p["version"] == pv for p in sj["packages"]))
```

这样检查强度不降（版本号写错照样被抓），且以后再 bump 不会假失败。

#### 案例三：sabotage 锚点失配导致"该 FAIL 的用例反而 PASS"

写反向验证时用 `orig.replace(锚点, 破坏代码)` 打 sabotage，
但如果锚点文本随源码演进而变化，`replace` 会**静默不匹配**——
破坏没打进去，用例通过，看起来像"断言有问题"，其实是脚本没打中。

**修法**：每次 replace 后立刻 `assert s != orig, "锚点未匹配（源码已变）"`。

同理，重命名内部函数（如 `_post_verify` → `_post_verify_bytes`）
会让**所有测试脚本里的 patch 静默失效**，表现为大量诡异的失败原因
（如 `reason=http_404`）。改名后必须 grep 全部验证脚本。

---

## can_contact 事件

**一句话**：我曾凭空往 Gumroad 请求体里加了一个不存在的参数。

### 经过

实现 P3 license 验证时，看到 Gumroad 的响应里有 `purchase.can_contact` 字段，
就认为它"看起来像个入参"，于是往请求体里加了 `can_contact: false`
（想表达"不要联系购买者"）。

这是**从响应反推出请求**——响应里有，不代表它能作为请求发出去。

### 为什么没被自动发现

这个错误**不会报错**。Gumroad 对未知字段静默忽略，
所以 `can_contact: false` 发过去毫无异常，功能照常工作。
如果不做反向验证，这个字段会一直躺在代码里。

### 实测证据

```bash
# 探测脚本实际发送的字段
payload = {"license_key": ..., "product_id": ...}     # 没有 can_contact

# 响应里却出现了
"purchase": { ..., "can_contact": true, ... }          # 服务端自动附加
```

`can_contact` 是**响应字段**，由 Gumroad 根据购买者的联系方式设置，
与请求无关。

### 加固

```python
#: 实测确认的 Gumroad verify 请求参数就是这两个
ALLOWED_REQUEST_FIELDS = frozenset({"product_id", "license_key"})
```

⚠️ **这个断言必须放在 `verify_license_online` 的 try 之外**。
最初它写在 `_post_verify` 内部，而 `verify_license_online` 有
`except Exception` 兜住一切 —— `AssertionError` 是 `Exception` 子类，
会被静默吞掉，**加固形同虚设**。这是反向验证 R9 实测发现的。

现在拆成两个函数：`_build_payload()` 负责构造与断言，
`_post_verify_bytes()` 只管发请求。

### 推广

这条经验已写入 README 测试规约第 7 条：
**新增任何请求参数前，必须先用探测脚本实测。**

---

## 实现层踩坑记录

### pypinyin：`first_letter` / `initials` 是逐字处理

**直觉**：这两个 style 应该取整词的首字母/首声母。

**实测**：pypinyin 0.55.0 对它们都是**逐字**处理。

| 输入 | `first_letter` | `initials` | 直觉预期 |
|---|---|---|---|
| `中华` | `z h` | `zh h` | `zh` / `zh` |

**影响**：项目实现与库行为一致（逐字），是**断言写错了**而非实现错。
如果当时按直觉写断言，会全盘皆错并试图"修"一个本来正确的实现。

### pypinyin：非法 style 静默降级，不报错

`lazy_pinyin(text, style="bad")` **不抛异常**，而是静默降级为
`Style.NORMAL`（带调拼音）。

**决策**：本项目在工具入口处**强制白名单校验**，不把非法 style 透传给底层库。
理由：静默降级会让调用方拿到"看起来对但不是我要的结果"的输出，
这类 bug 极难排查。

### pypinyin：`tone2` 的数字标在元音后

`zhong` → `zho1ng`，不是 `zhong1`。

**这是 pypinyin 的既有命名规则，非缺陷**，不是本项目的 bug。
调用方需要注意：`tone2` 与「词尾标数字」的直觉不同。

### jieba：没有 `cut_for_index`，`index` 会静默变 `search`

jieba 0.42.1 顶层**没有** `cut_for_index`，且 `tokenize(mode=...)` 内部
只区分 `default` 与"其他"——传 `index` 会**静默降级为 search**。

**决策**：本项目显式把 `index` 映射到 `cut_for_search`，
行为与 `search` 一致，避免给调用方"index 是独立模式"的错觉。

另外 `search` / `index` 模式下 jieba 内部计算的 `(word, start, end)`
位置信息**不返回**，返回值统一为 `list[str]`。

### pyahocorasick：性能与 wheel 可用性

- 实测 Windows + Python 3.13 有预编译 wheel，无需本地编译工具链
- 4813 词库 × 10 万字文本耗时 **0.008 秒**

### fastmcp：异常类型决定文案有没有前缀

实测 FastMCP 4.1.0 对三类异常的行为：

| 异常 | `isError` | 文案 |
|---|---|---|
| 自定义 `Exception` 子类 | true | `Error calling tool 'x': <msg>` |
| `ValueError` | true | `Error calling tool 'x': <msg>` |
| **`ToolError`** | true | **`<msg>`（无前缀）** |

**决策**：配额/权限异常继承 `fastmcp.exceptions.ToolError`
（它自身继承 `FastMCPError` → `Exception`，仍满足"继承 Exception"的约束），
换取 Agent 能读到无前缀的纯净引导文案。

### Gumroad verify API：实测形态

⚠️ **早期设计文档写过「无效 key 返回 HTTP 200 + success:false」——这个假设是错的。**
2026-10-11 用真实 key 与无效 key 双分支探测后确认：**无效 key 返回 HTTP 404**。

但 `success` 字段**仍必须校验**：HTTP 200 且 `success:false`
是防御「退款 / 吊销」的正确位置，不能只依赖状态码。

其他实测结论：

| 项 | 实测值 |
|---|---|
| 成功响应 | HTTP 200，`application/json; charset=utf-8` |
| 失败响应 | HTTP 404，body 仍为合法 JSON |
| 顶层字段 | `success` (bool) / `uses` (int) / `purchase` (object) |
| `uses` 语义 | **已用次数**（累计 verify 调用数），非剩余。顶层 int |
| `expires_at` | **不存在**。无任何过期字段，有效性靠 `refunded`/`disputed`/`chargebacked` |
| `refunded` 等 | 实测是真正的 JSON **bool**，不是 null（三方独立客户端交叉验证一致） |
| 明文回显 | ⚠️ 响应里**含明文 `purchase.license_key`**，以及 `email`/`referrer`/`ip_country` |
| Content-Type | JSON body 与 form-urlencoded **都被接受** |
| 测试订单 | `purchase.test == true` 表示沙箱购买，非真实付款 |

---

## 开发流程

### 本地验收

```bash
npx @modelcontextprotocol/inspector \
  ./.venv/Scripts/python.exe server.py
```

浏览器打开提示的地址（默认 http://localhost:6274），在 Tools 面板调用工具。

### 验收脚本

全部位于项目根目录，**不提交仓库**（`.gitignore` 已覆盖）：

| 脚本 | 覆盖范围 |
|---|---|
| `_verify_p1a.py` | 路径解析、HMAC、防回拨、剪枝、降级、文案四要素 |
| `_verify_p1c.py` | 闸门接入、hello_world 豁免、@wrap_quota 边界 |
| `_verify_p1d.py` | 设备记录（含 stdio 真实会话） |
| `_verify_p1_regress.py` | stdio 全量回归 |
| `_verify_p3.py` | license 在线判据、五层决策、D1–D5 落地、隐私纪律、请求白名单 |
| `_verify_p3_sabotage.py` | 反向验证 R1–R9 |

运行方式：`.venv\Scripts\python.exe _verify_p3.py`

### 硬性约束（勿破坏）

1. stdio transport，本地不开放任何端口。
2. 所有日志一律写 stderr；禁止 print 到 stdout（会污染 JSON-RPC 协议流）。
3. **license 验证只在 `main()` 启动时执行一次**，绝不接入任何工具函数
   （含 `hello_world`），结果缓存到模块级 `_tier`。
4. `licensing/` 对 MCP 框架**零依赖** —— MCP 耦合只允许出现在 `server.py`
   的 `@wrap_quota` 装饰器里。可用 AST 校验。
5. 状态文件**不含任何明文凭证**。默认连 license key 明文也不存。

### 分阶段推进约定

工作按密封批次推进，每批次以「验证 + 反向 sabotage」作为门槛，
通过后才推进下一批次。批次内不混语义变更。

已完成的阶段：

| 阶段 | 内容 |
|---|---|
| P1-a | StateStore（HMAC、防回拨、7 天剪枝） |
| P1-b | QuotaGuard（次数限制、参数上限） |
| P1-c | 5 个工具接入闸门（`hello_world` 豁免） |
| P1-d | 设备记录（仅告警不拒绝，允许 3 台） |
| P2 | v0.2.0 发布 |
| P3 | License 验证（启动时一次 + 24h 缓存 + 7 天宽限） |

### 设计边界：这个项目防什么、不防什么

chinese-nlp-mcp 是 MIT 开源的本地软件。它的商业模型是**软性付费墙**，
不是 DRM。这是产品定位的选择，不是待修复的缺陷 —— 我们认为把它讲清楚
比含糊过去更有价值，所以在这里明说。

**它能做什么**

- 让愿意付费的人，在一分钟内用上批量 API、长文本、自定义词典
- 让不买的人，能一直用到全部基础功能（五个工具都免费，只是有日次数上限）

**它不做什么**

- 它不是 DRM。**MIT 协议意味着任何人都可以 fork、修改、移除这些限制**，
  我们不会、也不打算用技术手段阻止你。那既做不到，也不该做。
- 它不上报任何使用数据。没有遥测、没有崩溃上报、没有活跃度统计。
  你不用它，我们也不知道。

**关于计数机制的诚实说明**

每日计数有 HMAC 签名保护，它的作用是**防止误操作和无意重置**
（比如系统时间被回拨后计数错乱、云盘同步把旧状态覆盖回来）。
它**不是**用来对抗蓄意破解的 —— 源码在本地，任何本地机制都只能提高成本，
不能提供密码学意义上的保证。这我们说在前面，不藏着。

**已知的边界，以及为什么接受**

- 纯本地状态文件无法区分"第一次运行"和"文件被删除"。我们用 7 天历史窗口
  缓解这种情况，但没有根治。**根因是本地架构本身** —— 如果我们能区分，
  意味着我们能感知到你的文件操作，那才是我们不想做的。
- 设备记录只能看到本机的设备标识变化，看不到另一台机器上的状态。
  要真正检测跨机共享就必须上报，而这与"不上报任何数据"的承诺冲突。
  **我们选择不检测。** 一个 $19 的产品不值得用隐私去换。
- License 缓存在本地，清掉它只会让下次启动多打一次验证请求，
  不影响任何权益判定。

**我们做了防误伤的设计**

超过 3 台设备时**只告警、不拒绝**。云主机重装、Docker 重建、VM 迁移、
双系统、换主板、团队共用构建机 —— 都会让设备数超过 3。拦住这些场景
造成的损失，比多收几个人的钱大得多。