"""chinese-nlp-mcp —— 中文 NLP MCP Server（stdio 本地模式）。

面向海外开发者的中文 NLP 能力封装。

硬性约束（勿破坏）：
1. stdio transport，本地不开放任何端口。
2. 所有日志一律写 stderr；禁止 print 到 stdout（会污染 JSON-RPC 协议流）。
3. 每个工具独立函数，统一错误处理，返回可读错误信息。
4. detect_sensitive_words 只接受用户自定义词库，默认词库为空。
5. 暂不做 license 校验，保留占位函数，恒返回 free 计划。
"""

from __future__ import annotations

import logging
import os
import sys

# 必须在导入 fastmcp 之前设置：fastmcp 在 Settings 初始化时读取环境变量。
# 关掉版本检查，避免每次启动都向 pypi.org 发请求（本项目承诺纯本地、不联网）。
os.environ["FASTMCP_CHECK_FOR_UPDATES"] = "off"
os.environ.setdefault("FASTMCP_SHOW_SERVER_BANNER", "false")

from fastmcp import FastMCP

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
    """
    logger.info("check_license called -> plan=free (placeholder)")
    return {"plan": "free", "valid": True, "placeholder": True}


# ---------------------------------------------------------------------------
# Day 1 验收工具
# ---------------------------------------------------------------------------


@mcp.tool
def hello_world() -> str:
    """健康检查工具。返回固定文本，用于验证 MCP 连接与工具注册是否正常。"""
    logger.info("hello_world called")
    return "Hello from Chinese NLP MCP"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # transport="stdio" 是 fastmcp 的默认值，此处显式声明以表明意图。
    # show_banner=False 关闭 ASCII banner，纯本地运行不产生任何网络请求。
    logger.info("starting chinese-nlp-mcp on stdio transport")
    mcp.run(transport="stdio", show_banner=False)
