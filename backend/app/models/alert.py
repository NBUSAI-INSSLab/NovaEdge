"""告警规则与告警记录（参考 ThingsBoard alarm 的 severity / status 状态机）。"""

from __future__ import annotations

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin

SEVERITIES = {
    "critical": "紧急",
    "major": "严重",
    "minor": "一般",
    "warning": "提示",
}

OPERATORS = {
    "gt": "大于",
    "ge": "大于等于",
    "lt": "小于",
    "le": "小于等于",
    "eq": "等于",
    "ne": "不等于",
    "out_of_range": "超出区间",
}

ALERT_ACTIVE = "active"
ALERT_ACKED = "acked"
ALERT_CLEARED = "cleared"
ALERT_STATUS_LABELS = {
    ALERT_ACTIVE: "待处理",
    ALERT_ACKED: "已确认",
    ALERT_CLEARED: "已恢复",
}


class AlertRule(db.Model, TimestampMixin, SerializerMixin):
    """阈值告警规则：支持「持续 N 秒才触发」与静默期，避免抖动误报。"""

    __tablename__ = "alert_rule"

    BASE_FIELDS = ("id", "name", "node_id", "group_id", "metric_key", "operator",
                   "threshold", "threshold2", "duration_sec", "severity", "silence_sec",
                   "enabled", "notify_channels", "description", "trigger_count",
                   "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    name = db.Column(db.String(96), nullable=False, comment="规则名称")
    node_id = db.Column(BigIntPK, default=0, index=True, comment="0 表示对全部节点生效")
    group_id = db.Column(BigIntPK, default=0, index=True, comment="按分组生效")
    metric_key = db.Column(db.String(64), nullable=False, index=True)
    operator = db.Column(db.String(16), default="gt", nullable=False)
    threshold = db.Column(db.Float, nullable=True)
    threshold2 = db.Column(db.Float, nullable=True, comment="区间告警的上限")
    duration_sec = db.Column(db.Integer, default=0, comment="持续满足条件多久才告警")
    severity = db.Column(db.String(16), default="warning", nullable=False, index=True)
    silence_sec = db.Column(db.Integer, default=300, comment="同一规则静默期")
    enabled = db.Column(db.Boolean, default=True, nullable=False, index=True)
    notify_channels = db.Column(db.JSON, default=list, comment='["console","email","webhook"]')
    description = db.Column(db.String(255), default="")
    trigger_count = db.Column(db.Integer, default=0)

    @property
    def severity_label(self) -> str:
        return SEVERITIES.get(self.severity, self.severity)

    @property
    def operator_label(self) -> str:
        return OPERATORS.get(self.operator, self.operator)

    def to_dict(self, extra: dict | None = None) -> dict:
        return super().to_dict({
            "severity_label": self.severity_label,
            "operator_label": self.operator_label,
            **(extra or {}),
        })


class AlertRecord(db.Model, SerializerMixin):
    """告警实例，状态机：active -> acked -> cleared。"""

    __tablename__ = "alert_record"

    BASE_FIELDS = ("id", "rule_id", "node_id", "metric_key", "severity", "title",
                   "content", "trigger_value", "clear_value", "status", "count",
                   "started_at", "acked_at", "acked_by", "cleared_at", "created_at")
    DATETIME_FIELDS = ("started_at", "acked_at", "cleared_at", "created_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    rule_id = db.Column(BigIntPK, db.ForeignKey("alert_rule.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    metric_key = db.Column(db.String(64), default="")
    severity = db.Column(db.String(16), default="warning", nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    content = db.Column(db.String(512), default="")
    trigger_value = db.Column(db.Float, nullable=True)
    clear_value = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(16), default=ALERT_ACTIVE, nullable=False, index=True)
    count = db.Column(db.Integer, default=1, comment="同一次告警的重复次数")
    started_at = db.Column(db.DateTime, nullable=False, index=True)
    acked_at = db.Column(db.DateTime, nullable=True)
    acked_by = db.Column(db.String(64), default="")
    cleared_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)

    @property
    def severity_label(self) -> str:
        return SEVERITIES.get(self.severity, self.severity)

    @property
    def status_label(self) -> str:
        return ALERT_STATUS_LABELS.get(self.status, self.status)

    def to_dict(self, extra: dict | None = None) -> dict:
        return super().to_dict({
            "severity_label": self.severity_label,
            "status_label": self.status_label,
            **(extra or {}),
        })
