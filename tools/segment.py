"""中文分词工具（Day 2 实现）。

计划签名：segment_chinese(text: str, mode: str = "default") -> list[str]
mode 支持 "default" / "search" / "index"，底层走 jieba。
"""

from __future__ import annotations


def segment_chinese(text: str, mode: str = "default") -> list[str]:
    """占位实现，Day 2 替换为 jieba 真实分词。"""
    raise NotImplementedError("segment_chinese 将在 Day 2 实现")
