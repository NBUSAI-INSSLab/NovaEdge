"""API 蓝图注册。"""

from flask import Blueprint

from . import (alerts, auth, butler, commands, dashboard, device, media, metrics,
               nodes, stream, system, upload, users)

API_PREFIX = "/api/v1"

BLUEPRINTS: list[tuple[Blueprint, str]] = [
    (auth.bp, "/auth"),
    (users.bp, "/users"),
    (nodes.bp, "/nodes"),
    (metrics.bp, "/metrics"),
    (media.bp, "/media"),
    (alerts.bp, "/alerts"),
    (commands.bp, "/commands"),
    (dashboard.bp, "/dashboard"),
    (butler.bp, "/butler"),
    (system.bp, "/system"),
    (stream.bp, "/stream"),
    # ---- 设备侧（节点 Agent 调用）----
    (device.bp, "/device"),
    (upload.bp, "/upload"),
]


def register_blueprints(app):
    for blueprint, suffix in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=f"{API_PREFIX}{suffix}")
