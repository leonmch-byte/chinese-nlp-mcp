"""QuotaGuard —— 唯一的计费闸门（P1-b）。

职责：查 tier → 校验参数上限 → 扣次数。
它**不知道** license key 从哪来，也不关心网络。

铁律：任何内部异常都不允许让服务器不可用 —— 全部吞掉并放行，只记 stderr。
唯一允许抛出的���是 ``QuotaExceeded``（商业状态，由上层转 isError）。
"""

from __future__ import annotations

import logging

from .errors import QuotaExceeded
from .gumroad import UPGRADE_URL
from .store import StateStore, is_full_sentinel, today_str

log = logging.getLogger("chinese_nlp_mcp.licensing")

# ---- 免费层每日次数（D2：先按此值，观察 1~2 周真实使用再调）----
FREE_LIMITS: dict[str, int | None] = {
    "hello_world": None,  # 健康检查永不拦
    "segment_chinese": 500,
    "convert_pinyin": 300,
    "extract_keywords": 100,
    "detect_sensitive_words": 200,
}

# ---- 免费层参数上限（第二道闸门，防单次超长文本绕过次数限制）----
FREE_MAX_TEXT_LEN = 20_000
FREE_MAX_WORDS = 1_000
FREE_MAX_TOPN = 50

# ---- 付费层软上限（D3：个人用户永远碰不到，仅防自动化转售）----
PAID_SOFT_CAP = 50_000
PAID_MAX_TEXT_LEN = 200_000

TIER_FREE = "free"
TIER_PAID = "paid"


class QuotaGuard:
    """配额闸门。

    ``tier_provider`` 为 None 时按free 处理（P1 恒free）。
    """

    def __init__(self, store: StateStore, tier_provider=None) -> None:
        self._store = store
        self._tier = tier_provider

    # ------------------------------------------------------------------
    def tier(self) -> str:
        try:
            return self._tier.tier() if self._tier else TIER_FREE
        except Exception:
            return TIER_FREE

    def max_text_len(self) -> int:
        return PAID_MAX_TEXT_LEN if self.tier() == TIER_PAID else FREE_MAX_TEXT_LEN

    def daily_limit(self, tool: str) -> int | None:
        """返回该工具的日限。None = 不限。"""
        if self.tier() == TIER_PAID:
            return PAID_SOFT_CAP
        return FREE_LIMITS.get(tool)

    def remaining_today(self, tool: str) -> int:
        """今日剩余次数。付费层按软上限计算。"""
        limit = self.daily_limit(tool)
        if limit is None:
            return 10**9  # 视为不限
        used = self._safe_count(tool)
        return max(0, limit - used)

    # ------------------------------------------------------------------
    def check(self, tool: str, args: dict | None = None) -> None:
        """调用前闸门。

        合规→ 放行并扣次数。
        超限 / 参数超上限 → 抛 ``QuotaExceeded``。
        其他内部异常 → 吞掉并放行（可用性优先）。
        """
        try:
            args = args or {}

            # 付费层：只校验输入长度上限，不限次数
            if self.tier() == TIER_PAID:
                self._check_text_len(args, PAID_MAX_TEXT_LEN, tool)
                self._consume(tool, 1)
                return

            limit = FREE_LIMITS.get(tool)
            if limit is None:
                # hello_world：不限次数，但仍受输入上限约束
                self._check_arg_caps(tool, args)
                return

            self._check_arg_caps(tool, args)

            used = self._safe_count(tool, limit)
            if used >= limit:
                raise QuotaExceeded(tool_name=tool, limit=limit, used=used)

            self._consume(tool, 1)

        except QuotaExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — 可用性优先，全部放行
            log.warning(f"quota: internal error, allowing call ({type(exc).__name__})")

    # ------------------------------------------------------------------
    def _safe_count(self, tool: str, limit: int | None = None) -> int:
        """取今日已用次数。哨兵值（回拨/篡改）按满额处理。"""
        try:
            n = self._store.get_count(today_str(), tool)
            if is_full_sentinel(n):
                return limit if limit is not None else (FREE_LIMITS.get(tool) or 10**9)
            return n
        except Exception:
            return 0

    def _consume(self, tool: str, n: int) -> None:
        try:
            self._store.increment(today_str(), tool, n)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"quota: consume failed ({type(exc).__name__})")

    # ------------------------------------------------------------------
    def _check_arg_caps(self, tool: str, args: dict) -> None:
        """免费层参数上限校验。

        这些**不是**配额问题，但复用 QuotaExceeded 以统一引导文案。
        """
        self._check_text_len(args, FREE_MAX_TEXT_LEN, tool)

        if tool == "detect_sensitive_words":
            words = args.get("words") or []
            if len(words) > FREE_MAX_WORDS:
                raise QuotaExceeded(
                    tool_name=tool,
                    limit=FREE_MAX_WORDS,
                    message=(
                        f"words list too large for free tier "
                        f"({len(words)} > {FREE_MAX_WORDS}).\n"
                        "Limits reset at 00:00 UTC.\n"
                        "Pro unlocks: batch API (100 texts per call), "
                        "custom dictionaries, priority support.\n"
                        "$19 one-time — no subscription.\n"
                        f"Upgrade: {UPGRADE_URL}"
                    ),
                )

        if tool == "extract_keywords":
            topn = args.get("topN") or 0
            if topn > FREE_MAX_TOPN:
                raise QuotaExceeded(
                    tool_name=tool,
                    limit=FREE_MAX_TOPN,
                    message=(
                        f"topN too large for free tier "
                        f"({topn} > {FREE_MAX_TOPN}).\n"
                        "Limits reset at 00:00 UTC.\n"
                        "Pro unlocks: batch API (100 texts per call), "
                        "custom dictionaries, priority support.\n"
                        "$19 one-time — no subscription.\n"
                        f"Upgrade: {UPGRADE_URL}"
                    ),
                )

    def _check_text_len(self, args: dict, cap: int, tool: str) -> None:
        text = args.get("text") or ""
        if isinstance(text, str) and len(text) > cap:
            raise QuotaExceeded(
                tool_name=tool,
                limit=cap,
                message=(
                    f"text too long for free tier "
                    f"({len(text)} chars > {cap}).\n"
                    "Limits reset at 00:00 UTC.\n"
                    "Pro unlocks: batch API (100 texts per call), "
                    "custom dictionaries, priority support.\n"
                    "$19 one-time — no subscription.\n"
                    f"Upgrade: {UPGRADE_URL}"
                ),
            )

    # ------------------------------------------------------------------
    def check_batch(self, tool: str, size: int) -> None:
        """批量调用闸门（P2' 使用）。

        - 免费层：直接拒绝（Pro 功能）
        - 付费层：按条数扣配额，不足则抛 QuotaExceeded
        """
        if self.tier() != TIER_PAID:
            from .errors import ProFeatureRequired

            raise ProFeatureRequired()

        if self.remaining_today(tool) < size:
            raise QuotaExceeded(
                tool_name=tool,
                limit=PAID_SOFT_CAP,
                message=(
                    f"batch requires {size} calls but only "
                    f"{self.remaining_today(tool)} remain today.\n"
                    "Limits reset at 00:00 UTC.\n"
                    "Pro unlocks: batch API (100 texts per call), "
                    "custom dictionaries, priority support.\n"
                    "$19 one-time — no subscription.\n"
                    f"Upgrade: {UPGRADE_URL}"
                ),
            )