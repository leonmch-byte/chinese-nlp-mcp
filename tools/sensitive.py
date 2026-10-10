"""自定义敏感词检测工具（Aho-Corasick 自动机）。

======================================================================
🔴 项目级红线 — 不可协商
======================================================================
本模块**严禁内置任何词库**。词库完全由调用方通过 ``words`` 参数传入。

* 本文件不得出现任何示例词、演示词、占位词，更不得内置政治敏感词。
* ``words`` 为空列表或 ``None`` 时，直接返回 ``{"matches": [], "clean": True}``，
  不做任何检测。
* 本模块中的所有中文字符串仅用于**类型标注与错误提示**，
  不得作为检测词库参与匹配。
======================================================================

方案选型（已实测，非推测）
--------------------------------
候选 a) pyahocorasick —— **采用**
    实测 `pip install pyahocorasick` 在 Windows + Python 3.13 下**成功**，
    有官方预编译 wheel `pyahocorasick-2.3.1-cp313-cp313-win_amd64.whl`，
    无需本地编译工具链。
    实测性能：4813 词库 × 100000 字文本，命中 79999 次，耗时 **0.008 秒**。

候选 b) 纯 Python AC 自动机 —— 未采用
    无编译依赖，但 Python 层逐字符循环比 C 扩展慢一到两个数量级，
    在大词库场景下不可接受。

候选 c) 简单多模式字符串匹配 —— 未采用
    复杂度 O(词库数 × 文本长度)，词库稍大即不可用。

底层 API 实测结论（pyahocorasick 2.3.1，模块名是``ahocorasick``，单 a）
----------------------------------------------------------------------
- ``ahocorasick.Automaton()`` 构造，``add_word(key, value)`` 加词，
  **必须调用 ``make_automaton()`` 之后**才能匹配，否则 ``iter`` 抛异常。
  因此 ``words`` 为空时必须提前返回，不能建空自动机。
- ``iter(text)`` 返回 ``(end_index, value)``，是生成器，**按 end_index 升序**。
  ``start_index = end_index - len(value) + 1``，实测切片校验通过。
- **索引为字符索引，不是字节索引**：``A.kind == 2``（``ahocorasick.unicode``），
  中文按 1 个字符计。
- ``find_all()`` 在非 ASCII 文本上会抛 ``IndexError``，**故统一使用 ``iter``**。
"""

from __future__ import annotations

import logging

import ahocorasick

logger = logging.getLogger("chinese_nlp_mcp.sensitive")

#: 单次调用允许的最大词库大小，防止调用方传入超大词库耗尽内存。
MAX_WORDS = 100_000


def detect_sensitive_words(
    text: str,
    words: list[str] | None = None,
) -> dict:
    """在文本中检测调用方自定义的敏感词。

    ⚠️ 本工具**不含任何内置词库**。``words`` 是唯一的检测依据，
    传空列表或 ``None`` 等同于不做检测。

    重叠匹配策略：**返回全部命中，不做去重、不做最长/最短优先裁剪**。

    理由：调用方是自己词库的负责人，最清楚"命中什么"才是自己关心的信号。
    若工具替他裁剪（例如只留最长匹配），他既无法知道"人民"也命中了，
    也无法针对重叠区间做不同的处置。反之，拿到全部命中后，
    调用方完全可以按 ``index`` 自行裁剪或聚合，而工具不做这个预设立场。
    AHOCORASICK 库本身即返回全部重叠命中，本工具原样透传。

    Args:
        text: 待检测文本。
        words: 调用方自定义词库。为 ``None`` 或空列表时不检测任何内容。

    Returns:
        ``{"matches": [{"word": str, "index": int}, ...], "clean": bool}``。
        ``index`` 是该词**起始位置**的字符索引（中文按 1 字计，非字节）。
        ``matches`` 按命中结束位置升序排列；``clean`` 为 ``matches`` 为空时为 True。

    Raises:
        ValueError: ``text`` 为空/非字符串；``words`` 不是列表；
            或 ``words`` 含空字符串/非字符串元素。
        RuntimeError: 自动机构建或匹配过程内部失败。
    """
    if not isinstance(text, str):
        raise ValueError(f"text 必须是字符串，当前类型: {type(text).__name__}")

    if not text.strip():
        raise ValueError("text 不能为空或仅含空白字符")

    # words 允许 None（视为空词库），但一旦是 list 之外的类型必须拒绝，
    # 例如传字符串 "abc" 会被逐字符迭代，若不拦截会静默产生错误检测结果。
    if words is None:
        words = []
    elif not isinstance(words, list):
        raise ValueError(
            f"words 必须是字符串列表，当前类型: {type(words).__name__}"
        )

    for i, w in enumerate(words):
        if not isinstance(w, str):
            raise ValueError(
                f"words[{i}] 必须是字符串，当前类型: {type(w).__name__}"
            )
        if not w:
            raise ValueError(f"words[{i}] 不能为空字符串")

    if len(words) > MAX_WORDS:
        raise ValueError(f"words 数量不得超过 {MAX_WORDS}，当前: {len(words)}")

    # 空词库直接返回。绝不能建空自动机——ahocorasick 未 make_automaton 时
    # 调用 iter 会抛 "Not an Aho-Corasick automaton yet"。
    if not words:
        logger.info("detect_sensitive_words: empty word list, skip scanning")
        return {"matches": [], "clean": True}

    logger.info("detect_sensitive_words: %d words, text len=%d", len(words), len(text))

    try:
        automaton = ahocorasick.Automaton()
        for w in words:
            automaton.add_word(w, w)
        automaton.make_automaton()

        matches = [
            # iter 给的是结束位置，起始位置需减去词长再 +1。
            {"word": value, "index": end_index - len(value) + 1}
            for end_index, value in automaton.iter(text)
        ]
    except Exception as exc:  # noqa: BLE001 - 统一包装为 RuntimeError
        logger.exception("detect_sensitive_words failed")
        raise RuntimeError(f"敏感词检测失败: {exc}") from exc

    return {"matches": matches, "clean": not matches}
