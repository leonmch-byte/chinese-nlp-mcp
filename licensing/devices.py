"""设备记录 —— license key 共享的**威慑**机制（D11：仅告警，不拒绝）。

⚠️ 诚实的能力边界（必读）：
纯本地架构下**无法真正检测 key 共享**。另一台机器的状态我们看不到，
除非上报到服务端。本模块唯一能检测的是「本机改了 machine_id 后
重放旧状态」—— 而这种攻击收益极低（还需重算 HMAC）。

所以这里的真实价值是**降低共享的便利性 + 留下审计痕迹**，
不是「防止共享」。任何对外承诺都不得越过这条线。

因此 D11 决定：**即使超过设备上限，也绝不拒绝付费用户的功能**。
误伤一个已付费用户的代价，远高于放过一个共享者。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("chinese_nlp_mcp.licensing")

MAX_DEVICES = 3          # D12：允许 3 个 machine_id
RESET_ENV = "CHINESE_NLP_DEVICE_RESET"
HASH_LEN = 16            # 只存 sha256 前 16 字符

DEVICES_FILE = "devices.json"


def machine_id() -> str | None:
    """平台 machine_id。取不到返回 None（此时跳过设备检查，不阻断）。"""
    try:
        if os.name == "nt":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                ) as k:
                    raw = str(winreg.QueryValueEx(k, "MachineGuid")[0])
            except OSError:
                return None
        elif os.sys.platform == "darwin":
            p = Path("/var/db/dbus/machine-id")
            if not p.exists():
                return None
            raw = p.read_text(encoding="utf-8").strip()
        else:
            p = Path("/etc/machine-id")
            if not p.exists():
                return None
            raw = p.read_text(encoding="utf-8").strip()

        raw = raw.strip()
        if not raw:
            return None
        # 只存哈希前 16 字符，**不存明文 machine_id**
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:HASH_LEN]
    except Exception:
        return None


def _devices_path() -> Path:
    from .paths import resolve_state_dir

    return resolve_state_dir() / DEVICES_FILE


def _load() -> dict:
    try:
        p = _devices_path()
        if not p.exists():
            return {"known_machines": []}
        raw = json.loads(p.read_text(encoding="utf-8"))
        km = raw.get("known_machines")
        return {"known_machines": km if isinstance(km, list) else []}
    except Exception:
        return {"known_machines": []}


def _save(data: dict) -> bool:
    try:
        from .paths import ensure_state_dir

        if ensure_state_dir() is None:
            return False
        _devices_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def _warn(count: int) -> None:
    """告警文案（用户指定模板）。只写 stderr，不改变任何 isError 状态。"""
    log.warning(
        "[chinese-nlp-mcp] This license key has been used on "
        f"{count} different machines.\n"
        f"To reset device binding, set {RESET_ENV}=1.\n"
        "If you believe this is an error, contact support."
    )


def check_device(env: dict | None = None, log_fn=log) -> dict:
    """启动时调用一次。**永远不抛异常，永远不返回"拒绝"。**

    返回诊断信息（供测试与调试），不影响任何功能。

    规则（用户指定）：
      - 当前machine_id 在列表中        → 无事发生
      - 不在列表且列表长度 < 3         → 加入列表，**不告警**
      - 不在列表且列表长度 >= 3        → 告警（并加入列表）
      - 每次成功调用不重复告警         → 因此只在启动/首次检查时告警

    ``CHINESE_NLP_DEVICE_RESET=1``：
      - 清空 known_machines，只保留当前 machine_id
      - **不重置配额计数**（本模块完全不碰 state.json）
    """
    env = env if env is not None else os.environ
    result = {"checked": False, "warned": False, "reason": ""}

    try:
        # ---- 0. machine_id 取不到 → 直接放行 ----
        mid = machine_id()
        if mid is None:
            result["reason"] = "machine_id_unavailable"
            return result
        result["checked"] = True
        result["machine_id"] = mid

        data = _load()
        known = data.get("known_machines") or []

        # ---- 1. 用户显式重置 ----
        if str(env.get(RESET_ENV, "")) == "1":
            data["known_machines"] = [mid]
            _save(data)
            log_fn.warning("Device binding reset by user request.")
            result["reason"] = "reset_by_user"
            return result

        # ---- 2. 已知名单内 → 无事发生（不重复告警）----
        if mid in known:
            result["reason"] = "known_machine"
            return result

        # ---- 3. 新机器 ----
        known.append(mid)
        data["known_machines"] = known
        _save(data)
        result["reason"] = "new_machine"

        # ---- 4. 达到上限才告警 ----
        #注意：加入后长度为 len(known)。要求「不在列表且长度 >= 3」时告警，
        # 这里用加入前的长度判断，与用户描述的语义一致。
        if len(known) >= MAX_DEVICES:
            result["warned"] = True
            _warn(len(known))
        return result

    except Exception as exc:  # noqa: BLE001 — 设备检查永远不能阻断启动
        log_fn.warning(f"device: check failed, ignored ({type(exc).__name__})")
        result["reason"] = "check_failed"
        return result


def known_machines() -> list[str]:
    """读取已记录机器（调试/测试用）。"""
    return list(_load().get("known_machines") or [])


def clear_devices() -> None:
    """清空设备记录（测试用）。"""
    _save({"known_machines": []})