"""Stable public errors. Upstream exception strings may contain private data."""

class ConnectorError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(code)

    def result(self):
        return {"ok": False, "error": {"code": self.code, "message": self.message,
                                       "retryable": self.retryable}}


def require(condition, code, message):
    if not condition:
        raise ConnectorError(code, message)
