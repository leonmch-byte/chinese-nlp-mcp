"""跨平台状态目录解析。

设计约束（用户明确指定 + 修正 1）：
- Windows: %LOCALAPPDATA%\\chinese-nlp-mcp\\state.json
  ⚠️ **刻意不用 %APPDATA%**（Roaming）：Roaming 目录在企业环境下会随登录
  同步到不同机器，导致同一份 state.json 出现在两台机器上，而 HMAC 签名
  密钥绑定了 machine_id → 签名校验在第二台机器必然失败 → 误判为篡改。
  LOCALAPPDATA 不参与漫游，从根上避免这个问题。
- macOS:   ~/Library/Application Support/chinese-nlp-mcp/state.json
- Linux:   $XDG_STATE_HOME/chinese-nlp-mcp/state.json，回退 ~/.local/state/...

**不引 platformdirs**，只用 pathlib + os.environ 判断。
环境变量 CHINESE_NLP_STATE_DIR 可覆盖（测试用，生产不建议改）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRNAME = "chinese-nlp-mcp"
STATE_FILENAME = "state.json"
LICENSE_FILENAME = "license.json"
LICENSE_CACHE_FILENAME = "license_cache.json"
DICT_DIRNAME = "dictionaries"

_OVERRIDE_ENV = "CHINESE_NLP_STATE_DIR"


def _select_root(os_name: str, platform: str, env: dict, home: str) -> str:
    """选择状态根目录（纯函数，返回字符串）。

    拆成纯函数是为了可跨平台测试：在 Windows 上 ``Path`` 已绑定为
    ``WindowsPath``，无法构造 ``PosixPath`` 去验证 macOS/Linux 分支。

    os_name   ``nt`` / ``posix``
    platform  ``sys.platform`` 值
    env       环境变量字典
    home      用户主目录
    """
    if os_name == "nt":  # Windows
        # 刻意用 LOCALAPPDATA 而非 APPDATA：Roaming 会随登录跨机同步，
        # 导致 state.json 出现在异机而 machine_id 不同 → 签名误判为篡改。
        base = env.get("LOCALAPPDATA")
        root = base if base else f"{home}/AppData/Local"
    elif platform == "darwin":  # macOS
        root = f"{home}/Library/Application Support"
    else:  # Linux / 其他
        xdg = env.get("XDG_STATE_HOME")
        root = xdg if xdg else f"{home}/.local/state"
    return root


def resolve_state_dir() -> Path:
    """返回状态目录（不一定存在）。

    顺序：显式覆盖 > 平台标准目录。
    任何异常都退回到 cwd 下，绝不抛出。
    """
    override = os.environ.get(_OVERRIDE_ENV)
    if override:
        return Path(override).expanduser() / APP_DIRNAME

    try:
        root = _select_root(
            os.name, sys.platform, dict(os.environ), str(Path.home())
        )
        return Path(root) / APP_DIRNAME
    except Exception:
        # 取不到 home 时兜底，不让路径解析成为崩溃点
        return Path.cwd() / APP_DIRNAME


def state_file_path() -> Path:
    return resolve_state_dir() / STATE_FILENAME


def license_file_path() -> Path:
    """本地 license 凭证（**仅当 CHINESE_NLP_STORE_KEY=1 时才存在**）。

    默认不存明文 key —— 见 `license.py` 的 D2 决策。
    """
    return resolve_state_dir() / LICENSE_FILENAME


def license_cache_path() -> Path:
    """license 验证缓存。**永远不含明文 key**，只含 key 摘要 + 验证结论。"""
    return resolve_state_dir() / LICENSE_CACHE_FILENAME


def dictionaries_dir() -> Path:
    return resolve_state_dir() / DICT_DIRNAME


def ensure_state_dir() -> Path | None:
    """确保状态目录存在。失败返回 None（调用方应降级为内存计数）。"""
    d = resolve_state_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return None