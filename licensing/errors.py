"""付费层异常定义。

⚠️ **本模块刻意不依赖任何 MCP 框架**（不import fastmcp / mcp）。
把「商业状态异常」与「MCP 框架」解耦，是P1-d 前的解耦修正项。

设计约束（用户明确指定）：
- QuotaExceeded 继承自 **Exception**，不继承 ValueError / RuntimeError。
  理由：项目既有约定是「参数错 → ValueError，内部错 → RuntimeError」，
  而配额超限两者都不是 —— 它是**商业状态**。

为什么不用 ToolError（曾试过，已回退）：
  实测 FastMCP 4.1.0 对普通异常会加 ``Error calling tool 'x': `` 前缀，
  只有 ToolError 分支输出纯净文案。当时让 QuotaExceeded 直接继承
  ``fastmcp.exceptions.ToolError`` 来拿无前缀文案，但那会让整个
  ``licensing/`` 依赖 MCP 框架 —— 违背分层原则。

  现改为：**licensing/ 保持纯净（只继承 Exception），
  由 server.py 的 ``@wrap_quota`` 装饰器捕获 QuotaExceeded
  并转成 ToolError**。MCP 框架耦合集中在 server.py 一层。
"""

from __future__ import annotations

UPGRADE_URL = "https://gumroad.com/l/chinese-nlp-mcp-pro"
RESET_AT_UTC = "00:00 UTC"

_PRO_LINES = (
    "Pro unlocks: batch API (100 texts per call), "
    "custom dictionaries, priority support."
)
_PRICE_LINE = "$19 one-time — no subscription."


def _build_quota_message(
    tool_name: str, limit: int, reset_at: str, upgrade_url: str
) -> str:
    """配额超限文案。强制包含四要素。

    ① 当前限制  ② 重置时间  ③ 升级权益  ④ 升级链接
    测试中断言任一要素缺失即 FAIL。
    """
    return "\n".join(
        [
            f"Daily quota exceeded for {tool_name} ({limit}/day).",
            f"Limits reset at {reset_at}.",
            _PRO_LINES,
            _PRICE_LINE,
            f"Upgrade: {upgrade_url}",
        ]
    )


class QuotaExceeded(Exception):
    """配额超限。

    属商业状态，非参数错误也非内部故障，故直接继承 ``Exception``。

    ⚠️ 本类**刻意不继承 fastmcp.ToolError**：保持 ``licensing/``
    不依赖 MCP 框架。MCP 框架耦合集中在 server.py 的 ``@wrap_quota``，
    由该装饰器捕获本异常并转成 ToolError，以获得无前缀的纯净文案。
    """

    def __init__(
        self,
        tool_name: str,
        limit: int,
        reset_at: str = RESET_AT_UTC,
        upgrade_url: str = UPGRADE_URL,
        used: int | None = None,
        message: str | None = None,
    ) -> None:
        if message is None:
            message = _build_quota_message(tool_name, limit, reset_at, upgrade_url)
        super().__init__(message)
        self.tool_name = tool_name
        self.limit = limit
        self.reset_at = reset_at
        self.upgrade_url = upgrade_url
        self.used = used

    def to_dict(self) -> dict:
        """供日志与测试断言使用。"""
        return {
            "tool_name": self.tool_name,
            "limit": self.limit,
            "used": self.used,
            "reset_at": self.reset_at,
            "upgrade_url": self.upgrade_url,
        }


class ProFeatureRequired(Exception):
    """Pro 功能未解锁（免费层调用付费专属能力）。

    与 QuotaExceeded 分开：这是**功能权限**问题，不是**次数**问题。
    同样保持对 MCP 框架零依赖，由 server.py 的 ``@wrap_quota`` 转换。
    """

    #: 用户指定的固定措辞
    DEFAULT_MESSAGE = (
        "Batch processing is a Pro feature. Upgrade at "
        f"{UPGRADE_URL} — $19 one-time, includes batch API, "
        "custom dictionaries, and priority support."
    )

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.DEFAULT_MESSAGE)
        self.upgrade_url = UPGRADE_URL