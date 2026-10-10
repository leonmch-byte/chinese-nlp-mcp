"""关键词提取工具（TF-IDF）。

底层 jieba.analyse。已实测核对的 API 事实（jieba 0.42.1）：

- 真实签名 ``extract_tags(sentence, topK=20, withWeight=False, allowPOS=(), withFlag=False)``
  —— 参数名是 ``topK`` 而非 ``topN``；``withWeight=True`` 时返回
  ``list[tuple[str, float]]``，否则返回 ``list[str]``。
- ``weight`` 是 **TF-IDF 原始分，未归一化**：实测值域约 0.8 ~ 6.0，
  可以大于 1.0（例："天安门广场" → 1.6316）。它反映的是该词在当前语料中的
  重要程度，不是 0~1 的概率或百分比。本工具原样透传，不做归一化处理。
- 返回顺序**已按权重降序**，无需再次排序。
- ``topK`` 超过可提取词数时，**返回全部词而非报错**（实测 topK=100 只有 5 个词）。

本项目对外签名为 ``extract_keywords(text, topN=10)``：把底层 ``topK``
映射为对外的 ``topN``，并把元组列表转换为 ``[{"word":..., "weight":...}]``，
以对齐项目约定的 dict 返回风格。
"""

from __future__ import annotations

import logging

from jieba.analyse import extract_tags

logger = logging.getLogger("chinese_nlp_mcp.keywords")

#: 默认返回关键词数量。
DEFAULT_TOP_N = 10

#: 单次调用允许的最大 topN，防止调用方传入超大值造成无意义开销。
MAX_TOP_N = 1000


def extract_keywords(text: str, topN: int = DEFAULT_TOP_N) -> list[dict]:
    """用 TF-IDF 从中文文本中提取关键词。

    Args:
        text: 待分析的文本，可中英混合。
        topN: 返回关键词数量上限，按权重降序。若超过文本可提取的词数，
            返回全部词而不报错。

    Returns:
        形如 ``[{"word": "天安门广场", "weight": 1.6316}, ...]`` 的列表，
        按 ``weight`` 降序。``weight`` 为 TF-IDF 原始分，未归一化，
        值域通常 0 ~ 6，可大于 1.0。

    Raises:
        ValueError: ``text`` 为空/非字符串，或 ``topN`` 不是正整数。
        RuntimeError: jieba 分词或 TF-IDF 计算过程内部失败。
    """
    if not isinstance(text, str):
        raise ValueError(f"text 必须是字符串，当前类型: {type(text).__name__}")

    if not text.strip():
        raise ValueError("text 不能为空或仅含空白字符")

    # bool 是 int 的子类，isinstance(True, int) 为 True，需显式排除。
    if isinstance(topN, bool) or not isinstance(topN, int):
        raise ValueError(f"topN 必须是整数，当前类型: {type(topN).__name__}")

    if topN <= 0:
        raise ValueError(f"topN 必须大于 0，当前值: {topN}")

    if topN > MAX_TOP_N:
        raise ValueError(f"topN 不得超过 {MAX_TOP_N}，当前值: {topN}")

    logger.info("extract_keywords topN=%d len=%d", topN, len(text))

    try:
        # 底层参数名是 topK；withWeight=True 才会返回 (word, weight) 元组。
        pairs = extract_tags(text, topK=topN, withWeight=True)
    except Exception as exc:  # noqa: BLE001 - 统一包装为 RuntimeError
        logger.exception("extract_keywords failed, topN=%d", topN)
        raise RuntimeError(f"关键词提取失败（topN={topN}）: {exc}") from exc

    # 已按权重降序，无需再排序。
    return [{"word": word, "weight": weight} for word, weight in pairs]
