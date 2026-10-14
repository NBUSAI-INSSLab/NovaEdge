"""登录认证接口。"""

from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import create_access_token

from ..extensions import db
from ..models import ROLE_LABELS, AuditLog, User, utcnow
from ..utils.jwt_helper import current_user, login_required
from ..utils.response import CODE_UNAUTHORIZED, fail, ok

bp = Blueprint("auth", __name__)


def _write_audit(user: User, action: str, detail: dict | None = None) -> None:
    db.session.add(AuditLog(
        user_id=user.id, username=user.username, action=action,
        target_type="user", target_id=str(user.id), detail=detail or {},
        ip=request.remote_addr or "", created_at=utcnow(),
    ))
    db.session.commit()


@bp.post("/login")
def login():
    """账号密码登录，返回 JWT 与用户信息。"""
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        return fail("请输入用户名与密码", 400)

    user = User.query.filter_by(username=username).first()
    if user is None or not user.verify_password(password):
        return fail("用户名或密码错误", CODE_UNAUTHORIZED, 401)
    if not user.is_active:
        return fail("账号已被禁用，请联系管理员", CODE_UNAUTHORIZED, 401)

    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role, "username": user.username,
                           "real_name": user.real_name},
    )
    user.last_login_at = utcnow()
    user.last_login_ip = request.remote_addr or ""
    db.session.commit()
    _write_audit(user, "login", {"ip": user.last_login_ip})

    return ok({"token": token, "user": user.to_dict(), "roles": ROLE_LABELS}, "登录成功")


@bp.get("/profile")
@login_required
def profile():
    return ok(current_user().to_dict(), "查询成功")


@bp.post("/change-password")
@login_required
def change_password():
    payload = request.get_json(silent=True) or {}
    old = str(payload.get("old_password", ""))
    new = str(payload.get("new_password", ""))
    if len(new) < 6:
        return fail("新密码长度不得少于 6 位", 400)
    user = current_user()
    if not user.verify_password(old):
        return fail("原密码不正确", 400)
    user.set_password(new)
    db.session.commit()
    _write_audit(user, "change_password")
    return ok(message="密码修改成功")


@bp.post("/logout")
@login_required
def logout():
    _write_audit(current_user(), "logout")
    return ok(message="已退出登录")
