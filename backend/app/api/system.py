"""系统信息与运维接口。"""

from __future__ import annotations

import platform
import sys
import time
from datetime import timedelta
from pathlib import Path

from flask import Blueprint, current_app, request
from sqlalchemy import func, text

from ..extensions import db
from ..models import (AlertRecord, Command, MediaFile, Node, NodeHeartbeat,
                      SysConfig, Telemetry, to_ts, utcnow)
from ..services import storage, telemetry_service
from ..utils.jwt_helper import login_required, operator_required
from ..utils.response import ok, parse_int

bp = Blueprint("system", __name__)

_START_TS = time.time()

DEFAULT_CONFIGS = [
    ("node.heartbeat_timeout", {"value": 180}, "node", "节点离线判定时长（秒）"),
    ("node.default_report_interval", {"value": 60}, "node", "默认数据上报周期（秒）"),
    ("storage.upload_chunk_size", {"value": 2097152}, "storage", "图片分片大小（字节）"),
    ("storage.video_chunk_size", {"value": 8388608}, "storage", "视频分片大小（字节）"),
    ("storage.retention_days", {"value": 90}, "storage", "遥测数据保留天数"),
    ("media.retention_days", {"value": 180}, "storage", "媒体文件保留天数"),
    ("alert.default_silence", {"value": 300}, "alert", "告警默认静默期（秒）"),
]


@bp.get("/health")
def health():
    """健康检查（供反向代理 / 容器探针使用，无需登录）。"""
    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # pragma: no cover
        database = f"error: {exc}"
    return ok({"status": "ok" if database == "ok" else "degraded",
               "database": database, "uptime_seconds": int(time.time() - _START_TS)})


@bp.get("/info")
@login_required
def info():
    cfg = current_app.config
    storage_root = storage.storage_root()
    try:
        usage = sum(f.stat().st_size for f in storage_root.rglob("*") if f.is_file())
    except Exception:  # pragma: no cover
        usage = 0

    return ok({
        "app": {
            "name": cfg["APP_NAME"],
            "version": "1.0.0",
            "api_prefix": "/api/v1",
            "uptime_seconds": int(time.time() - _START_TS),
            "server_time": to_ts(utcnow()),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": f"{platform.system()} {platform.release()}",
            "flask": __import__("flask").__version__,
        },
        "database": {
            "type": cfg["DB_TYPE"],
            "uri_masked": _mask_uri(cfg["SQLALCHEMY_DATABASE_URI"]),
            "tables": len(db.metadata.tables),
            "dialect": db.engine.dialect.name,
        },
        "storage": {
            "root": str(storage_root),
            "mode": "local",
            "usage_bytes": usage,
            "chunk_size": cfg["CHUNK_SIZE"],
            "large_chunk_size": cfg["LARGE_CHUNK_SIZE"],
        },
        "mqtt": {
            "enabled": cfg["MQTT_ENABLED"],
            "host": cfg["MQTT_HOST"],
            "port": cfg["MQTT_PORT"],
            "topic_prefix": cfg["MQTT_TOPIC_PREFIX"],
        },
        "counts": {
            "nodes": Node.query.count(),
            "metrics": Telemetry.query.with_entities(Telemetry.metric_key).distinct().count(),
            "telemetry": Telemetry.query.count(),
            "media": MediaFile.query.filter(MediaFile.status != "deleted").count(),
            "alerts": AlertRecord.query.count(),
            "commands": Command.query.count(),
        },
    })


def _mask_uri(uri: str) -> str:
    if "@" not in uri or "://" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" in credentials:
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:******@{host}"
    return f"{scheme}://******@{host}"


@bp.get("/configs")
@login_required
def list_configs():
    """读取平台配置；首次访问自动写入默认值。"""
    existing = {c.cfg_key: c for c in SysConfig.query.all()}
    created = False
    for key, value, category, description in DEFAULT_CONFIGS:
        if key not in existing:
            row = SysConfig(cfg_key=key, cfg_value=value, category=category,
                            description=description)
            db.session.add(row)
            existing[key] = row
            created = True
    if created:
        db.session.commit()
    groups: dict[str, list] = {}
    for row in SysConfig.query.order_by(SysConfig.category, SysConfig.id).all():
        groups.setdefault(row.category, []).append(row.to_dict())
    return ok({"groups": groups,
               "items": [c.to_dict() for c in SysConfig.query.order_by(SysConfig.id).all()]})


@bp.put("/configs/<key>")
@operator_required
def update_config(key: str):
    row = SysConfig.query.filter_by(cfg_key=key).first()
    if row is None:
        return ok(message="配置项不存在，已忽略")
    payload = request.get_json(silent=True) or {}
    if "value" in payload:
        row.cfg_value = payload["value"]
    if "description" in payload:
        row.description = str(payload["description"])
    db.session.commit()
    return ok(row.to_dict(), "配置已更新")


@bp.post("/maintenance/rollup")
@operator_required
def manual_rollup():
    """手动触发小时级降采样（生产环境建议由定时任务每小时调用）。"""
    buckets = parse_int((request.get_json(silent=True) or {}).get("hours"), 1)
    total = 0
    current = utcnow().replace(minute=0, second=0, microsecond=0)
    for offset in range(1, min(max(buckets, 1), 72) + 1):
        total += telemetry_service.rollup_hour(current - timedelta(hours=offset))
    return ok({"rolled_buckets": total}, "小时聚合完成")


@bp.post("/maintenance/cleanup")
@operator_required
def cleanup():
    """数据生命周期清理：删除超期的遥测明细与心跳记录。

    仅清理**时序明细**，不删除节点、媒体文件或告警历史，避免误删业务数据。
    """
    payload = request.get_json(silent=True) or {}
    days = max(parse_int(payload.get("retention_days"), 90), 1)
    media_days = max(parse_int(payload.get("media_retention_days"), 0), 0)
    cutoff = utcnow() - timedelta(days=days)
    cutoff_ts = to_ts(cutoff)

    points = Telemetry.query.filter(Telemetry.ts < cutoff_ts).delete(synchronize_session=False)
    heartbeats = NodeHeartbeat.query.filter(NodeHeartbeat.created_at < cutoff).delete(
        synchronize_session=False)
    logs_deleted = 0
    try:
        from ..models import NodeLog
        logs_deleted = NodeLog.query.filter(NodeLog.created_at < cutoff).delete(
            synchronize_session=False)
    except Exception:  # pragma: no cover
        pass
    media_deleted = 0
    if media_days:
        media_cutoff = utcnow() - timedelta(days=media_days)
        stale = MediaFile.query.filter(MediaFile.created_at < media_cutoff,
                                       MediaFile.status == "ready").all()
        for item in stale:
            storage.delete_media_files(item.storage_path, item.thumb_path)
            item.status = "deleted"
            media_deleted += 1
    db.session.commit()
    return ok({"telemetry_deleted": points, "heartbeat_deleted": heartbeats,
               "log_deleted": logs_deleted, "media_deleted": media_deleted,
               "retention_days": days}, "数据清理完成")


@bp.get("/storage-usage")
@login_required
def storage_usage():
    """按类型统计存储占用，用于容量预警。"""
    rows = (db.session.query(MediaFile.file_type, func.count(MediaFile.id),
                             func.coalesce(func.sum(MediaFile.file_size), 0))
            .filter(MediaFile.status != "deleted").group_by(MediaFile.file_type).all())
    labels = {"image": "图片", "video": "视频", "other": "其他"}
    return ok([{"file_type": key, "label": labels.get(key, key), "count": int(count),
                "bytes": int(size)} for key, count, size in rows])
