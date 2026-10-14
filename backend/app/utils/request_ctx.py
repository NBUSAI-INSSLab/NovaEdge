"""HTTP 接入层的请求体解析辅助。"""

from __future__ import annotations

from flask import request

from ..models import utcnow


def json_body() -> dict:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def node_device_info() -> dict:
    """从上报负载中提取设备自描述信息（首次上线自动补全）。"""
    return {
        "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
        "user_agent": request.headers.get("User-Agent", ""),
        "server_time": utcnow(),
    }
