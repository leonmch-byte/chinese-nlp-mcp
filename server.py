"""chinese-nlp-mcp —— 中文 NLP MCP Server（stdio 本地模式）。

面向海外开发者的中文 NLP 能力封装。

硬性约束（勿破坏）：
1. stdio transport，本地不开放任何端口。
2. 所有日志一律写 stderr；禁止 print 到 stdout（会污染 JSON-RPC 协议流）。
3. 每个工具独立函数，统一错误处理，返回可读错误信息。
4. detect_sensitive_words 只接受用户自定义词库，默认词库为空。
5. 付费层 P1：纯本地计量，零网络请求。商业状态异常由 @wrap_quota 转ToolError。
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
from licensing.quota import QuotaGuard
from licensing.store import StateStore
from licensing.tier import TierProvider
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
        "所有工具均为纯本地推理，不发起网络请求。"
    ),
)


# ---------------------------------------------------------------------------
# License 占位（Day 1 不做校验）
# ---------------------------------------------------------------------------
# 刻意不注册为 MCP 工具：付费层方案未定，Day 6 再决定是否对外暴露。


def check_license() -> dict:
    """查询当前许可证计划。

    内部函数，暂不暴露为 MCP 工具。Day 1 占位实现：暂不校验，恒返回 free 计划。
    P1 起由 TierProvider 提供真实 tier 判定（仍无网络请求）。
    """
    logger.info("check_license called -> plan=free (placeholder)")
    return {"plan": "free", "valid": True, "placeholder": True}


# ---------------------------------------------------------------------------
# 付费层闸门（P1-c 接入）
# ---------------------------------------------------------------------------
# 设计要点：
# 1. hello_world **不接入**配额 —— 健康检查被拦会让客户端误判服务器故障。
# 2. QuotaExceeded / ProFeatureRequired 均继承 Exception（licensing/ 对 MCP 框架
#    零依赖），由下面的 @wrap_quota 统一转 ToolError以拿到无前缀文案。
# 3. QuotaGuard 内部除这两类异常外全部吞掉放行 —— 计数器故障不影响可用性。
# 4. P1 无任何网络请求，tier 恒为 free。
# 5. P1-d 设备记录**仅在 main() 启动时调用一次**，绝不接入任何工具函数：
#    包括 hello_world —— 告警只写 stderr，不改变任何工具的 isError 状态。


_state_store = StateStore()
_tier_provider = TierProvider()
_quota = QuotaGuard(_state_store, _tier_provider)

logger.info(f"licensing initialized: {_tier_provider.describe()}")


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

    保持 stdio transport + 关闭 banner：纯本地运行、不开放端口、不联网。
    """
    # P1-d 设备记录：仅在启动时检查一次（不接入任何工具函数）。
    # check_device 保证永不抛异常、永不拒绝，只可能写一条 stderr 警告。
    # 放在 mcp.run() 之前，保证告警出现在服务就绪之前。
    _device_status = check_device()
    logger.info(f"device check: {_device_status}")

    # transport="stdio" 是 fastmcp 的默认值，此处显式声明以表明意图。
    # show_banner=False 关闭 ASCII banner，纯本地运行不产生任何网络请求。
    logger.info("starting chinese-nlp-mcp on stdio transport")
    mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
