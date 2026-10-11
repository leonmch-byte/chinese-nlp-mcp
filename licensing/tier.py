"""TierProvider —— 当前 tier 判定。

P1 恒为 free。P3 接入 Gumroad 验证后，只需替换 ``tier()`` 实现，
闸门逻辑与工具代码零改动。
"""

from __future__ import annotations

import logging

log = logging.getLogger("chinese_nlp_mcp.licensing")

FREE = "free"
PAID = "paid"


class TierProvider:
    """tier 判定。

    P1: 恒返回 free（无网络请求）。
    P3: 改为基于 ``Verifi`` 结果返回，且缓存 24h + 断网宽限 7 天。
    """

    def __init__(self, forced: str | None = None) -> None:
        self._forced = forced

    def tier(self) -> str:
        """返回 ``free`` 或 ``paid``。P1 恒 free。"""
        if self._forced in (FREE, PAID):
            return self._forced
        return FREE

    def is_paid(self) -> bool:
        return self.tier() == PAID

    def describe(self) -> dict:
        """供日志/调试。P1 无敏感信息。"""
        return {
            "tier": self.tier(),
            "source": "p1-placeholder",
            "network_calls": 0,
        }