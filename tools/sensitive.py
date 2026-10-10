"""自定义敏感词检测工具（Day 5 实现）。

计划签名：detect_sensitive_words(text: str, words: list[str] = []) -> dict
返回 {"matches": [{"word": ..., "index": ...}], "clean": bool}

设计红线：本模块**不内置任何词库**。词库完全由调用方通过 words 参数传入，
默认空列表即为不做任何检测。严禁在此写入内置敏感词。
"""

from __future__ import annotations


def detect_sensitive_words(text: str, words: list[str] | None = None) -> dict:
    """占位实现，Day 5 替换为 AC 自动机真实检测。"""
    raise NotImplementedError("detect_sensitive_words 将在 Day 5 实现")
