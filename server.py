"""chinese-nlp-mcp —— 中文 NLP MCP Server（stdio 本地模式）。

面向海外开发者的中文 NLP 能力封装。

硬性约束（勿破坏）：
1. stdio transport，本地不开放任何端口。
2. 所有日志一律写 stderr；禁止 print 到 stdout（会污染 JSON-RPC 协议流）。
3. 每个工具独立函数，统一错误处理，返回可读错误信息。
4. detect_sensitive_words 只接受用户自定义词库，默认词库为空。
5. 付费层：商业状态异常由 @wrap_quota 转 ToolError。
6. **P3起可能发出唯一的网络请求**：启动时向 Gumroad 验证 license key
   （仅当用户配置了 CHINESE_NLP_LICENSE_KEY 时）。24h 缓存，
   工具调用热路径零网络、零磁盘 I/O。未配置 key 时行为与 P1 完全一致（纯离线）。
7. **license 验证只在 main() 启动时执行一次**，绝不接入任何工具函数
   （含 hello_world），结果缓存到模块级 ``_tier``。
"""

from __future__ import annotations

import functools
import logging
import os
import sys

# 必须在导入 fastmcp 之前设置：fastmcp 在 Settings 初始化时读取环境变量。
# 关掉版本检查，避免每次启动都向 pypi.org 发请求（本项目承诺纯本地、不联网）。
os.environ["FASTMCP_CHECK_FOR_UPDATES"] = "off"
os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from licensing.devices import check_device
from licensing.errors import ProFeatureRequired, QuotaExceeded
from licensing.license import LicenseVerifier
from licensing.quota import QuotaGuard
from licensing.store import StateStore
from tools.keywords import extract_keywords as _extract_keywords
from tools.pinyin import convert_pinyin as _convert_pinyin
from tools.segment import segment_chinese as _segment_chinese
from tools.sensitive import detect_sensitive_words as _detect_sensitive_words

# ---------------------------------------------------------------------------
# 日志：强制走 stderr，严禁污染 stdout
# ---------------------------------------------------------------------------

logger = logging.getLogger("chinese_nlp_mcp")


