"""平台用户与审计日志。"""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLE_LABELS = {
    ROLE_ADMIN: "系统管理员",
    ROLE_OPERATOR: "运维工程师",
    ROLE_VIEWER: "只读访客",
}


class User(db.Model, TimestampMixin, SerializerMixin):
    """平台操作用户（Web 控制台侧），与设备凭证完全分离。"""

    __tablename__ = "user"

    BASE_FIELDS = (
        "id", "username", "real_name", "role", "email", "phone",
        "department", "avatar", "is_active", "last_login_at", "last_login_ip",
        "created_at", "updated_at",
    )
    DATETIME_FIELDS = ("last_login_at", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True, comment="登录名")
    password_hash = db.Column(db.String(256), nullable=False, comment="口令散列（PBKDF2）")
    real_name = db.Column(db.String(64), default="", comment="姓名")
    role = db.Column(db.String(16), default=ROLE_VIEWER, nullable=False, index=True, comment="角色")
    email = db.Column(db.String(128), default="")
    phone = db.Column(db.String(32), default="")
    department = db.Column(db.String(64), default="", comment="所属部门/课题组")
    avatar = db.Column(db.String(255), default="")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(64), default="")

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def verify_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def to_dict(self, extra: dict | None = None) -> dict:
        return super().to_dict({"role_label": self.role_label, **(extra or {})})


class AuditLog(db.Model, SerializerMixin):
    """关键操作审计（登录、下发指令、删除媒体、修改规则等）。"""

    __tablename__ = "audit_log"

    BASE_FIELDS = (
        "id", "user_id", "username", "action", "target_type",
        "target_id", "detail", "ip", "created_at",
    )
    DATETIME_FIELDS = ("created_at",)

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    user_id = db.Column(BigIntPK, nullable=True, index=True)
    username = db.Column(db.String(64), default="")
    action = db.Column(db.String(64), nullable=False, index=True, comment="动作编码")
    target_type = db.Column(db.String(32), default="", comment="对象类型")
    target_id = db.Column(db.String(64), default="", comment="对象 ID")
    detail = db.Column(db.JSON, default=dict, comment="附加信息")
    ip = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, nullable=False, index=True)
