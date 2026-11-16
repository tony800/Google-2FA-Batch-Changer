"""
@file __init__.py
@brief 谷歌业务后端模块
@details 包含 Google 账号 2FA 更改的核心业务逻辑
"""

from .google_auth import google_login
from .change_2fa_service import (
    change_2fa_for_account,
    process_change_2fa_batch,
    Change2FAStatus,
)

__all__ = [
    'google_login',
    'change_2fa_for_account',
    'process_change_2fa_batch',
    'Change2FAStatus',
]
