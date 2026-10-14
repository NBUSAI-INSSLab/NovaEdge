"""设备侧身份认证（HTTP 接入使用）。

节点无需用户账号，采用：
    X-Node-Key: <access_key>
    X-Node-Secret: <secret>        （或 Authorization: Device <key>:<secret>）

校验逻辑与 Web 用户 JWT 完全隔离，避免设备密钥泄漏影响控制台。
"""

from __future__ import annotations

import hmac
from functools import wraps

from flask import g, request
from werkzeug.security import check_password_hash

from ..models import Node, NodeCredential, STATUS_DISABLED, utcnow
from .response import CODE_UNAUTHORIZED, fail


def _extract_credentials() -> tuple[str, str]:
    access_key = request.headers.get("X-Node-Key", "") or ""
    secret = request.headers.get("X-Node-Secret", "") or ""
    if not access_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Device "):
            payload = auth[7:].strip()
            if ":" in payload:
                access_key, secret = payload.split(":", 1)
    if not access_key:
        access_key = request.args.get("node_key", "")
        secret = secret or request.args.get("node_secret", "")
    return access_key.strip(), secret.strip()


def authenticate_node(access_key: str, secret: str) -> Node | None:
    """校验设备凭证，成功返回 Node 并刷新 last_used_at。"""
    if not access_key or not secret:
        return None
    cred = NodeCredential.query.filter_by(access_key=access_key, is_active=True).first()
    if cred is None:
        return None
    if cred.expires_at is not None and cred.expires_at < utcnow():
        return None
    if not check_password_hash(cred.secret_hash, secret):
        # 兼容明文比对（仅用于迁移期，规范流程始终使用散列）
        if not hmac.compare_digest(cred.secret_hash, secret):
            return None
    node = Node.query.get(cred.node_id)
    if node is None or not node.enabled:
        return None
    cred.last_used_at = utcnow()
    return node


def device_auth_required(func):
    """设备接口装饰器：注入 ``g.node``。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        access_key, secret = _extract_credentials()
        node = authenticate_node(access_key, secret)
        if node is None:
            return fail("设备凭证无效或已失效", CODE_UNAUTHORIZED, 401)
        if node.status == STATUS_DISABLED:
            return fail("节点已被停用", CODE_UNAUTHORIZED, 401)
        g.node = node
        g.node_credential_key = access_key
        return func(*args, **kwargs)

    return wrapper
