"""chinese-nlp-mcp 付费层计量与授权（P1）。

P1 范围：**纯本地计量，不含任何网络请求**。
- `paths`   跨平台状态目录解析（pathlib + os.environ，不引第三方依赖）
- `errors`  QuotaExceeded —— 商业状态异常，独立基类
- `store`   StateStore —— HMAC 签名、防日期回拨、7 天历史剪枝
- `quota`   QuotaGuard —— 次数限制 + 参数上限
- `tier`    TierProvider —— P1 恒为 free，P3 替换实现

硬性约束（勿破坏）：
1. 任何内部异常都不允许让服务器不可用 —— 全部吞掉并放行，只记 stderr。
2. 日志一律写 stderr，禁止 print 到 stdout（会污染 JSON-RPC 协议流）。
3. 状态文件不含任何明文凭证。
"""

from .errors import QuotaExceeded
from .paths import resolve_state_dir
from .quota import FREE_LIMITS, FREE_MAX_TEXT_LEN, PAID_SOFT_CAP, QuotaGuard
from .store import StateStore
from .tier import TierProvider

__all__ = [
    "QuotaExceeded",
    "resolve_state_dir",
    "FREE_LIMITS",
    "FREE_MAX_TEXT_LEN",
    "PAID_SOFT_CAP",
    "QuotaGuard",
    "StateStore",
    "TierProvider",
]

__version__ = "0.1.1-p1a"