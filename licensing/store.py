"""StateStore —— 配额计数持久化 + 防篡改。

设计目标：
1. 计数持久化到 state.json（平台标准目录，不用 projectdir，避免 uvx临时目录被清）。
2. HMAC-SHA256 签名防篡改；密钥 = machine_id + 本地随机 secret 双层绑定。
3. 保留 7 天日粒度记录 → 日期回拨无法"回到干净的某天"。
4. **任何异常都不抛出** —— 读不了/写不了就降级为内存计数，服务器照常可用。

已知绕过点（诚实记录）：删除 state.json 即重置。文件不存在时无法区分
"首次运行"与"被删"。这是纯本地架构的固有局限，通过 7 天窗口缓解但不根治。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .paths import ensure_state_dir, state_file_path

log = logging.getLogger("chinese_nlp_mcp.licensing")

HISTORY_DAYS = 7
SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 1_000_000  # 单文件上限，防撑爆磁盘

# 状态标记
_OK = "ok"
_TAMPERED = "tampered"
_MEMORY_ONLY = "memory_only"


def _machine_id() -> str | None:
    """平台机器 ID。取不到返回 None（不放行失败，直接降级为不绑定）。"""
    try:
        if os.name == "nt":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                ) as k:
                    return str(winreg.QueryValueEx(k, "MachineGuid")[0])
            except OSError:
                return None
        if os.sys.platform == "darwin":
            p = Path("/var/db/dbus/machine-id")
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
            return None
        p = Path("/etc/machine-id")
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        return None
    except Exception:
        return None


def _local_secret() -> str:
    """本地随机 secret，存于 state.key（0600）。取不到则临时生成。"""
    p = state_file_path().parent / "state.key"
    try:
        if p.exists():
            s = p.read_text(encoding="utf-8").strip()
            if len(s) >= 32:
                return s
        s = uuid.uuid4().hex + uuid.uuid4().hex
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s, encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass  # Windows 上 chmod 语义有限，忽略
        return s
    except Exception:
        # 写不了 secret 时退化为进程级临时值（重启后签名失效 → 保守模式）
        return uuid.uuid4().hex + uuid.uuid4().hex


def _signing_key(secret: str) -> bytes:
    """双层绑定：machine_id + local_secret。

    拷贝到另一台机器 → machine_id 不同 → 签名失效。
    用户重算 HMAC 需要知道算法，且换机器后 machine_id 对不上。
    （诚实说明：源码在本地，这提高成本而非密码学不可破解。）
    """
    mid = _machine_id() or "no-machine-id"
    return hashlib.sha256(f"{mid}:{secret}".encode("utf-8")).digest()


def _canonical(payload: dict) -> bytes:
    """确定性序列化，保证签名可复现。"""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _mac(payload: dict, secret: str) -> str:
    return hmac.new(
        _signing_key(secret), _canonical(payload), hashlib.sha256
    ).hexdigest()


def _mac_matches(payload: dict, secret: str, signature: str) -> bool:
    try:
        return hmac.compare_digest(_mac(payload, secret), str(signature))
    except Exception:
        return False


def today_str() -> str:
    """本地日期（配额按本地日切分，与用户直觉一致）。"""
    return date.today().isoformat()


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class StateStore:
    """配额状态读写。

    状态标记 ``mode``：
      - ``ok``            正常，持久化生效
      - ``tampered``      签名校验失败，已进入保守模式（当日按满额）
      - ``memory_only``   目录不可写或文件异常，仅内存计数
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = secret or _local_secret()
        self.mode = _OK
        self._payload: dict = {"version": SCHEMA_VERSION, "daily": {}, "last_seen_date": today_str()}
        self._mem: dict[str, int] = {}
        self.reload()

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """从磁盘加载并校验。任何异常都不抛出。"""
        p = state_file_path()
        try:
            if not p.exists():
                self.mode = _OK
                self._payload = self._fresh()
                return

            if p.stat().st_size > _MAX_FILE_BYTES:
                log.warning("state: file too large, memory-only")
                self.mode = _MEMORY_ONLY
                self._payload = self._fresh()
                return

            raw = json.loads(p.read_text(encoding="utf-8"))
            payload = {
                "version": raw.get("version", SCHEMA_VERSION),
                "daily": raw.get("daily") or {},
                "last_seen_date": raw.get("last_seen_date") or today_str(),
            }
            sig = raw.get("sig", "")

            if not _mac_matches(payload, self._secret, sig):
                # 签名不匹配：无法区分"被篡改"与"secret 轮换"，
                # 一律保守处理 —— 当日按满额，用户重装可恢复。
                log.warning("state: integrity check failed, conservative mode")
                self.mode = _TAMPERED
                self._payload = self._conservative(payload)
                return

            self.mode = _OK
            self._payload = self._prune(payload)

        except Exception as exc:  # noqa: BLE001 — 故意兜底全部
            log.warning(f"state: load failed, memory-only ({type(exc).__name__})")
            self.mode = _MEMORY_ONLY
            self._payload = self._fresh()

    @staticmethod
    def _fresh() -> dict:
        return {"version": SCHEMA_VERSION, "daily": {}, "last_seen_date": today_str()}

    def _conservative(self, payload: dict) -> dict:
        """签名失败时的保守数据：保留结构，但计数视为满。

        这里不写入具体满额值 —— 满额由调用方按 tool 查FREE_LIMITS 决定，
        Store 只负责把日期标记为"不可信"。
        """
        p = self._prune(payload)
        p["untrusted"] = True
        return p

    @staticmethod
    def _prune(payload: dict) -> dict:
        """剪掉 HISTORY_DAYS 之外的历史，防止文件无限增长。"""
        try:
            keep_from = (
                date.today() - timedelta(days=HISTORY_DAYS)
            ).isoformat()
            daily = {
                d: v
                for d, v in (payload.get("daily") or {}).items()
                if isinstance(d, str) and d >= keep_from
            }
            return {
                "version": SCHEMA_VERSION,
                "daily": daily,
                "last_seen_date": payload.get("last_seen_date") or today_str(),
            }
        except Exception:
            return {"version": SCHEMA_VERSION, "daily": {}, "last_seen_date": today_str()}

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    @property
    def untrusted(self) -> bool:
        """计数是否不可信（签名失败）。"""
        return bool(self._payload.get("untrusted"))

    @property
    def last_seen_date(self) -> str:
        return str(self._payload.get("last_seen_date") or today_str())

    def rollback_detected(self, day: str | None = None) -> bool:
        """检测系统日期回拨：今天早于 last_seen_date 即为回拨。"""
        d = day or today_str()
        return d < self.last_seen_date

    def get_count(self, day: str, tool: str) -> int:
        """取某日某工具的已用次数。"""
        if self.mode == _MEMORY_ONLY:
            return self._mem.get(f"{day}|{tool}", 0)
        if self.rollback_detected(day):
            # 回拨：把该历史日按满额处理（由调用方查 limit 兜底），
            # 这里返回哨兵值 _SENTINEL_FULL 表示"视为已满"。
            return _SENTINEL_FULL
        if self.untrusted:
            return _SENTINEL_FULL
        try:
            return int(
                (self._payload.get("daily", {}).get(day) or {}).get(tool, 0)
            )
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def increment(self, day: str, tool: str, n: int = 1) -> None:
        """增加计数。任何异常都不抛出。"""
        try:
            if self.mode == _MEMORY_ONLY:
                k = f"{day}|{tool}"
                self._mem[k] = self._mem.get(k, 0) + n
                return

            daily = self._payload.setdefault("daily", {})
            day_rec = daily.setdefault(day, {})
            day_rec[tool] = int(day_rec.get(tool, 0)) + n

            # last_seen 只前进，不回退 —— 防止回拨把标记拉低
            if day > self.last_seen_date:
                self._payload["last_seen_date"] = day

            self.save()
        except Exception as exc:  # noqa: BLE001
            log.warning(f"state: increment failed ({type(exc).__name__})")

    def consume(self, day: str, counts: dict[str, int]) -> None:
        """批量扣减（批量工具用）。"""
        for tool, n in counts.items():
            if n > 0:
                self.increment(day, tool, n)

    def save(self) -> bool:
        """写盘。失败则降级为内存计数。返回是否持久化成功。"""
        if self.mode == _MEMORY_ONLY:
            return False
        payload = self._prune(self._payload)
        payload.pop("untrusted", None)
        try:
            d = ensure_state_dir()
            if d is None:
                log.warning("state: dir not writable, memory-only")
                self.mode = _MEMORY_ONLY
                return False

            p = state_file_path()
            sig = _mac(payload, self._secret)
            blob = json.dumps(
                {**payload, "sig": sig}, ensure_ascii=False, indent=2
            )
            # 原子写：先写临时文件再replace，避免半截文件
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(blob, encoding="utf-8")
            os.replace(tmp, p)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning(f"state: save failed, memory-only ({type(exc).__name__})")
            self.mode = _MEMORY_ONLY
            return False


#: 表示"视为已满"的哨兵值
_SENTINEL_FULL = -1
SENTINEL_FULL = _SENTINEL_FULL


def is_full_sentinel(value: int) -> bool:
    """判断计数是否为哨兵值（回拨/篡改 ⇒ 视为已满）。"""
    return value == _SENTINEL_FULL