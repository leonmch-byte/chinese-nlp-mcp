"""付费层异常定义。

设计约束（用户明确指定）：
- QuotaExceeded 继承自 **Exception**，不继承 ValueError / RuntimeError。
  理由：项目既有约定是「参数错 → ValueError，内部错 → RuntimeError」，
  而配额超限两者都不是 —— 它是**商业状态**。独立基类避免语义混淆，
  也让 FastMCP 侧能精确捕获并转成引导文案。
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

    属商业状态，非参数错误也非内部故障，故独立基类。
    FastMCP 捕获后转 ``isError: true`` + 引导文案。
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
    两者都会被 FastMCP 转成 isError，但文案语义不同。
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