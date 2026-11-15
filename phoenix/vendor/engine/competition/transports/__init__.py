"""比赛平台传输层（设计 8.3，COMP-02）。

- ``http``：官方 REST（第 1 顺位）。
- ``playwright``：经用户授权的浏览器会话（第 2 顺位，可选依赖）。

选择规则见 ``phoenix.vendor.engine.competition.platforms.base.select_transport_kind``。
"""

from phoenix.vendor.engine.competition.transports.http import (
    RestResponse,
    RestTransport,
    parse_retry_after,
)
from phoenix.vendor.engine.competition.transports.playwright import (
    PlaywrightTransport,
    playwright_available,
)

__all__ = [
    "PlaywrightTransport",
    "RestResponse",
    "RestTransport",
    "parse_retry_after",
    "playwright_available",
]
