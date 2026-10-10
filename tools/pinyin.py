"""中文转拼音工具。

底层 pypinyin 0.55.0。四种style 对应关系（已实测核对，见文件末尾注释）：

- ``tone``        -> ``Style.TONE``        带声调符号，如 ``zhōng``
- ``tone2``       -> ``Style.TONE2``      数字声调，如 ``zho1ng``
- ``initials``    -> ``Style.INITIALS``    声母，如 ``zh``
- ``first_letter`` -> ``Style.FIRST_LETTER`` 首字母，如 ``z``

⚠️ 为何必须自己做白名单：实测 ``lazy_pinyin(text, style="bad")`` **不报错**，
会静默降级为 ``Style.NORMAL`` 返回带调拼音。调用方传错参数将静默拿到错误结果，
因此本模块在入口处强制校验 style，不把非法值透传给 pypinyin。

pypinyin 源码/运行时依据（v0.55.0）：
    Style 枚举成员实际取值——
        NORMAL=0, TONE=1, TONE2=2, INITIALS=3, FIRST_LETTER=4
    lazy_pinyin 签名——
        lazy_pinyin(hans, style=Style.NORMAL, errors='default',
                     strict=True, v_to_u=False, neutral_tone_with_five=False,
                     tone_sandhi=False)
"""

from __future__ import annotations

import logging

from pypinyin import Style, lazy_pinyin

logger = logging.getLogger("chinese_nlp_mcp.pinyin")

#: 允许的拼音风格白名单。
VALID_STYLES: frozenset[str] = frozenset(
    {"tone", "tone2", "initials", "first_letter"}
)

#: style -> pypinyin Style枚举映射。
_STYLE_MAP: dict[str, Style] = {
    "tone": Style.TONE,
    "tone2": Style.TONE2,
    "initials": Style.INITIALS,
    "first_letter": Style.FIRST_LETTER,
}


def convert_pinyin(
    text: str,
    style: str = "tone",
    separator: str = " ",
) -> str:
    """将中文文本转换为拼音字符串。

    Args:
        text: 待转换的中文文本。
        style: 拼音风格，四选一—— ``tone`` 带声调符号（``zhōng``）；
            ``tone2`` 数字声调（``zho1ng``）；``initials`` 声母（``zh``）；
            ``first_letter`` 首字母（``z``）。
        separator: 词与词之间的拼接分隔符，默认空格。

    Returns:
        以 ``separator`` 拼接的拼音字符串。非中文字符（如英文、数字）会被
        pypinyin 原样保留。

    Raises:
        ValueError: ``text`` 为空、``style`` 不在白名单内，
            或 ``separator`` 不是字符串。
        RuntimeError: pypinyin 转换过程内部失败。
    """
    if not isinstance(text, str):
        raise ValueError(f"text 必须是字符串，当前类型: {type(text).__name__}")

    if not text.strip():
        raise ValueError("text 不能为空或仅含空白字符")

    if not isinstance(style, str):
        raise ValueError(f"style 必须是字符串，当前类型: {type(style).__name__}")

    if style not in VALID_STYLES:
        raise ValueError(f"style 无效: {style!r}，仅支持 {sorted(VALID_STYLES)}")

    if not isinstance(separator, str):
        raise ValueError(
            f"separator 必须是字符串，当前类型: {type(separator).__name__}"
        )

    pinyin_style = _STYLE_MAP.get(style)
    if pinyin_style is None:  # pragma: no cover - 防御性：白名单已拦截
        raise ValueError(f"style 无效: {style!r}，仅支持 {sorted(VALID_STYLES)}")

    logger.info(
        "convert_pinyin style=%s sep=%r len=%d", style, separator, len(text)
    )

    try:
        parts = lazy_pinyin(text, style=pinyin_style)
    except Exception as exc:  # noqa: BLE001 - 统一包装为 RuntimeError
        logger.exception("convert_pinyin failed, style=%s", style)
        raise RuntimeError(f"拼音转换失败（style={style}）: {exc}") from exc

    return separator.join(parts)
