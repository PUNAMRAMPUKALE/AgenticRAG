from __future__ import annotations


class AppError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class AuthError(AppError):
    pass


class ConversationNotFound(AppError):
    def __init__(self, detail: str = "Conversation not found"):
        super().__init__(404, detail)


class IndexNotReady(AppError):
    def __init__(self):
        super().__init__(503, "Index not ready")


class EmptyQuery(AppError):
    def __init__(self):
        super().__init__(400, "Empty query")
