# -*- coding: utf-8 -*-
"""body 模組共用的例外。"""


class ApiError(Exception):
    """要回給前端的錯誤：message 會放進 {ok: false, error}，status 是 HTTP 狀態碼。"""

    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra          # 額外欄位，例如 need='profile'，前端依此顯示對應的按鈕

    @classmethod
    def not_found(cls, message):
        return cls(message, 404)

    @classmethod
    def unauthorized(cls, message='登入已逾時，請重新登入。'):
        return cls(message, 401)
