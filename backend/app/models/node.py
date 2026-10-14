"""边缘节点（树莓派 / 香橙派等计算节点）相关表。

对应 ThingsBoard 的 device / device_credentials / 设备属性思路，
但做了适配：算力节点的资源画像（CPU/内存/磁盘/温度）独立成心跳表，
并冗余一份最新值到 node 表，避免列表页 N+1 查询。
"""

from __future__ import annotations

import secrets

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin, utcnow

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_DISABLED = "disabled"
STATUS_LABELS = {
    STATUS_ONLINE: "在线",
    STATUS_OFFLINE: "离线",
    STATUS_DISABLED: "已停用",
}

NODE_TYPES = {
    "raspberrypi": "树莓派",
    "orangepi": "香橙派",
    "jetson": "英伟达 Jetson",
    "rk3588": "瑞芯微 RK3588",
    "generic": "通用 Linux 节点",
}


class NodeGroup(db.Model, TimestampMixin, SerializerMixin):
    """节点分组 / 场景区域，例如「实验楼 A 区」「厂区北门」。"""

    __tablename__ = "node_group"

    BASE_FIELDS = ("id", "name", "code", "parent_id", "description", "sort_order", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    name = db.Column(db.String(64), nullable=False, comment="分组名称")
    code = db.Column(db.String(32), default="", comment="分组编码")
    parent_id = db.Column(BigIntPK, default=0, comment="上级分组，0 为顶级")
    description = db.Column(db.String(255), default="")
    sort_order = db.Column(db.Integer, default=0)


class Node(db.Model, TimestampMixin, SerializerMixin):
    """边缘计算节点主表。"""

    __tablename__ = "node"

    BASE_FIELDS = (
        "id", "node_uid", "name", "node_type", "model", "serial_no", "group_id",
        "ip_address", "mac_address", "os_version", "agent_version", "firmware_version",
        "location", "longitude", "latitude", "capabilities", "status",
        "last_seen_at", "last_boot_at", "uptime_seconds",
        "cpu_percent", "mem_percent", "disk_percent", "cpu_temp",
        "report_interval", "enabled", "remark", "created_at", "updated_at",
    )
    DATETIME_FIELDS = ("last_seen_at", "last_boot_at", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_uid = db.Column(db.String(64), unique=True, nullable=False, index=True,
                         comment="节点唯一编码，如 RPI-LAB-001")
    name = db.Column(db.String(96), nullable=False, comment="节点名称")
    node_type = db.Column(db.String(32), default="generic", nullable=False, index=True)
    model = db.Column(db.String(96), default="", comment="硬件型号，如 Raspberry Pi 4B 8G")
    serial_no = db.Column(db.String(96), default="", comment="设备序列号")
    group_id = db.Column(BigIntPK, default=0, index=True, comment="所属分组")
    ip_address = db.Column(db.String(64), default="")
    mac_address = db.Column(db.String(64), default="")
    os_version = db.Column(db.String(96), default="")
    agent_version = db.Column(db.String(32), default="")
    firmware_version = db.Column(db.String(32), default="")
    location = db.Column(db.String(128), default="", comment="部署位置描述")
    longitude = db.Column(db.Numeric(10, 6), nullable=True)
    latitude = db.Column(db.Numeric(10, 6), nullable=True)
    capabilities = db.Column(db.JSON, default=dict,
                             comment='能力清单 {"camera":true,"video":true,"sensors":["temp","hum"]}')
    status = db.Column(db.String(16), default=STATUS_OFFLINE, nullable=False, index=True)
    last_seen_at = db.Column(db.DateTime, nullable=True, index=True)
    last_boot_at = db.Column(db.DateTime, nullable=True)
    uptime_seconds = db.Column(db.Integer, default=0)
    cpu_percent = db.Column(db.Float, default=0.0, comment="最新 CPU 使用率 %")
    mem_percent = db.Column(db.Float, default=0.0)
    disk_percent = db.Column(db.Float, default=0.0)
    cpu_temp = db.Column(db.Float, default=0.0, comment="SoC 温度 ℃")
    report_interval = db.Column(db.Integer, default=60, comment="节点上报周期（秒）")
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    remark = db.Column(db.String(255), default="")

    credentials = db.relationship("NodeCredential", backref="node", lazy="select",
                                  cascade="all, delete-orphan")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def node_type_label(self) -> str:
        return NODE_TYPES.get(self.node_type, self.node_type)

    def touch(self, when=None) -> None:
        self.last_seen_at = when or utcnow()

    def to_dict(self, extra: dict | None = None) -> dict:
        payload = {
            "status_label": self.status_label,
            "node_type_label": self.node_type_label,
            "online": self.status == STATUS_ONLINE,
        }
        payload.update(extra or {})
        return super().to_dict(payload)


class NodeCredential(db.Model, TimestampMixin, SerializerMixin):
    """设备接入凭证。

    * ``access_key``   —— 节点唯一标识，MQTT ClientID / HTTP Header ``X-Node-Key``
    * ``secret_hash``  —— 密钥散列，仅在节点注册时明文返回一次
    * ``mqtt_username`` / ``mqtt_password`` —— 供 EMQX 认证使用（可对接 HTTP 认证插件）
    """

    __tablename__ = "node_credential"

    BASE_FIELDS = ("id", "node_id", "access_key", "token_type", "is_active",
                   "expires_at", "last_used_at", "created_at", "updated_at")
    DATETIME_FIELDS = ("expires_at", "last_used_at", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    access_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    secret_hash = db.Column(db.String(256), nullable=False)
    mqtt_username = db.Column(db.String(64), default="")
    mqtt_password = db.Column(db.String(128), default="")
    token_type = db.Column(db.String(16), default="device", comment="device | mqtt")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)

    @staticmethod
    def new_access_key(node_uid: str) -> str:
        return f"ak_{node_uid.lower().replace('-', '_')}_{secrets.token_hex(4)}"

    @staticmethod
    def new_secret() -> str:
        return secrets.token_urlsafe(24)


class NodeHeartbeat(db.Model, SerializerMixin):
    """节点资源心跳明细（保留原始序列，用于绘制资源曲线）。"""

    __tablename__ = "node_heartbeat"

    BASE_FIELDS = ("id", "node_id", "cpu_percent", "mem_percent", "disk_percent",
                   "cpu_temp", "net_rx_kbps", "net_tx_kbps", "uptime_seconds",
                   "process_count", "created_at")
    DATETIME_FIELDS = ("created_at",)

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    cpu_percent = db.Column(db.Float, default=0.0)
    mem_percent = db.Column(db.Float, default=0.0)
    disk_percent = db.Column(db.Float, default=0.0)
    cpu_temp = db.Column(db.Float, default=0.0)
    net_rx_kbps = db.Column(db.Float, default=0.0)
    net_tx_kbps = db.Column(db.Float, default=0.0)
    uptime_seconds = db.Column(db.Integer, default=0)
    process_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, nullable=False, index=True)


class NodeLog(db.Model, SerializerMixin):
    """节点上报的运行日志（用于远程排障）。"""

    __tablename__ = "node_log"

    BASE_FIELDS = ("id", "node_id", "level", "module", "message", "created_at")
    DATETIME_FIELDS = ("created_at",)

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    level = db.Column(db.String(16), default="info", index=True)
    module = db.Column(db.String(64), default="")
    message = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, index=True)
