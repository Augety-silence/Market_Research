"""对外可见的错误类型，消息可直接打印给使用者。"""


class CrawlError(Exception):
    """可以安全展示的错误；不包含 Cookie、签名参数等敏感信息。"""


class LoginRequired(CrawlError):
    """接口需要登录态，但当前没有可用 Cookie。"""


class RiskControl(CrawlError):
    """触发风控（HTTP 412/429 或业务码 -352/-412），应当停止。"""
