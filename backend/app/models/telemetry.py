"""传感器数据的物模型与三张时序表。

分层存储策略（兼顾 SQLite 测试与 MySQL 生产）
------------------------------------------------
1. ``metric_def``        —— 物模型定义（指标字典），等价 ThingsBoard 的 ``ts_kv_dictionary``
2. ``telemetry``         —— 全量时序明细，索引 ``(node_id, metric_key, ts)``
3. ``telemetry_latest``  —— 每节点每指标最新值快照，唯一键 ``(node_id, metric_key)``，看板直读
4. ``telemetry_hourly``  —— 小时级聚合（平均/最大/最小/样本数），长周期曲线无需扫全表

> 生产规模更大时，``telemetry`` 可平滑迁移到 TDengine / InfluxDB，
> 平台侧仅需改写 ``services/telemetry_service.py`` 中的写入与查询实现。
"""

from __future__ import annotations

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin

DATA_TYPES = {
    "float": "浮点数",
    "int": "整数",
    "bool": "布尔量",
    "string": "字符串",
    "enum": "枚举",
    "json": "结构体",
}

METRIC_CATEGORIES = {
    "env": "环境量",
    "power": "电气量",
    "motion": "运动量",
    "vision": "视觉量",
    "system": "系统量",
    "custom": "自定义",
}


class MetricDef(db.Model, TimestampMixin, SerializerMixin):
    """物模型字段定义：屏蔽底层传感器差异，平台内统一口径。"""

    __tablename__ = "metric_def"

    BASE_FIELDS = ("id", "metric_key", "name", "data_type", "unit", "category",
                   "min_value", "max_value", "precision", "enum_options",
                   "applicable_type", "is_system", "description", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    metric_key = db.Column(db.String(64), unique=True, nullable=False, index=True,
                           comment="指标编码，如 temperature")
    name = db.Column(db.String(96), nullable=False, comment="中文名称，如 空气温度")
    data_type = db.Column(db.String(16), default="float", nullable=False)
    unit = db.Column(db.String(24), default="", comment="单位，如 ℃ / %RH / lux")
    category = db.Column(db.String(24), default="custom", index=True)
    min_value = db.Column(db.Float, nullable=True, comment="量程下限（用于校验与图表 Y 轴）")
    max_value = db.Column(db.Float, nullable=True)
    precision = db.Column(db.Integer, default=2, comment="保留小数位")
    enum_options = db.Column(db.JSON, default=list, comment="枚举可选值")
    applicable_type = db.Column(db.String(32), default="", comment="适用节点类型，空=通用")
    is_system = db.Column(db.Boolean, default=False, comment="系统内置指标")
    description = db.Column(db.String(255), default="")

    @property
    def data_type_label(self) -> str:
        return DATA_TYPES.get(self.data_type, self.data_type)

    @property
    def category_label(self) -> str:
        return METRIC_CATEGORIES.get(self.category, self.category)

    def to_dict(self, extra: dict | None = None) -> dict:
        return super().to_dict({
            "data_type_label": self.data_type_label,
            "category_label": self.category_label,
            **(extra or {}),
        })


class Telemetry(db.Model, SerializerMixin):
    """遥测明细。value_num 用于数值型（便于聚合），value_str 兜底字符串/枚举。"""

    __tablename__ = "telemetry"
    __table_args__ = (
        db.Index("ix_telemetry_node_metric_ts", "node_id", "metric_key", "ts"),
        db.Index("ix_telemetry_ts", "ts"),
    )

    BASE_FIELDS = ("id", "node_id", "metric_key", "value_num", "value_str", "ts", "quality", "created_at")
    DATETIME_FIELDS = ("created_at",)

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"), nullable=False)
    metric_key = db.Column(db.String(64), nullable=False, index=True)
    value_num = db.Column(db.Float, nullable=True)
    value_str = db.Column(db.String(255), default="")
    ts = db.Column(db.BigInteger, nullable=False, comment="数据产生的毫秒时间戳")
    quality = db.Column(db.Integer, default=1, comment="数据质量位：1 正常 / 0 可疑")
    created_at = db.Column(db.DateTime, nullable=False)


class TelemetryLatest(db.Model):
    """最新值快照表，看板与节点详情直读，避免扫描明细表。"""

    __tablename__ = "telemetry_latest"

    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    metric_key = db.Column(db.String(64), primary_key=True)
    value_num = db.Column(db.Float, nullable=True)
    value_str = db.Column(db.String(255), default="")
    ts = db.Column(db.BigInteger, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, index=True)


class TelemetryHourly(db.Model):
    """小时级降采样，长周期趋势查询走这张表。"""

    __tablename__ = "telemetry_hourly"
    __table_args__ = (
        db.UniqueConstraint("node_id", "metric_key", "bucket_ts", name="uq_hourly_node_metric_bucket"),
    )

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"), nullable=False)
    metric_key = db.Column(db.String(64), nullable=False)
    bucket_ts = db.Column(db.BigInteger, nullable=False, comment="整点毫秒时间戳")
    avg_value = db.Column(db.Float, default=0.0)
    min_value = db.Column(db.Float, default=0.0)
    max_value = db.Column(db.Float, default=0.0)
    sample_count = db.Column(db.Integer, default=0)
