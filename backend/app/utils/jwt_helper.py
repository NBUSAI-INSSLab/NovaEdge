"""JWT 认证辅助与角色鉴权装饰器。"""

from __future__ import annotations

from functools import wraps

from flask import g, request
from flask_jwt_extended import (decode_token, get_jwt, jwt_required,
                                verify_jwt_in_request)

from ..models import ROLE_ADMIN, ROLE_OPERATOR, User
from .response import CODE_FORBIDDEN, CODE_UNAUTHORIZED, fail

ROLE_WEIGHT = {"viewer": 1, "operator": 2, "admin": 3}


def current_user() -> User | None:
    return getattr(g, "current_user", None)


def login_required(func):
    """要求登录，并把用户对象注入 ``g.current_user``。"""

    @wraps(func)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        user = User.query.get(int(claims.get("sub", 0)))
        if user is None or not user.is_active:
            return fail("账号不存在或已禁用", CODE_UNAUTHORIZED, 401)
        g.current_user = user
        return func(*args, **kwargs)

    return wrapper


def role_required(minimum: str):
    """按最低角色等级鉴权：viewer < operator < admin。"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            user = User.query.get(int(claims.get("sub", 0)))
            if user is None or not user.is_active:
                return fail("账号不存在或已禁用", CODE_UNAUTHORIZED, 401)
            if ROLE_WEIGHT.get(user.role, 0) < ROLE_WEIGHT.get(minimum, 99):
                return fail(f"需要「{minimum}」及以上权限", CODE_FORBIDDEN, 403)
            g.current_user = user
            return func(*args, **kwargs)

        return wrapper

    return decorator


admin_required = role_required(ROLE_ADMIN)
operator_required = role_required(ROLE_OPERATOR)


def flexible_login_required(func):
    """既支持 ``Authorization`` 请求头，也支持 ``?token=`` 查询参数。

    浏览器的 ``<img>`` / ``<video>`` 标签无法自定义请求头，因此媒体预览类
    接口需要支持查询参数传递令牌（与 SSE 实时通道保持一致的鉴权方式）。
    令牌同样经过完整签名校验与账号有效性检查，安全性等价。
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        token = request.args.get("token", "")
        if not token:
            return login_required(func)(*args, **kwargs)
        try:
            claims = decode_token(token)
        except Exception:
            return fail("访问令牌无效或已过期", CODE_UNAUTHORIZED, 401)
        user = User.query.get(int(claims.get("sub", 0)))
        if user is None or not user.is_active:
            return fail("账号不存在或已禁用", CODE_UNAUTHORIZED, 401)
        g.current_user = user
        return func(*args, **kwargs)

    return wrapper
