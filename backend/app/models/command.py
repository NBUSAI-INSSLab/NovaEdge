"""下行指令（RPC）与系统配置表。"""

from __future__ import annotations

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin

CMD_PENDING = "pending"
CMD_SENT = "sent"
CMD_SUCCESS = "success"
CMD_FAILED = "failed"
CMD_TIMEOUT = "timeout"
CMD_STATUS_LABELS = {
    CMD_PENDING: "待下发",
    CMD_SENT: "已下发",
    CMD_SUCCESS: "执行成功",
    CMD_FAILED: "执行失败",
    CMD_TIMEOUT: "已超时",
}

# 平台内置指令字典：节点 Agent 按 command 编码实现处理逻辑
COMMAND_CATALOG = {
    "capture_image": {
        "label": "抓拍图片",
        "params": {"resolution": "1920x1080", "quality": 90},
        "desc": "立即抓拍一张图片并回传平台",
    },
    "start_record": {
        "label": "开始录像",
        "params": {"duration": 30, "resolution": "1280x720", "fps": 25},
        "desc": "录制指定时长的视频并上传",
    },
    "stop_record": {
        "label": "停止录像",
        "params": {},
        "desc": "提前结束当前录像任务",
    },
    "set_interval": {
        "label": "设置上报周期",
        "params": {"interval": 60},
        "desc": "修改传感器数据上报间隔（秒）",
    },
    "sync_config": {
        "label": "同步配置",
        "params": {},
        "desc": "节点拉取最新采集配置",
    },
    "reboot": {
        "label": "重启节点",
        "params": {"delay": 5},
        "desc": "延迟若干秒后重启边缘节点",
    },
    "self_test": {
        "label": "自检",
        "params": {},
        "desc": "检测摄像头/传感器/网络连通性",
    },
}


class Command(db.Model, SerializerMixin):
    """节点下行指令：pending -> sent -> success/failed/timeout。"""

    __tablename__ = "command"

    BASE_FIELDS = ("id", "cmd_id", "node_id", "command", "params", "status",
                   "channel", "result", "issued_by", "timeout_sec", "retry_count",
                   "issued_at", "sent_at", "ack_at", "created_at")
    DATETIME_FIELDS = ("issued_at", "sent_at", "ack_at", "created_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    cmd_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    command = db.Column(db.String(64), nullable=False, index=True)
    params = db.Column(db.JSON, default=dict)
    status = db.Column(db.String(16), default=CMD_PENDING, nullable=False, index=True)
    channel = db.Column(db.String(16), default="http-poll",
                        comment="实际下发通道：mqtt 实时下发 / http-poll 轮询取指令")
    result = db.Column(db.JSON, default=dict, comment="节点执行回执")
    issued_by = db.Column(db.String(64), default="", comment="下发人")
    timeout_sec = db.Column(db.Integer, default=30)
    retry_count = db.Column(db.Integer, default=0)
    issued_at = db.Column(db.DateTime, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    ack_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False)

    @property
    def status_label(self) -> str:
        return CMD_STATUS_LABELS.get(self.status, self.status)

    @property
    def channel_label(self) -> str:
        return "MQTT 实时" if self.channel == "mqtt" else "HTTP 轮询"

    @property
    def command_label(self) -> str:
        return COMMAND_CATALOG.get(self.command, {}).get("label", self.command)

    def to_dict(self, extra: dict | None = None) -> dict:
        return super().to_dict({
            "status_label": self.status_label,
            "command_label": self.command_label,
            "channel_label": self.channel_label,
            **(extra or {}),
        })


class SysConfig(db.Model, TimestampMixin, SerializerMixin):
    """平台运行时配置（键值对，JSON 值）。"""

    __tablename__ = "sys_config"

    BASE_FIELDS = ("id", "cfg_key", "cfg_value", "category", "description", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    cfg_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    cfg_value = db.Column(db.JSON, default=dict)
    category = db.Column(db.String(32), default="common", index=True)
    description = db.Column(db.String(255), default="")
