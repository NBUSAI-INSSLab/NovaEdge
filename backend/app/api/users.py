"""平台用户管理接口（仅管理员）。"""

from __future__ import annotations

from flask import Blueprint, request
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import (ROLE_ADMIN, ROLE_LABELS, AuditLog, User, utcnow)
from ..utils.jwt_helper import admin_required, current_user, login_required
from ..utils.response import (CODE_CONFLICT, CODE_NOT_FOUND, fail,
                              get_page_args, ok, paginated, truthy)

bp = Blueprint("users", __name__)


@bp.get("")
@login_required
def list_users():
    page, page_size = get_page_args(20)
    query = User.query
    if request.args.get("role"):
        query = query.filter(User.role == request.args["role"])
    if request.args.get("keyword"):
        like = f"%{request.args['keyword'].strip()}%"
        query = query.filter(db.or_(User.username.like(like), User.real_name.like(like)))
    total = query.count()
    rows = query.order_by(User.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return paginated([u.to_dict() for u in rows], total, page, page_size)


@bp.get("/roles")
@login_required
def roles():
    return ok([{"value": k, "label": v} for k, v in ROLE_LABELS.items()])


@bp.post("")
@admin_required
def create_user():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or len(password) < 6:
        return fail("用户名不能为空，密码至少 6 位", 400)
    if User.query.filter_by(username=username).first():
        return fail(f"用户名 {username} 已存在", CODE_CONFLICT)
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        real_name=str(payload.get("real_name", "")),
        role=str(payload.get("role", "viewer")),
        email=str(payload.get("email", "")),
        phone=str(payload.get("phone", "")),
        department=str(payload.get("department", "")),
        is_active=truthy(payload.get("is_active"), True),
    )
    db.session.add(user)
    db.session.commit()
    return ok(user.to_dict(), "用户已创建")


@bp.put("/<int:user_id>")
@admin_required
def update_user(user_id: int):
    user = User.query.get(user_id)
    if user is None:
        return fail("用户不存在", CODE_NOT_FOUND, 404)
    payload = request.get_json(silent=True) or {}
    for field in ("real_name", "role", "email", "phone", "department"):
        if field in payload:
            setattr(user, field, str(payload[field]))
    if "is_active" in payload:
        if user.id == current_user().id and not truthy(payload["is_active"], True):
            return fail("不能禁用当前登录账号", 400)
        user.is_active = truthy(payload["is_active"], True)
    if payload.get("password"):
        if len(str(payload["password"])) < 6:
            return fail("密码至少 6 位", 400)
        user.set_password(str(payload["password"]))
    db.session.commit()
    return ok(user.to_dict(), "用户已更新")


@bp.delete("/<int:user_id>")
@admin_required
def delete_user(user_id: int):
    user = User.query.get(user_id)
    if user is None:
        return fail("用户不存在", CODE_NOT_FOUND, 404)
    if user.id == current_user().id:
        return fail("不能删除当前登录账号", 400)
    if user.role == ROLE_ADMIN and User.query.filter_by(role=ROLE_ADMIN).count() <= 1:
        return fail("至少需要保留一名管理员", 400)
    db.session.delete(user)
    db.session.commit()
    return ok(message="用户已删除")


@bp.get("/audit-logs")
@login_required
def audit_logs():
    page, page_size = get_page_args(30)
    query = AuditLog.query
    if request.args.get("action"):
        query = query.filter(AuditLog.action == request.args["action"])
    if request.args.get("username"):
        query = query.filter(AuditLog.username == request.args["username"])
    total = query.count()
    rows = query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return paginated([r.to_dict() for r in rows], total, page, page_size)
