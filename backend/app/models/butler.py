"""智能管家：会话消息与分析报告。"""

from __future__ import annotations

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin, to_iso, utcnow

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"


class ButlerMessage(db.Model, TimestampMixin, SerializerMixin):
    """智能管家会话消息（含工具调用轨迹）。"""

    __tablename__ = "butler_message"

    BASE_FIELDS = ("id", "session_id", "user_id", "role", "content",
                   "tool_name", "tool_args", "tool_result", "created_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    session_id = db.Column(db.String(48), nullable=False, index=True)
    user_id = db.Column(BigIntPK, default=0, index=True)
    role = db.Column(db.String(16), nullable=False)            # user / assistant / tool
    content = db.Column(db.Text, default="")
    tool_name = db.Column(db.String(64), default="")
    tool_args = db.Column(db.JSON, default=dict)
    tool_result = db.Column(db.JSON, default=None)
    engine = db.Column(db.String(24), default="")              # llm / builtin（assistant 消息记录来源）

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args or {},
            "tool_result": self.tool_result,
            "engine": self.engine,
            "created_at": to_iso(self.created_at),
        }


class ButlerReport(db.Model, TimestampMixin, SerializerMixin):
    """平台分析报告。"""

    __tablename__ = "butler_report"

    BASE_FIELDS = ("id", "title", "report_type", "status", "content_md",
                   "summary", "data_snapshot", "engine", "created_by",
                   "node_count", "alert_count", "telemetry_count", "created_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    title = db.Column(db.String(160), nullable=False)
    report_type = db.Column(db.String(24), default="on_demand", index=True)  # daily/weekly/on_demand
    status = db.Column(db.String(16), default="done", index=True)  # generating / done / failed
    content_md = db.Column(db.Text, default="")
    summary = db.Column(db.Text, default="")                   # 摘要（一两句话）
    data_snapshot = db.Column(db.JSON, default=dict)           # 生成时的平台数据快照
    engine = db.Column(db.String(24), default="builtin")       # llm / builtin
    created_by = db.Column(db.String(64), default="")
    node_count = db.Column(db.Integer, default=0)
    alert_count = db.Column(db.Integer, default=0)
    telemetry_count = db.Column(db.Integer, default=0)

    def to_dict(self, with_content=False):
        data = {
            "id": self.id,
            "title": self.title,
            "report_type": self.report_type,
            "status": self.status,
            "summary": self.summary,
            "engine": self.engine,
            "created_by": self.created_by,
            "node_count": self.node_count,
            "alert_count": self.alert_count,
            "telemetry_count": self.telemetry_count,
            "created_at": to_iso(self.created_at),
        }
        if with_content:
            data["content_md"] = self.content_md
            data["data_snapshot"] = self.data_snapshot or {}
        return data
