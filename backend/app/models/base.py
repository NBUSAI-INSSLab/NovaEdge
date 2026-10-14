"""模型基础设施：主键类型、时间戳混合类、UTC 工具。

设计要点
--------
* 主键统一使用 ``BigInteger().with_variant(Integer, "sqlite")``，
  保证 MySQL 用 BIGINT 自增、SQLite 用 INTEGER PRIMARY KEY 自增，双兼容。
* 时间统一以 **naive UTC** 落库，对外序列化时补 ``Z`` 后缀，
  由前端 ``new Date()`` 自动换算为本地时区（北京时间）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Integer

from ..extensions import db

# MySQL: BIGINT AUTO_INCREMENT / SQLite: INTEGER PRIMARY KEY AUTOINCREMENT
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """当前 UTC 时间（naive，便于 SQLite 存储）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_iso(dt: datetime | None) -> str | None:
    """把 naive UTC datetime 序列化为带 Z 的 ISO8601 字符串。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds") + "Z"


def to_ts(dt: datetime | None) -> int | None:
    """naive UTC datetime -> 毫秒时间戳。"""
    if dt is None:
        return None
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


class TimestampMixin:
    """创建 / 更新时间戳。"""

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SerializerMixin:
    """统一序列化入口，子类通过 ``BASE_FIELDS`` 声明字段。"""

    BASE_FIELDS: tuple[str, ...] = ()
    DATETIME_FIELDS: tuple[str, ...] = ("created_at", "updated_at")

    def to_dict(self, extra: dict | None = None) -> dict:
        data: dict = {}
        for field in self.BASE_FIELDS:
            if not hasattr(self, field):
                continue
            value = getattr(self, field)
            if field in self.DATETIME_FIELDS:
                data[field] = to_iso(value)
                data[f"{field}_ts"] = to_ts(value)
            else:
                data[field] = value
        if extra:
            data.update(extra)
        return data
