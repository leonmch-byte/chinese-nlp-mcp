"""Gumroad 产品常量与 License Key 在线验证（纯网络层）。

本模块**只做一件事**：拿着 key 去问Gumroad「这个 key 有效吗」，然后如实回答。
它**不碰文件系统、不读环境变量、不做缓存、不抛异常** —— 那些是 `license.py` 的职责。

分层理由（沿用licensing/ 零 MCP 依赖原则）：
- 本模块**不依赖任何 MCP 框架**（不 import fastmcp / mcp）。
- 只用 stdlib `urllib.request`，不引入 requests（保持零新增第三方依赖）。
- 网络 I/O 与缓存/降级策略分离，便于对二者分别做单元测试。

================================================================
实测响应形态（2026-10-11 真实 key + 无效 key 双分支探测，勿凭记忆改）
================================================================

成功分支：
    HTTP 200
    Content-Type: application/json; charset=utf-8
    {
      "success": true,
      "uses": 1,                      # 已用次数（累计 verify 调用数），非剩余
      "purchase": {
        "product_id": "wC1DNPpemAqtBZKYOYXbGw==",
        "seller_id": "1iLh5XOsdthIspGS5577Zg==",
        "sale_id": "KKEJhiUMe_BnOdhjSOwaCA==",
        "sale_timestamp": "2026-10-11T11:55:30Z",
        "test": true,                 # 测试订单沙箱标志
        "refunded": false,
        "disputed": false,
        "dispute_won": false,
        "chargebacked": false,
        "license_key": "<明文回显！>",  # ⚠️ 绝不落盘、绝不进日志
        "email": "<PII>",
        "referrer": "<含 _ga 追踪串>",
        "ip_country": "Angola",
        ...
      }
    }

失败分支：
    HTTP 404← 实测值，不是 200
    Content-Type: application/json
    {"success": false, "message": "That license does not exist for the provided product."}

⚠️ **勘误（2026-10-11）**：早期设计文档（`docs/paid-tier-design.md`）与本文件
旧 docstring 都写了「无效 key 返回 HTTP 200 + success:false，只看状态码会误判成功」。
**该假设已被实测推翻 —— 无效 key 返回 HTTP 404。**
即便如此，`success` 字段**仍必须校验**：HTTP 200 且 `success:false`
是防御「退款 / 吊销」的正确位置，不能只依赖状态码。

⚠️ **无过期字段**：实测响应中**不存在** `expires_at` / `expires` / `expiry`。
本模块不做任何本地过期计算，有效性只由服务端结论 + 4 个退款/争议布尔决定。

⚠️ **关于 refunded 等布尔字段的类型（2026-10-12 交叉验证）**
    实测这三个字段是**真正的 JSON bool**（false / true），**不是 null**。
    三个独立第三方客户端（go-gumroad 的 Go struct、GumroadLicensing .NET、
    airsync-mac 的 Swift）也都把它们声明为非可选 bool —— 三方一致。
    因此 ``is not False``（null 判无效）在实践中**不会误伤合法订单**。
    若 Gumroad 未来改成 null，本实现会保守判为无效 —— 这是**有意的**：
    判错方向是「付费用户掉到免费层」，而非「退款用户继续用 Pro」。
    真出现时 stderr 会打出 ``refunded`` 原因码，可据此定位。

⚠️ **请求 Content-Type 实测**：JSON body 与 ``application/x-www-form-urlencoded``
    **都被接受**（均返回同一份 404 JSON）。本实现用 JSON，与探测脚本一致。

隐私承诺（P3 实施时必须严格遵守）：
- 验证请求**只发送 license_key 与 product_id** 两个字段 ——
  这正是2026-10-11 探测脚本实际发出的内容（见 `_probe_gumroad.py`），
  不发送任何用户数据（文本、工具名、计数、设备 ID 均不上报）。
- ⚠️ **不要往请求体里加未经实测的字段**。
  曾误加 ``can_contact: false``，但它其实是 ``purchase`` 对象的**响应**字段
  （实测响应里 ``purchase.can_contact == true``，而探测脚本并未发送它），
  不是请求参数。
  请求参数实测只有 ``product_id`` / ``license_key``。官方另有
  ``increment_uses_count`` 控制是否计数，本项目**刻意不发** ——
  避免我方验证推高用户的 uses，代价是 D3 的共享检测信号更弱。
- 响应解析采用**字段白名单**，绝不整体 ``json.dumps`` 落盘或进日志——
  因为实测响应里含明文 ``license_key``、``email``、``referrer``、``ip_country``。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# 产品常量（Gumroad 后台实际值，勿手改）
# ---------------------------------------------------------------------------

#: Gumroad Product ID。实测确认出现在 ``purchase.product_id``。
#: 验证成功**之后**仍需本地二次比对 —— 不能只看 success 字段，
#: 否则别的产品的 Gumroad key 也会解锁 Pro。
PRODUCT_ID = "wC1DNPpemAqtBZKYOYXbGw=="

#: 产品购买页。文案里的升级链接一律引用本常量，禁止再写硬编码 URL。
PRODUCT_URL = "https://wolfmanchao.gumroad.com/l/chinese-nlp-mcp-pro"

#: Gumroad License Key 校验接口（POST）。
VERIFY_ENDPOINT = "https://api.gumroad.com/v2/licenses/verify"

#: 引导文案统一使用的链接（= PRODUCT_URL，语义化别名）。
UPGRADE_URL = PRODUCT_URL

#: 产品 permalink（实测 ``purchase.permalink``）。用于第二重一致性校验。
PRODUCT_PERMALINK = "chinese-nlp-mcp-pro"

#: 网络参数。D4 决策：超时 8s、重试 0 次（24h 缓存已吸收抖动）。
TIMEOUT_SECONDS = 8.0
MAX_RETRIES = 0

#: **请求字段白名单**（2026-10-12 加固）。
#:
#: 背景：曾因看到响应里有 ``purchase.can_contact`` 就误以为它也是请求参数，
#: 凭空往请求体里加了 ``can_contact: false`` —— 而它其实是响应字段。
#: 这类"响应里有→ 推测也是入参"的错误协议层最容易犯，且不会报错，
#: 只是静默地发了一个 Gumroad 会忽略（或行为未知）的字段。
#:
#: 铁律：**新增任何请求字段前，必须先用探测脚本实测**，
#: 确认真实 key 与无效 key 两个分支都不返回异常。
#: 本白名单就是这条铁律的代码化 —— 集合不等即崩，
#: 开发期立刻暴露，绝不留到线上。
#:
#: 实测确认的 Gumroad verify 请求参数就是这两个（探测脚本 + 2026-10-12 复测）：
#:   product_id / license_key
#: 官方另有 ``increment_uses_count``，本项目**刻意不发**（见模块 docstring）。
ALLOWED_REQUEST_FIELDS = frozenset({"product_id", "license_key"})

log = logging.getLogger("chinese_nlp_mcp.licensing")

# ---------------------------------------------------------------------------
# 验证结论常量
# ---------------------------------------------------------------------------

#: 有效，且本地二次校验全过。
VALID = "valid"
#: key 无效（404 / success:false / 本地校验不过）。**立即降级，不走宽限。**
INVALID = "invalid"
#: 网络故障或服务端故障（DNS / 超时 / TLS / socket / HTTP 5xx）。
#: 此类**不证明 key 有问题**，由上层决定是否走 7 天宽限。
TRANSIENT = "transient"

#: 诊断原因码（会进 stderr，可安全展示 —— 不含任何 PII）
REASON_OK = "ok"
REASON_EMPTY_KEY = "empty_key"
REASON_HTTP_404 = "http_404"
REASON_HTTP_4XX = "http_4xx"
REASON_HTTP_5XX = "http_5xx"
REASON_SUCCESS_FALSE = "success_false"
REASON_BAD_JSON = "bad_json"
REASON_EMPTY_BODY = "empty_body"
REASON_NO_PURCHASE = "no_purchase"
REASON_PRODUCT_MISMATCH = "product_mismatch"
REASON_REFUNDED = "refunded"
REASON_DISPUTED = "disputed"
REASON_CHARGEBACKED = "chargebacked"
REASON_NETWORK = "network_error"


class VerifyResult:
    """在线验证结论。

    刻意**不携带原始响应** —— 因为实测响应含明文 license_key 与 PII，
    一旦被调用方 log 出去就是凭证泄漏。调用方只能拿到下面这些安全字段。
    """

    __slots__ = ("status", "reason", "product_ok", "sale_id", "uses", "test_purchase")

    def __init__(
        self,
        status: str,
        reason: str,
        product_ok: bool = False,
        sale_id: str | None = None,
        uses: int | None = None,
        test_purchase: bool = False,
    ) -> None:
        self.status = status  # VALID / INVALID / TRANSIENT
        self.reason = reason  # 诊断原因码
        self.product_ok = product_ok
        self.sale_id = sale_id  # 审计标识，用户报问题时可提供
        self.uses = uses  # 已用次数，仅供诊断，不参与有效性判定
        self.test_purchase = test_purchase

    @property
    def is_valid(self) -> bool:
        return self.status == VALID

    @property
    def is_transient(self) -> bool:
        return self.status == TRANSIENT

    def as_dict(self) -> dict:
        """给 ``status()`` / 日志用。字段全部白名单挑出，安全可展示。"""
        return {
            "status": self.status,
            "reason": self.reason,
            "product_ok": self.product_ok,
            "sale_id": self.sale_id,
            "uses": self.uses,
            "test_purchase": self.test_purchase,
        }

    def __repr__(self) -> str:  # pragma: no cover — 调试用，不含 PII
        return (
            f"VerifyResult(status={self.status!r}, reason={self.reason!r}, "
            f"product_ok={self.product_ok!r})"
        )


def _build_payload(key: str) -> bytes:
    """构造请求体，并断言字段集合与实测白名单完全一致。

    ⚠️ **这个断言必须放在 `verify_license_online` 的 try 之外**
    ——否则 AssertionError（Exception 子类）会被那个「兜住一切」的 except 吞掉，
    加固就形同虚设。这是 2026-10-12 反向验证 R9 实测发现的：
    断言写在 `_post_verify` 内部时，R9 的「加假字段必须抛错」用例直接失败。

    之所以用 assert 而非静默过滤：静默过滤会让「误加字段」变成
    一个永远没人发现的静默行为；而抛错能让它在开发期第一次运行时就炸出来。
    """
    request_fields = {"product_id": PRODUCT_ID, "license_key": key}

    assert (
        request_fields.keys() == ALLOWED_REQUEST_FIELDS
    ), (
        f"gumroad request fields drifted: {sorted(request_fields)} "
        f"!= {sorted(ALLOWED_REQUEST_FIELDS)}"
    )

    return json.dumps(request_fields).encode("utf-8")


def _post_verify_bytes(payload: bytes, timeout: float) -> tuple[int, bytes]:
    """POST 已构造好的请求体，返回 ``(http_status, body_bytes)``。

    HTTP 错误状态**不抛异常** —— 由调用方按状态码分流（404 / 4xx / 5xx 语义不同）。
    只有真正的网络层故障才向上抛。
    """
    req = urllib.request.Request(
        VERIFY_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "chinese-nlp-mcp",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 实测 Content-Type: application/json; charset=utf-8
            # 解析前不做过严断言 —— 不同网关可能不带 charset。
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        # 4xx / 5xx 在这里被转成返回值而非异常，因为三者语义完全不同：
        #   404 → key 不存在（INVALID，不给宽限）
        #   4xx → 请求有问题（INVALID，保守降级）
        #   5xx → 服务端故障（TRANSIENT，给宽限）
        try:
            body = exc.read()
        except Exception:  # noqa: BLE001
            body = b""
        return exc.code, body
    # URLError / socket.timeout / ssl.SSLError / ConnectionReset 全部属于
    # TRANSIENT —— 它们不证明 key 有问题。
    # ssl.SSLError 是 OSError 子类，ConnectionResetError 同样，都会被下面的 except 兜住。


def _parse(body: bytes) -> dict | None:
    """解析响应体。返回 dict 或 None（非 JSON / 非对象 / 空）。"""
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def verify_license_online(key: str, timeout: float = TIMEOUT_SECONDS) -> VerifyResult:
    """在线验证 license key。

    **本函数永不抛异常** —— 任何失败都转成 ``VerifyResult``。
    判据严格按 2026-10-11 实测：

    ====================================  ===============  ==============
    条件status            是否可走宽限
    ====================================  ===============  ==============
    HTTP 404                             INVALID         否
    HTTP 4xx（其他）                      INVALID         否
    HTTP 5xx                             TRANSIENT        是
    HTTP 200 且 body 非 JSON              INVALID         否
    HTTP 200 且 success != True          INVALID         否
    HTTP 200 且 success == True          进本地二次校验  —
    网络层故障（DNS/超时/TLS/socket）      TRANSIENT        是
    ====================================  ===============  ==============

    本地二次校验（4 项全过才算 VALID，字段缺失一律按不通过）：
        ``purchase.product_id == PRODUCT_ID``
        ``purchase.refunded is False``
        ``purchase.disputed is False``
        ``purchase.chargebacked is False``
    """
    key = (key or "").strip()
    if not key:
        return VerifyResult(INVALID, REASON_EMPTY_KEY)

    # ---- 构造请求体（白名单断言在此，刻意不放进下面的 try）----
    payload = _build_payload(key)

    # ---- 网络请求 ----
    try:
        status, body = _post_verify_bytes(payload, timeout)
    except Exception as exc:  # noqa: BLE001
        # URLError / socket.timeout / OSError / ssl.SSLError 全在此兜住。
        # 全部归为 TRANSIENT —— 不证明 key 有问题，允许上层走宽限。
        log.warning(f"license: network failure ({type(exc).__name__})")
        return VerifyResult(TRANSIENT, REASON_NETWORK)

    # ---- HTTP 分流 ----
    if status >= 500:
        # 服务端故障：不证明 key 有问题 → 允许上层走宽限
        return VerifyResult(TRANSIENT, REASON_HTTP_5XX)

    if status == 404:
        # 实测形态：无效 key 就是 404
        return VerifyResult(INVALID, REASON_HTTP_404)

    if status >= 400:
        return VerifyResult(INVALID, REASON_HTTP_4XX)

    # ---- 2xx：解析 body ----
    if not body:
        return VerifyResult(INVALID, REASON_EMPTY_BODY)

    data = _parse(body)
    if data is None:
        # 声称成功但 body 不是 JSON 对象 → 保守判无效（绝不做乐观默认）
        return VerifyResult(INVALID, REASON_BAD_JSON)

    # ---- success 字段是主判据 ----
    # 即使 HTTP 200，也必须查 success —— 这是防御「退款 / 吊销」的正确位置。
    if data.get("success") is not True:
        # 只记固定原因码，**不把 message 原文落盘/进日志**
        #（实测 message 为 "That license does not exist for the provided product."，
        #  当前不含 PII，但未来不可控）。
        return VerifyResult(INVALID, REASON_SUCCESS_FALSE)

    purchase = data.get("purchase")
    if not isinstance(purchase, dict):
        return VerifyResult(INVALID, REASON_NO_PURCHASE)

    # ---- 本地二次校验：字段白名单，绝不整体落盘 ----
    uses = data.get("uses")
    uses_val = uses if isinstance(uses, int) and not isinstance(uses, bool) else None
    sale_id = purchase.get("sale_id")
    sale_id_val = sale_id if isinstance(sale_id, str) else None
    test_purchase = purchase.get("test") is True

    def _reject(reason: str) -> VerifyResult:
        return VerifyResult(
            INVALID,
            reason,
            sale_id=sale_id_val,
            uses=uses_val,
            test_purchase=test_purchase,
        )

    # ① product_id 白名单（防「别的产品的 Gumroad key 解锁本产品」）
    if purchase.get("product_id") != PRODUCT_ID:
        return _reject(REASON_PRODUCT_MISMATCH)

    # ②③④ 退款 / 争议 / 拒付。字段缺失一律视为不通过（`is not False`）。
    if purchase.get("refunded") is not False:
        return _reject(REASON_REFUNDED)
    if purchase.get("disputed") is not False:
        return _reject(REASON_DISPUTED)
    if purchase.get("chargebacked") is not False:
        return _reject(REASON_CHARGEBACKED)

    # 测试订单（沙箱购买）**不参与有效性判定**（D1 决策）：
    # 若把 test 当无效，开发者本地永远调不通 P3。只标记 + 落盘供诊断。
    return VerifyResult(
        VALID,
        REASON_OK,
        product_ok=True,
        sale_id=sale_id_val,
        uses=uses_val,
        test_purchase=test_purchase,
    )


# re-export 让license.py 可以 ``from .gumroad import socket`` 之外直接拿 socket 判定
__all__ = [
    "PRODUCT_ID",
    "PRODUCT_URL",
    "PRODUCT_PERMALINK",
    "VERIFY_ENDPOINT",
    "UPGRADE_URL",
    "TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "VerifyResult",
    "verify_license_online",
    "VALID",
    "INVALID",
    "TRANSIENT",
]