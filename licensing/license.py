"""LicenseVerifier —— tier 判定 + 缓存 + 宽限 + 静默降级（P3）。

与 `gumroad.py` 的分工：
    gumroad.py只做「问一次Gumroad」，不碰文件系统。
    license.py    做「什么时候问、问完怎么缓存、失败了怎么办」。

================================================================
设计决策（D1~D5，已 review 通过）
================================================================

**D1** ``purchase.test == true``（测试/沙箱订单）**不参与有效性判定**。
     若把 test 当无效，开发者本地永远调不通 P3。只落盘 ``test_purchase``
     并在 stderr 打一行提示。

**D2** ⚠️ **默认不保存 key 明文。**
     理由：
     - 隐私承诺一致性 —— README 声称「纯本地、数据不出机器」，存明文会矛盾；
     - HMAC 只防篡改，**不防读取** —— state目录可能被云盘同步 / 备份软件扫描 /
       用户贴给别人。
     默认行为：key 来自环境变量 ``CHINESE_NLP_LICENSE_KEY``，由用户自己决定
     是否持久化到 shell 配置。
     可选功能：``CHINESE_NLP_STORE_KEY=1`` 才写明文到 ``license.json``，
     **默认关闭**。
     无论开关如何，``license_cache.json`` **永远只含 key 摘要**，不含明文。

**D3** ``uses`` **不参与有效性判定**，只落盘 ``last_uses``。
     理由：我方自己的验证调用会推高这个计数，拿它做配额是自欺欺人。
     补充：若 24h 内 ``uses - last_uses > 20``，写 stderr 警告
     "Possible key sharing detected"，**但不拒绝服务**。

**D4** 超时 8s、重试 0 次。

**D5** 断网宽限 7 天。

**TTL 分档**：paid 缓存 24h，**free（INVALID）缓存仅 1h**。
     理由：误判一次 INVALID 不该锁 24h（用户输错 key 立刻改对、
     或在 Gumroad 后台解封 key，都只需等 1h）。1h 也已足够避免
     「误输一次 key 之后每次启动都干等 8s 超时」。

================================================================
五层决策（按序求值，命中即返回）
================================================================

===  ==============================  ==============  ==========
层   条件                            返回            联网
===  ==============================  ==============  ==========
L1   无可用 key                      free            否
L2   缓存 <24h 且 key 摘要匹配        缓存里的 tier   否
L3   缓存过期 / 摘要不匹配 / 无缓存   在线验证        是
L4   L3 判为 TRANSIENT 且上次成功
     验证距今 <7 天且摘要匹配paid            否
L5   兜底                            free            否
===  ==============================  ==============  ==========

除 L4 外全部保守落 free —— 宁可少收钱，不给绕过空间。
L4 是唯一例外：已付费用户断网不该被立刻降级，这是**体验**而非安全边界。

**L4 只对 TRANSIENT 生效**：HTTP 404 / HTTP 4xx / ``success:false`` /
退款 / 争议 / 拒付 一律INVALID，**立即降级，不给宽限**。
理由：这些是服务端明确说「你的 key 不行」，不是网络问题。

================================================================
铁律
================================================================

1. ``tier()`` 永不抛异常、永不返回 None、绝不超过 8s 阻塞。
2. 任何问题都**静默降级**到 free —— 只记 stderr，绝不弹窗、绝不新增错误类型。
   Pro 功能不可用时表现为「配额用完了」，而不是一个陌生的 license 错误。
3. 缓存文件 HMAC 签名，密钥 = machine_id + local_secret 双层绑定（复用 store.py）。
   签名失败 → 不信任缓存 → 按L5 走 free。
4. 本模块**不 import任何 MCP 框架**。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from .gumroad import (
    INVALID,
    PRODUCT_ID,
    TIMEOUT_SECONDS,
    TRANSIENT,
    VALID,
    verify_license_online,
)
from .paths import ensure_state_dir, license_cache_path, license_file_path
from .store import _local_secret, _mac, _mac_matches

log = logging.getLogger("chinese_nlp_mcp.licensing")

# ---- 环境变量 ----
ENV_KEY = "CHINESE_NLP_LICENSE_KEY"      # key 来源（不进git，用户自己配 shell）
ENV_STORE_KEY = "CHINESE_NLP_STORE_KEY"  # =1 才落盘明文，默认关（D2）
ENV_DEBUG = "CHINESE_NLP_LICENSE_DEBUG"  # =1 输出 stderr 诊断
ENV_RESET = "CHINESE_NLP_LICENSE_RESET"  # =1 清除本地缓存与凭证

# ---- 时限（D4 / D5）----
CACHE_TTL_HOURS = 24          # L2 paid 缓存新鲜期
INVALID_TTL_HOURS = 1         # L2 free（INVALID）缓存新鲜期 —— 见下方说明
GRACE_DAYS = 7                # L4 断网宽限期
SHARING_DELTA_THRESHOLD = 20  # D3：24h 内 uses 增长超过此值 → 疑似共享

# **为什么 INVALID 缓存只给 1h，而 paid 给 24h**
#   paid 缓存的代价是「多24h 不发一次网络请求」，收益是「网络故障时不受影响」→ 24h 合理。
#   free（INVALID）缓存的代价是「误判一次会锁1h」——
#   典型场景：用户输错 key 后立刻改对，或在 Gumroad 后台解封/恢复了一个 key。
#   两种情况下都只该等 1h，而不是 24h。
#   1h 也已足够避免「误输一次 key 就每次启动都等 8s 超时」这个真实问题。
#   实现上不新增缓存字段 —— 直接按缓存里的 ``tier`` 值选 TTL，白名单仍是 7 个字段。

# ---- 摘要口径 ----
# 与 devices.py 的 machine_id() 同思路：本地存摘要，不存明文。
# 16 hex = 64 bit，碰撞概率对本场景足够低。
KEY_HASH_LEN = 16

CACHE_VERSION = 1
_MAX_CACHE_BYTES = 10_000

FREE = "free"
PAID = "paid"

# ---- 缓存字段白名单（D2：只有这 7 个可以落盘）----
_CACHE_FIELDS = (
    "key_sha256_prefix",
    "verified_at",
    "tier",
    "product_id",
    "sale_id",
    "test_purchase",
    "last_uses",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    """解析 ISO-8601。失败返回 None（调用方按「无缓存」处理）。"""
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # 兼容尾部 Z 写法（Python 3.10 的 fromisoformat 不认Z）
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def key_fingerprint(key: str) -> str:
    """key 摘要：``sha256(key)`` 的前 16 hex。

    **永不返回明文或其可逆形式。**
    """
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:KEY_HASH_LEN]


def _env_flag(env: dict | None, name: str) -> bool:
    src = os.environ if env is None else env
    return str(src.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


class LicenseVerifier:
    """tier 判定器。对接 ``QuotaGuard(tier_provider=...)``。

    ``env`` 参数供测试注入；生产传None 读真实环境变量。
    """

    def __init__(self, env: dict | None = None, timeout: float = TIMEOUT_SECONDS) -> None:
        self._env = env
        self._timeout = timeout
        self._secret = _local_secret()
        self._tier_cache: str | None = None  # 进程内记忆，避免每次调用都判
        self._last_result = None

    # ------------------------------------------------------------------
    # 环境变量读取
    # ------------------------------------------------------------------
    def _env_get(self, name: str) -> str:
        src = os.environ if self._env is None else self._env
        return str(src.get(name, "") or "").strip()

    def _env_key(self) -> str:
        """来自环境变量的 key。**明文只在内存里，绝不落盘**（除非 STORE_KEY=1）。"""
        return self._env_get(ENV_KEY)

    def _stored_key(self) -> str:
        """从 license.json 读明文 key。

        该文件**只在 ``CHINESE_NLP_STORE_KEY=1`` 时才存在**（D2 默认关闭）。
        """
        p = license_file_path()
        try:
            if not p.exists():
                return ""
            if p.stat().st_size > _MAX_CACHE_BYTES:
                return ""
            raw = json.loads(p.read_text(encoding="utf-8"))
            key = raw.get("key")
            if not isinstance(key, str) or not key:
                return ""
            if not _mac_matches({"key": key}, self._secret, raw.get("sig", "")):
                log.warning("license: stored key integrity check failed, ignoring")
                return ""
            return key.strip()
        except Exception as exc:  # noqa: BLE001
            log.warning(f"license: read stored key failed ({type(exc).__name__})")
            return ""

    def _resolve_key(self) -> str:
        """环境变量优先，其次本地凭证文件。"""
        return self._env_key() or self._stored_key()

    # ------------------------------------------------------------------
    # 缓存读写
    # ------------------------------------------------------------------
    def _load_cache(self) -> dict | None:
        """读缓存并验签。任何异常 / 验签失败 → None（按无缓存处理）。"""
        p = license_cache_path()
        try:
            if not p.exists():
                return None
            if p.stat().st_size > _MAX_CACHE_BYTES:
                return None

            raw = json.loads(p.read_text(encoding="utf-8"))
            payload = {k: raw.get(k) for k in _CACHE_FIELDS}
            if not _mac_matches(payload, self._secret, raw.get("sig", "")):
                # 签名不匹配 → 不信任。注意这是**保守方向**（倾向 free）。
                log.warning("license: cache integrity check failed, ignoring cache")
                return None
            return payload
        except Exception as exc:  # noqa: BLE001
            log.warning(f"license: cache load failed ({type(exc).__name__})")
            return None

    def _save_cache(self, payload: dict) -> None:
        """写缓存。**只写白名单 7 字段 + sig**。失败不抛。"""
        try:
            d = ensure_state_dir()
            if d is None:
                return
            clean = {k: payload.get(k) for k in _CACHE_FIELDS}
            sig = _mac(clean, self._secret)
            blob = json.dumps({**clean, "sig": sig}, ensure_ascii=False, indent=2)
            p = license_cache_path()
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(blob, encoding="utf-8")
            os.replace(tmp, p)  # 原子写，避免半截文件
        except Exception as exc:  # noqa: BLE001
            log.warning(f"license: cache save failed ({type(exc).__name__})")

    # ------------------------------------------------------------------
    # 明文凭证（仅 STORE_KEY=1）
    # ------------------------------------------------------------------
    def activate(self, key: str) -> dict:
        """用户主动设置 key。

        默认**不落盘**（D2）—— 只返回提示，key 需自行配到环境变量。
        ``CHINESE_NLP_STORE_KEY=1`` 时才写入 license.json。
        """
        key = (key or "").strip()
        if not key:
            return {"ok": False, "reason": "empty_key"}

        if not _env_flag(self._env, ENV_STORE_KEY):
            return {
                "ok": False,
                "reason": "store_disabled",
                "hint": (
                    f"Default is NOT to store the key on disk. "
                    f"Set it in your shell instead:\n"
                    f"  export {ENV_KEY}=<your-key>\n"
                    f"Or opt in to local storage with {ENV_STORE_KEY}=1."
                ),
            }

        try:
            d = ensure_state_dir()
            if d is None:
                return {"ok": False, "reason": "state_dir_unwritable"}
            p = license_file_path()
            sig = _mac({"key": key}, self._secret)
            blob = json.dumps({"key": key, "sig": sig}, ensure_ascii=False, indent=2)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(blob, encoding="utf-8")
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass  # Windows 上 chmod 语义有限，靠账户隔离
            os.replace(tmp, p)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"write_failed:{type(exc).__name__}"}

        # 强制下次 tier() 重新判定
        self._tier_cache = None
        return {"ok": True, "stored": True}

    def deactivate(self) -> bool:
        """清除本地明文凭证与缓存。返回是否真的删了东西。"""
        removed = False
        for p in (license_file_path(), license_cache_path()):
            try:
                if p.exists():
                    p.unlink()
                    removed = True
            except OSError:
                pass
        self._tier_cache = None
        return removed

    def _maybe_reset(self) -> None:
        """``CHINESE_NLP_LICENSE_RESET=1`` 时清缓存（用户自解锁）。"""
        if _env_flag(self._env, ENV_RESET):
            self.deactivate()

    # ------------------------------------------------------------------
    # 核心：五层决策
    # ------------------------------------------------------------------
    def tier(self) -> str:
        """返回 ``"paid"`` 或 ``"free"``。

        **永不抛异常、永不返回 None、绝不超过 8s阻塞。**
        """
        try:
            if self._tier_cache is not None:
                return self._tier_cache
            self._tier_cache = self._decide()
            return self._tier_cache
        except Exception as exc:  # noqa: BLE001 — 最后一道保险
            log.warning(f"license: tier() internal error, falling back to free ({type(exc).__name__})")
            return FREE

    def _decide(self) -> str:
        self._maybe_reset()

        key = self._resolve_key()

        # ---- L1：无 key ----
        if not key:
            return FREE

        fp = key_fingerprint(key)
        cache = self._load_cache()
        cache_match = bool(cache) and cache.get("key_sha256_prefix") == fp

        # ---- L2：缓存新鲜 ----
        # paid 缓存 24h / free（INVALID）缓存 1h —— 见 INVALID_TTL_HOURS 处说明。
        if cache_match:
            verified_at = _parse_iso(cache.get("verified_at"))
            if verified_at is not None:
                cached_tier = str(cache.get("tier") or FREE)
                ttl_hours = CACHE_TTL_HOURS if cached_tier == PAID else INVALID_TTL_HOURS
                age = _now() - verified_at
                # 负数 = 系统时间被回拨到验证之前 → 视为过期（保守）
                if timedelta(0) <= age < timedelta(hours=ttl_hours):
                    return cached_tier

        # ---- L3：在线验证 ----
        result = verify_license_online(key, timeout=self._timeout)
        self._last_result = result

        if _env_flag(self._env, ENV_DEBUG):
            log.info(f"license: verify result = {result.as_dict()}")

        # L3a：有效
        if result.status == VALID:
            self._record_success(key, result)
            return PAID

        # L3b：无效 —— **立即降级，不给宽限**
        if result.status == INVALID:
            # 无效结果也写缓存吗？写。
            # 目的不是「记住坏 key」，而是让 24h 内的启动不再去打网络 ——
            # 一次误输入不该让用户每次启动都等 8s 超时。
            # 摘要仍写入，保证换了 key 会立刻失效缓存。
            self._save_cache(
                {
                    "key_sha256_prefix": fp,
                    "verified_at": _iso(_now()),
                    "tier": FREE,
                    "product_id": None,
                    "sale_id": result.sale_id,
                    "test_purchase": result.test_purchase,
                    "last_uses": result.uses,
                }
            )
            return FREE

        # ---- L3c / L4：TRANSIENT → 看宽限 ----
        # 只在「上次成功验证过 + 摘要匹配 + 距今 <7 天」时才给 paid。
        if cache_match and cache and cache.get("tier") == PAID:
            last_ok = _parse_iso(cache.get("verified_at"))
            if last_ok is not None:
                age = _now() - last_ok
                if timedelta(0) <= age < timedelta(days=GRACE_DAYS):
                    log.warning(
                        "license: network unavailable, using cached Pro tier "
                        f"(grace window, {GRACE_DAYS - age.days}d left)"
                    )
                    return PAID
                # 宽限已过期 → 落free（L5）
                log.warning(
                    "license: network unavailable and grace window expired "
                    f"({age.days}d > {GRACE_DAYS}d), serving free tier"
                )
                return FREE

        return FREE

    # ------------------------------------------------------------------
    def _record_success(self, key: str, result) -> None:
        """验证成功后写缓存 + 打诊断日志。

        隐私纪律：这里只写白名单 7 字段，
        ``key`` 只用来算摘要，明文绝不进文件。
        """
        # D1：测试订单提示
        if result.test_purchase:
            log.warning(
                "[chinese-nlp-mcp] Test purchase detected (sandbox order)"
            )

        # D3：疑似 key 共享告警（不拒绝服务）
        try:
            cache = self._load_cache()
            if (
                result.uses is not None
                and cache
                and cache.get("key_sha256_prefix") == key_fingerprint(key)
            ):
                prev = cache.get("last_uses")
                if isinstance(prev, int) and not isinstance(prev, bool):
                    if result.uses - prev > SHARING_DELTA_THRESHOLD:
                        log.warning(
                            "Possible key sharing detected "
                            f"(uses {prev} -> {result.uses} within cache window). "
                            "Serving normally."
                        )
        except Exception:  # noqa: BLE001
            pass  # 共享检测是诊断功能，失败绝不影响主流程

        self._save_cache(
            {
                "key_sha256_prefix": key_fingerprint(key),
                "verified_at": _iso(_now()),
                "tier": PAID,
                "product_id": PRODUCT_ID,
                "sale_id": result.sale_id,
                "test_purchase": result.test_purchase,
                "last_uses": result.uses,
            }
        )

    # ------------------------------------------------------------------
    def status(self) -> dict:
        """诊断信息。**只含非敏感字段**，可安全展示/ 打日志。"""
        try:
            key = self._resolve_key()
            cache = self._load_cache()
            return {
                "tier": self.tier(),
                "has_key": bool(key),
                "key_source": (
                    "env" if self._env_key() else ("file" if self._stored_key() else "none")
                ),
                "stored_plaintext": license_file_path().exists(),
                "cache_present": bool(cache),
                "cache_tier": (cache or {}).get("tier"),
                "cache_verified_at": (cache or {}).get("verified_at"),
                "cache_ttl_hours": CACHE_TTL_HOURS,
                "cache_ttl_invalid_hours": INVALID_TTL_HOURS,
                "grace_days": GRACE_DAYS,
                "sale_id": (cache or {}).get("sale_id"),
                "test_purchase": (cache or {}).get("test_purchase"),
                "last_uses": (cache or {}).get("last_uses"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"tier": FREE, "error": type(exc).__name__}

    def is_paid(self) -> bool:
        return self.tier() == PAID

    def reset(self) -> None:
        """清进程内记忆 + 本地缓存（不删明文凭证，除非调 ``deactivate()``）。"""
        self._tier_cache = None
        try:
            p = license_cache_path()
            if p.exists():
                p.unlink()
        except OSError:
            pass


__all__ = [
    "LicenseVerifier",
    "ENV_KEY",
    "ENV_STORE_KEY",
    "ENV_DEBUG",
    "ENV_RESET",
    "CACHE_TTL_HOURS",
    "INVALID_TTL_HOURS",
    "GRACE_DAYS",
    "SHARING_DELTA_THRESHOLD",
    "KEY_HASH_LEN",
    "key_fingerprint",
    "FREE",
    "PAID",
    "VALID",
    "INVALID",
    "TRANSIENT",
]