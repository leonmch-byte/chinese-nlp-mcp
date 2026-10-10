"""中文转拼音工具（Day 3 实现）。

计划签名：convert_pinyin(text: str, style: str = "tone", separator: str = " ") -> str
style 支持 "tone" / "tone2" / "initials" / "first_letter"，底层走 pypinyin。
"""

from __future__ import annotations


def convert_pinyin(
    text: str, style: str = "tone", separator: str = " "
) -> str:
    """占位实现，Day 3 替换为 pypinyin 真实转换。"""
    raise NotImplementedError("convert_pinyin 将在 Day 3 实现")