def _init_logging() -> None:
    """把 root logger 全部挂到 stderr。

    注意：这里显式传 stream=sys.stderr，不依赖 logging 的默认行为，
    因为在部分环境下默认 handler 可能被宿主进程改写。
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_init_logging()

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="chinese-nlp-mcp",
    instructions=(
        "中文 NLP 能力包：分词、关键词提取、拼音转换、自定义敏感词检测。"
        "所有工具均为纯本地推理。\n"
        "隐私：未配置 license key 时完全离线，无网络请求、无遥测，"
        "文本永不离开本机；配置了 Pro key 时，仅在启动时向 Gumroad 校验一次"
        "（缓存 24 小时），只发送 product_id 与 license_key，"
        "不发送文本内容、使用统计或设备标识。工具调用本身始终完全离线。"
    ),
)


# ---------------------------------------------------------------------------
# License 查询
# ---------------------------------------------------------------------------
# 刻意不注册为 MCP 工具：工具列表是 Registry 展示面，
# 暴露 license 查询会引导用户频繁调用它（而它不是能力入口）。
# 需要诊断时用环境变量 CHINESE_NLP_LICENSE_DEBUG=1，
# main() 会把 status() 打到 stderr。


def check_license() -> dict:
    """查询当前 tier 的本地快照（不联网）。

    读的是 main() 启动时算好的模块级 ``_tier``，**不发任何网络请求** ——
    即使传了真key 也不会重新验证（要重新验证请重启进程，或清license_cache.json）。
    """
    status = _license_verifier.status()
    return {
        "tier": _tier,
        "valid": _tier == "paid",
        "cache_ttl_hours": status.get("cache_ttl_hours"),
        "grace_days": status.get("grace_days"),
        "cache_verified_at": status.get("cache_verified_at"),
        "sale_id": status.get("sale_id"),
    }


# ---------------------------------------------------------------------------
# 付费层闸门（P1-c 接入，P3 接 license）
# ---------------------------------------------------------------------------
# 设计要点：
# 1. hello_world **不接入**配额 —— 健康检查被拦会让客户端误判服务器故障。
# 2. QuotaExceeded / ProFeatureRequired 均继承 Exception（licensing/ 对 MCP 框架
#    零依赖），由下面的 @wrap_quota 统一转 ToolError以拿到无前缀文案。
# 3. QuotaGuard 内部除这两类异常外全部吞掉放行 —— 计数器故障不影响可用性。
# 4. P1-d 设备记录**仅在 main() 启动时调用一次**，绝不接入任何工具函数：
#    包括 hello_world —— 告警只写 stderr，不改变任何工具的 isError 状态。
# 5. **P3：license 验证同样只在 main() 启动时执行一次**，
#    绝不接入任何工具函数、绝不在每次 tools/call 时读文件或发网络请求。
#    启动结果写进模块级``_tier``，QuotaGuard 通过下面的
#    ``_tier_provider`` 对象读内存值 —— 每次调用零I/O。

_state_store = StateStore()

#: 启动时验证一次得到的 tier 值（"free" / "paid"）。
#: 初始为 "free"（保守）；main() 启动时若配置了 license 会被覆写。
_tier: str = "free"


class _StartupTierProvider:
    """把启动时算好的 tier 交给 QuotaGuard。

    为什么不在每次调用时调 ``LicenseVerifier.tier()``：
    - 会每次读 license_cache.json（磁盘 I/O），而 24h 内结果本就不会变；
    - ``tier()`` 内部有进程内记忆，但多一层调用没收益；
    - 万一将来缓存逻辑变动，也不会在工具调用的热路径上引入意外 I/O。

    这是最小实现：只读一个模块级字符串，永不抛异常。
    """

    def tier(self) -> str:
        return _tier

    def is_paid(self) -> bool:
        return _tier == "paid"

    def describe(self) -> dict:
        return {"tier": _tier, "source": "startup-verified"}


_tier_provider = _StartupTierProvider()
_license_verifier = LicenseVerifier()
_quota = QuotaGuard(_state_store, _tier_provider)

logger.info("licensing initialized (tier=free, pending startup license check)")


# ---------------------------------------------------------------------------
# @wrap_quota —— MCP 框架耦合的唯一出口
# ---------------------------------------------------------------------------
# 分层设计：licensing/ 对 MCP 框架零依赖（QuotaExceeded 只继承 Exception），
# 但 FastMCP 4.1.0 对普通异常会加 "Error calling tool 'x': " 前缀，
# 而四要素引导文案需要 Agent 读到**无前缀**的纯净文本
# —— 实测只有 fastmcp.exceptions.ToolError 分支输出纯净文案。
#
# 因此本装饰器是唯一把「商业状态异常」翻译成「MCP 框架异常」的地方：
#   QuotaExceeded / ProFeatureRequired  ->  ToolError（文案原样透出）
#   其他异常                            ->  照常抛出，保持原有语义
#
# ⚠️ 用 functools.wraps 保留原函数元信息，否则 FastMCP 无法正确提取
#    参数 schema（docstring 决定 description，签名决定 properties）。
def wrap_quota(fn):
    """把配额/权限异常转为 ToolError，保持引导文案无前缀。"""

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (QuotaExceeded, ProFeatureRequired) as exc:
            logger.info(f"quota gate: {type(exc).__name__} for {fn.__name__}")
            raise ToolError(str(exc)) from exc

    return _wrapped


# ---------------------------------------------------------------------------
# Day 1 验收工具
# ---------------------------------------------------------------------------


@mcp.tool
def hello_world() -> str:
    """健康检查工具。返回固定文本，用于验证 MCP 连接与工具注册是否正常。"""
    logger.info("hello_world called")
    return "Hello from Chinese NLP MCP"


# ---------------------------------------------------------------------------
# 中文分词
# ---------------------------------------------------------------------------


@mcp.tool
@wrap_quota
def segment_chinese(text: str, mode: str = "default") -> list[str]:
    """对中文文本分词，返回词列表。

    Args:
        text: 待分词的中文文本。
        mode: 分词模式。``default`` 标准分词；``search`` 搜索模式，
            会额外切出词内部的 2/3 元组；``index`` 索引模式，
            行为与 ``search`` 一致。

    Returns:
        分词结果列表。search / index 模式下 jieba 内部计算的位置信息不返回。
    """
    _quota.check("segment_chinese", {"text": text, "mode": mode})
    return _segment_chinese(text=text, mode=mode)


# ---------------------------------------------------------------------------
# 中文转拼音
# ---------------------------------------------------------------------------


@mcp.tool
@wrap_quota
def convert_pinyin(
    text: str, style: str = "tone", separator: str = " "
) -> str:
    """将中文文本转换为拼音字符串。

    Args:
        text: 待转换的中文文本。
        style: ``tone`` 带声调符号（zhōng）；``tone2`` 数字声调（zho1ng）；
            ``initials`` 声母（zh）；``first_letter`` 首字母（z）。
        separator: 词与词之间的拼接分隔符，默认空格。

    Returns:
        以 separator 拼接的拼音字符串。
    """
    _quota.check("convert_pinyin",
                 {"text": text, "style": style, "separator": separator})
    return _convert_pinyin(text=text, style=style, separator=separator)


# ---------------------------------------------------------------------------
# 关键词提取
# ---------------------------------------------------------------------------


@mcp.tool
@wrap_quota
def extract_keywords(text: str, topN: int = 10) -> list[dict]:
    """用 TF-IDF 从中文文本中提取关键词，按权重降序返回。

    Args:
        text: 待分析的文本，可中英混合。
        topN: 返回关键词数量上限。超过可提取词数时返回全部词，不报错。

    Returns:
        形如 ``[{"word": "北京", "weight": 1.55}, ...]`` 的列表。
        weight 为 TF-IDF 原始分，未归一化，可大于 1.0。
    """
    _quota.check("extract_keywords", {"text": text, "topN": topN})
    return _extract_keywords(text=text, topN=topN)


# ---------------------------------------------------------------------------
# 自定义敏感词检测
# ---------------------------------------------------------------------------


@mcp.tool
@wrap_quota
def detect_sensitive_words(
    text: str, words: list[str] | None = None
) -> dict:
    """在文本中检测调用方自定义的敏感词。

    ⚠️ 本工具**不含任何内置词库**，words 是唯一检测依据。
    传空列表或 None 等同于不检测，直接返回 {"matches": [], "clean": true}。

    重叠匹配策略：返回**全部**命中，不去重、不做最长/最短优先裁剪。
    调用方是自己词库的负责人，最清楚"命中什么"才是关心的信号；
    拿到全部命中后，可按 index 自行裁剪或聚合。

    Args:
        text: 待检测文本。
        words: 调用方自定义词库。

    Returns:
        {"matches": [{"word": str, "index": int}, ...], "clean": bool}。
        index 为词起始位置的字符索引（中文按 1 字计）。
    """
    _quota.check("detect_sensitive_words", {"text": text, "words": words})
    return _detect_sensitive_words(text=text, words=words)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    """控制台脚本入口。

    PyPI 入口点 ``chinese-nlp-mcp = "server:main"`` 绑定到此函数，
    使用户可直接 ``uvx chinese-nlp-mcp`` 或 ``chinese-nlp-mcp`` 启动。

    保持 stdio transport + 关闭 banner：纯本地运行、不开放端口。
    """
    # P3 license 验证：**仅在启动时执行一次**，绝不接入任何工具函数。
    #
    # 为什么放这里而不是装饰器里：
    # - 24h 缓存意味着每次启动最多一次网络请求，工具调用热路径零I/O；
    # - LicenseVerifier.tier() 的铁律是永不抛异常、永不返回 None、最多阻塞 8s，
    #   即便验证彻底失败也只是静默降级到 free，绝不影响服务器可用性；
    # - hello_world 也不接入 —— 健康检查必须永远可用。
    global _tier
    try:
        _tier = _license_verifier.tier()
        logger.info(f"license check: {_license_verifier.status()}")
    except Exception as exc:  # noqa: BLE001 — 兜底，绝不阻断启动
        logger.warning(f"license check failed, serving free tier ({type(exc).__name__})")
        _tier = "free"

    # P1-d 设备记录：仅在启动时检查一次（不接入任何工具函数）。
    # check_device 保证永不抛异常、永不拒绝，只可能写一条 stderr 警告。
    # 放在 mcp.run() 之前，保证告警出现在服务就绪之前。
    _device_status = check_device()
    logger.info(f"device check: {_device_status}")

    # transport="stdio" 是 fastmcp 的默认值，此处显式声明以表明意图。
    # show_banner=False 关闭 ASCII banner。
    logger.info(f"starting chinese-nlp-mcp on stdio transport (tier={_tier})")
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
