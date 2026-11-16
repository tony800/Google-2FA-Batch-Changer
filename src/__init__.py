"""
@file __init__.py
@brief 核心模块包
@details 包含数据库管理、比特浏览器API等公共模块
"""

from .database import DBManager

try:
    from .bit_api import BitBrowserAPI
except ImportError as e:
    print(f"[core] bit_api 导入失败: {e}")
    BitBrowserAPI = None

__all__ = [
    'DBManager',
    'BitBrowserAPI',
]
