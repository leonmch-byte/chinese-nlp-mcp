"""Gumroad 产品常量与（未来的）License Key 验证客户端。

⚠️ **P1/P2' 阶段本模块只提供常量，不发起任何网络请求。**
真正的License Key 验证属P3 范围，届时会新增 ``verify_license()``。

设计约束（沿用licensing/ 分层原则）：
- 本模块**不依赖任何 MCP 框架**（不 import fastmcp / mcp）。
- 验证逻辑在 P3 引入时，也必须把「网络 I/O」与「异常定义」分开：
  网络失败一律降级为免费层，**绝不抛异常阻断启动**。

隐私承诺（P3 实施时必须严格遵守）：
  验证请求**只发送 license key 与 product_id**，
  不发送任何用户数据（文本、工具名、计数、设备 ID 均不上报）。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 产品常量（Gumroad 后台实际值，勿手改）
# ---------------------------------------------------------------------------

#: Gumroad Product ID。验证时用于白名单比对 —— key 有效但属于别的产品
#: 时，Gumroad 返回 HTTP 200 + success:false.product_id 不匹配，
#: 因此**必须**本地再校验一次，不能只看 success 字段。
PRODUCT_ID = "wC1DNPpemAqtBZKYOYXbGw=="

#: 产品购买页。文案里的升级链接一律引用本常量，禁止再写硬编码 URL。
PRODUCT_URL = "https://wolfmanchao.gumroad.com/l/chinese-nlp-mcp-pro"

#: Gumroad License Key 校验接口（POST）。
VERIFY_ENDPOINT = "https://api.gumroad.com/v2/licenses/verify"

#: 引导文案统一使用的链接（= PRODUCT_URL，语义化别名）。
UPGRADE_URL = PRODUCT_URL