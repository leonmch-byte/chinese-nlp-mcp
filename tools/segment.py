"""中文分词工具。

底层 jieba 0.42.1。三种模式对应关系（已实测核对jieba 源码，见文件末尾注释）：

- ``default`` -> ``jieba.cut(text)``
- ``search``  -> ``jieba.cut_for_search(text)``，额外切出词内部的 2/3 gram
- ``index``   -> jieba 顶层**不存在** ``cut_for_index``；``tokenize(mode=...)``
  仅区分default 与 "其他"，传 index 会静默走 search 分支。故本实现显式
  将 index 映射为 ``cut_for_search``，行为与 search 一致但语义上更贴近
  搜索引擎/倒排索引场景。

注意：``search`` / ``index`` 模式下 jieba 内部会计算每个词的 (word, start, end)
位置三元组，但按项目约定，返回值统一为 ``list[str]``，**位置信息一律丢弃**。

jieba 源码依据（jieba/__init__.py，v0.42.1）：
    - line 289:  def cut(self, sentence, cut_all=False, HMM=True, use_paddle=False)
    - line 338:  def cut_for_search(self, sentence, HMM=True)
    - line 476:  def tokenize(self, unicode_sentence, mode="default", HMM=True)
                 # 内部仅 if mode == 'default': ... else: <cut_for_search逻辑>
                 # 故 mode='index' 会被当作 search 处理，无独立 index 分支。
"""

from __future__ import annotations

import logging

import jieba

logger = logging.getLogger("chinese_nlp_mcp.segment")

# jieba 首次加载会往 stderr 打大量构建词典日志，属正常现象。
# 这里显式设为 WARNING 级别，保留真正的错误信息即可。
jieba.setLogLevel(logging.WARNING)

#: 允许的分词模式白名单。
VALID_MODES: frozenset[str] = frozenset({"default", "search", "index"})

# 精确模式 -> jieba 调用函数名（mode 白名单已在下方统一拦截）。
_CUTTERS = {
    "default": jieba.cut,
    "search": jieba.cut_for_search,
    # jieba 无 cut_for_index；见模块 docstring 说明。
    "index": jieba.cut_for_search,
}


def segment_chinese(text: str, mode: str = "default") -> list[str]:
    """对中文文本分词。

    Args:
        text: 待分词的中文文本。
        mode: 分词模式，三选一—— ``default``（标准分词）、``search``
            （搜索模式，额外切出词内部的 2/3 元组）、``index``
            （索引模式，当前与 search 行为一致，因 jieba 未提供独立
            ``cut_for_index`` 实现）。

    Returns:
        分词结果列表。``search`` / ``index`` 模式下jieba 内部计算的
        词位置 (start, end) **不返回**，仅返回词本身。

    Raises:
        ValueError: ``mode`` 不在白名单内，或 ``text`` 不是字符串 / 为空。
        RuntimeError: jieba 分词过程内部失败。
    """
    if not isinstance(text, str):
        raise ValueError(f"text 必须是字符串，当前类型: {type(text).__name__}")

    if not text.strip():
        raise ValueError("text 不能为空或仅含空白字符")

    if mode not in VALID_MODES:
        raise ValueError(
            f"mode 无效: {mode!r}，仅支持 {sorted(VALID_MODES)}"
        )

    cutter = _CUTTERS.get(mode)
    if cutter is None:  # pragma: no cover - 防御性：白名单已拦截，此处仅兜底
        raise ValueError(f"mode 无效: {mode!r}，仅支持 {sorted(VALID_MODES)}")
    logger.info("segment_chinese mode=%s len=%d", mode, len(text))

    try:
        tokens = list(cutter(text))
    except Exception as exc:  # noqa: BLE001 - 统一包装为 RuntimeError
        logger.exception("segment_chinese failed, mode=%s", mode)
        raise RuntimeError(f"分词失败（mode={mode}）: {exc}") from exc

    return [t for t in tokens if t.strip()]
