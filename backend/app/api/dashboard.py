"""总览看板接口：一次请求聚合首页所需全部数据，降低前端请求数。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request
from sqlalchemy import func

from ..extensions import db
from ..models import (ALERT_ACTIVE, NODE_TYPES, STATUS_LABELS, STATUS_OFFLINE,
                      STATUS_ONLINE, AlertRecord, Command, MediaFile, MetricDef,
                      Node, NodeGroup, NodeHeartbeat, Telemetry, human_size,
                      to_ts, utcnow)
from ..utils.jwt_helper import login_required
from ..utils.response import ok, parse_int
from ..services import telemetry_service

bp = Blueprint("dashboard", __name__)


def _hour_buckets(hours: int = 24) -> list[datetime]:
    current = utcnow().replace(minute=0, second=0, microsecond=0)
    return [current - timedelta(hours=offset) for offset in range(hours - 1, -1, -1)]


@bp.get("/overview")
@login_required
def overview():
    """首页总览：节点、数据、媒体、告警四类核心指标 + 趋势。"""
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ts = to_ts(today_start)
    week_start = today_start - timedelta(days=6)

    total_nodes = Node.query.count()
    online_nodes = Node.query.filter_by(status=STATUS_ONLINE).count()
    offline_nodes = Node.query.filter_by(status=STATUS_OFFLINE).count()

    total_points = db.session.query(func.count(Telemetry.id)).scalar() or 0
    today_points = db.session.query(func.count(Telemetry.id)).filter(
        Telemetry.ts >= today_ts).scalar() or 0

    media_total = MediaFile.query.filter(MediaFile.status != "deleted").count()
    media_today = MediaFile.query.filter(MediaFile.status != "deleted",
                                         MediaFile.created_at >= today_start).count()
    image_total = MediaFile.query.filter(MediaFile.status != "deleted",
                                         MediaFile.file_type == "image").count()
    video_total = MediaFile.query.filter(MediaFile.status != "deleted",
                                         MediaFile.file_type == "video").count()
    storage_bytes = db.session.query(func.coalesce(func.sum(MediaFile.file_size), 0)).filter(
        MediaFile.status != "deleted").scalar() or 0

    active_alerts = AlertRecord.query.filter_by(status=ALERT_ACTIVE).count()
    today_alerts = AlertRecord.query.filter(AlertRecord.started_at >= today_start).count()

    # 资源均值（取最近一次心跳）
    latest_ids = (db.session.query(func.max(NodeHeartbeat.id))
                  .group_by(NodeHeartbeat.node_id).scalar_subquery())
    latest_hb = NodeHeartbeat.query.filter(NodeHeartbeat.id.in_(latest_ids)).all() \
        if total_nodes else []
    avg_cpu = round(sum(r.cpu_percent for r in latest_hb) / len(latest_hb), 1) if latest_hb else 0
    avg_mem = round(sum(r.mem_percent for r in latest_hb) / len(latest_hb), 1) if latest_hb else 0
    avg_temp = round(sum(r.cpu_temp for r in latest_hb) / len(latest_hb), 1) if latest_hb else 0
    total_up = round(sum(r.net_tx_kbps for r in latest_hb), 1)
    total_down = round(sum(r.net_rx_kbps for r in latest_hb), 1)

    return ok({
        "nodes": {
            "total": total_nodes, "online": online_nodes, "offline": offline_nodes,
            "disabled": Node.query.filter_by(status="disabled").count(),
            "online_rate": round(online_nodes / total_nodes * 100, 1) if total_nodes else 0.0,
            "groups": NodeGroup.query.count(),
        },
        "data": {
            "total_points": int(total_points), "today_points": int(today_points),
            "metric_defs": MetricDef.query.count(),
        },
        "media": {
            "total": media_total, "today": media_today, "images": image_total,
            "videos": video_total, "storage_bytes": int(storage_bytes),
            "storage_human": human_size(int(storage_bytes)),
        },
        "alerts": {"active": active_alerts, "today": today_alerts},
        "commands": {
            "pending": Command.query.filter_by(status="pending").count(),
            "sent": Command.query.filter_by(status="sent").count(),
        },
        "resource": {"avg_cpu": avg_cpu, "avg_mem": avg_mem, "avg_temp": avg_temp,
                     "net_up_kbps": total_up, "net_down_kbps": total_down},
        "server_time": to_ts(utcnow()),
    })


@bp.get("/node-distribution")
@login_required
def node_distribution():
    """节点状态 / 类型 / 分组分布，供环形图与柱状图。"""
    status_rows = dict(db.session.query(Node.status, func.count(Node.id))
                       .group_by(Node.status).all())
    type_rows = dict(db.session.query(Node.node_type, func.count(Node.id))
                     .group_by(Node.node_type).all())
    group_rows = (db.session.query(NodeGroup.name, func.count(Node.id))
                  .outerjoin(Node, Node.group_id == NodeGroup.id)
                  .group_by(NodeGroup.id).all())
    ungrouped = Node.query.filter_by(group_id=0).count()

    return ok({
        "by_status": [{"name": STATUS_LABELS.get(k, k), "value": int(v), "key": k}
                      for k, v in status_rows.items()],
        "by_type": [{"name": NODE_TYPES.get(k, k), "value": int(v), "key": k}
                    for k, v in type_rows.items()],
        "by_group": ([{"name": name, "value": int(count)} for name, count in group_rows]
                     + ([{"name": "未分组", "value": ungrouped}] if ungrouped else [])),
    })


@bp.get("/trend")
@login_required
def trend():
    """近 N 小时的数据上报量与媒体上传量趋势（按整点分桶）。"""
    hours = min(max(parse_int(request.args.get("hours"), 24), 6), 168)
    buckets = _hour_buckets(hours)
    start_ts = to_ts(buckets[0])
    hour_ms = 3600 * 1000

    counters = {to_ts(bucket): 0 for bucket in buckets}
    for (ts,) in db.session.query(Telemetry.ts).filter(Telemetry.ts >= start_ts).all():
        key = (ts // hour_ms) * hour_ms
        if key in counters:
            counters[key] += 1

    media_counters = {to_ts(bucket): 0 for bucket in buckets}
    for (created,) in (db.session.query(MediaFile.created_at)
                       .filter(MediaFile.created_at >= buckets[0],
                               MediaFile.status != "deleted").all()):
        key = to_ts(created.replace(minute=0, second=0, microsecond=0))
        if key in media_counters:
            media_counters[key] += 1

    return ok({
        "labels": [bucket.strftime("%m-%d %H:00") for bucket in buckets],
        "points": [counters[to_ts(bucket)] for bucket in buckets],
        "media": [media_counters[to_ts(bucket)] for bucket in buckets],
    })


@bp.get("/top-nodes")
@login_required
def top_nodes():
    """数据量 / 媒体量 Top 节点排行。"""
    limit = min(parse_int(request.args.get("limit"), 8), 20)
    point_rows = (db.session.query(Telemetry.node_id, func.count(Telemetry.id).label("cnt"))
                  .group_by(Telemetry.node_id).order_by(func.count(Telemetry.id).desc())
                  .limit(limit).all())
    media_rows = (db.session.query(MediaFile.node_id, func.count(MediaFile.id).label("cnt"))
                  .filter(MediaFile.status != "deleted")
                  .group_by(MediaFile.node_id).order_by(func.count(MediaFile.id).desc())
                  .limit(limit).all())
    node_map = {n.id: n for n in Node.query.all()}

    def pack(rows):
        result = []
        for node_id, count in rows:
            node = node_map.get(node_id)
            if node is None:
                continue
            result.append({"node_id": node_id, "node_name": node.name,
                           "node_uid": node.node_uid, "value": int(count),
                           "status": node.status})
        return result

    return ok({"by_points": pack(point_rows), "by_media": pack(media_rows)})


@bp.get("/recent")
@login_required
def recent():
    """最近事件流：告警 + 媒体 + 指令，用于首页动态列表。"""
    limit = min(parse_int(request.args.get("limit"), 8), 30)
    node_map = {n.id: n for n in Node.query.all()}

    alerts = AlertRecord.query.order_by(AlertRecord.started_at.desc()).limit(limit).all()
    medias = (MediaFile.query.filter(MediaFile.status != "deleted")
              .order_by(MediaFile.created_at.desc()).limit(limit).all())
    commands = Command.query.order_by(Command.issued_at.desc()).limit(limit).all()

    return ok({
        "alerts": [a.to_dict({"node_name": node_map[a.node_id].name
                              if a.node_id in node_map else "未知节点"}) for a in alerts],
        "media": [m.to_dict({"node_name": node_map[m.node_id].name
                             if m.node_id in node_map else "未知节点"}) for m in medias],
        "commands": [c.to_dict({"node_name": node_map[c.node_id].name
                                if c.node_id in node_map else "未知节点"}) for c in commands],
    })


@bp.get("/metric-ranking")
@login_required
def metric_ranking():
    """指标采样量排行，反映当前平台的数据结构构成。"""
    limit = min(parse_int(request.args.get("limit"), 10), 30)
    rows = (db.session.query(Telemetry.metric_key, func.count(Telemetry.id).label("cnt"))
            .group_by(Telemetry.metric_key).order_by(func.count(Telemetry.id).desc())
            .limit(limit).all())
    defs = {m.metric_key: m for m in MetricDef.query.all()}
    return ok([{
        "metric_key": key, "name": defs[key].name if key in defs else key,
        "unit": defs[key].unit if key in defs else "", "value": int(count),
    } for key, count in rows])


@bp.get("/offline-nodes")
@login_required
def offline_nodes():
    """离线节点清单（用于运维巡检提醒）。"""
    from ..models import Node as NodeModel
    rows = (NodeModel.query.filter(NodeModel.status == STATUS_OFFLINE)
            .order_by(NodeModel.last_seen_at.asc().nullsfirst()).limit(20).all())
    return ok([n.to_dict({"last_seen_ts": to_ts(n.last_seen_at)}) for n in rows])
