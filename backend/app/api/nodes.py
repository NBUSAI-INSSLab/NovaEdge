"""节点管理接口（Web 控制台侧）。"""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, current_app, request
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import (NODE_TYPES, Node, NodeCredential, NodeGroup,
                      NodeHeartbeat, NodeLog, STATUS_DISABLED, STATUS_LABELS,
                      STATUS_OFFLINE, STATUS_ONLINE, Telemetry, utcnow)
from ..utils.jwt_helper import current_user, login_required, operator_required
from ..utils.response import (CODE_CONFLICT, CODE_NOT_FOUND, fail,
                              get_page_args, ok, paginated, parse_int, truthy)
from ..services import events, telemetry_service

bp = Blueprint("nodes", __name__)


# --------------------------------------------------------------------------- #
# 字典与分组
# --------------------------------------------------------------------------- #
@bp.get("/specs")
@login_required
def specs():
    """节点类型、状态等枚举字典，供前端下拉框使用。"""
    return ok({
        "node_types": [{"value": k, "label": v} for k, v in NODE_TYPES.items()],
        "statuses": [{"value": k, "label": v} for k, v in STATUS_LABELS.items()],
        "report_intervals": [10, 30, 60, 300, 600, 1800, 3600],
    })


@bp.get("/groups")
@login_required
def list_groups():
    groups = NodeGroup.query.order_by(NodeGroup.sort_order, NodeGroup.id).all()
    counts = dict(db.session.query(Node.group_id, func.count(Node.id))
                  .group_by(Node.group_id).all())
    return ok([g.to_dict({"node_count": counts.get(g.id, 0)}) for g in groups])


@bp.post("/groups")
@operator_required
def create_group():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    if not name:
        return fail("分组名称不能为空", 400)
    group = NodeGroup(
        name=name,
        code=str(payload.get("code", "")).strip(),
        parent_id=parse_int(payload.get("parent_id"), 0),
        description=str(payload.get("description", "")),
        sort_order=parse_int(payload.get("sort_order"), 0),
    )
    db.session.add(group)
    db.session.commit()
    return ok(group.to_dict(), "分组创建成功")


@bp.put("/groups/<int:group_id>")
@operator_required
def update_group(group_id: int):
    group = NodeGroup.query.get(group_id)
    if group is None:
        return fail("分组不存在", CODE_NOT_FOUND, 404)
    payload = request.get_json(silent=True) or {}
    for field in ("name", "code", "description"):
        if field in payload:
            setattr(group, field, str(payload[field]))
    if "parent_id" in payload:
        group.parent_id = parse_int(payload["parent_id"], 0)
    if "sort_order" in payload:
        group.sort_order = parse_int(payload["sort_order"], 0)
    db.session.commit()
    return ok(group.to_dict(), "分组已更新")


@bp.delete("/groups/<int:group_id>")
@operator_required
def delete_group(group_id: int):
    group = NodeGroup.query.get(group_id)
    if group is None:
        return fail("分组不存在", CODE_NOT_FOUND, 404)
    if Node.query.filter_by(group_id=group_id).count():
        return fail("该分组下仍有节点，无法删除", CODE_CONFLICT)
    db.session.delete(group)
    db.session.commit()
    return ok(message="分组已删除")


# --------------------------------------------------------------------------- #
# 节点 CRUD
# --------------------------------------------------------------------------- #
@bp.get("")
@login_required
def list_nodes():
    page, page_size = get_page_args()
    query = Node.query
    keyword = request.args.get("keyword", "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(Node.name.like(like), Node.node_uid.like(like),
                                 Node.location.like(like), Node.ip_address.like(like)))
    if request.args.get("status"):
        query = query.filter(Node.status == request.args["status"])
    if request.args.get("node_type"):
        query = query.filter(Node.node_type == request.args["node_type"])
    if request.args.get("group_id"):
        query = query.filter(Node.group_id == parse_int(request.args["group_id"], 0))

    total = query.count()
    rows = (query.order_by(Node.status.asc(), Node.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    groups = {g.id: g.name for g in NodeGroup.query.all()}
    items = [n.to_dict({"group_name": groups.get(n.group_id, "未分组")}) for n in rows]
    return paginated(items, total, page, page_size)


@bp.post("")
@operator_required
def create_node():
    """新建节点并签发设备凭证。

    返回的 ``secret`` 仅在此处明文出现一次，节点 Agent 需妥善保存。
    """
    payload = request.get_json(silent=True) or {}
    node_uid = str(payload.get("node_uid", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not node_uid or not name:
        return fail("节点编码与名称不能为空", 400)
    if Node.query.filter_by(node_uid=node_uid).first():
        return fail(f"节点编码 {node_uid} 已存在", CODE_CONFLICT)

    node = Node(
        node_uid=node_uid,
        name=name,
        node_type=str(payload.get("node_type", "generic")),
        model=str(payload.get("model", "")),
        serial_no=str(payload.get("serial_no", "")),
        group_id=parse_int(payload.get("group_id"), 0),
        ip_address=str(payload.get("ip_address", "")),
        mac_address=str(payload.get("mac_address", "")),
        location=str(payload.get("location", "")),
        os_version=str(payload.get("os_version", "")),
        agent_version=str(payload.get("agent_version", "")),
        capabilities=payload.get("capabilities") or {},
        report_interval=parse_int(payload.get("report_interval"),
                                  current_app.config["DEFAULT_REPORT_INTERVAL"]),
        remark=str(payload.get("remark", "")),
        status=STATUS_OFFLINE,
        enabled=truthy(payload.get("enabled"), True),
    )
    db.session.add(node)
    db.session.flush()

    access_key = NodeCredential.new_access_key(node_uid)
    secret = NodeCredential.new_secret()
    credential = NodeCredential(
        node_id=node.id,
        access_key=access_key,
        secret_hash=generate_password_hash(secret),
        mqtt_username=access_key,
        mqtt_password=secret,
        token_type="device",
        is_active=True,
    )
    db.session.add(credential)
    db.session.commit()

    return ok({
        "node": node.to_dict(),
        "credential": {
            "access_key": access_key,
            "secret": secret,
            "mqtt_client_id": access_key,
            "http_header": {"X-Node-Key": access_key, "X-Node-Secret": secret},
        },
        "tips": "secret 仅显示一次，请立即写入节点 Agent 配置",
    }, "节点创建成功")


@bp.get("/<int:node_id>")
@login_required
def node_detail(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    group = NodeGroup.query.get(node.group_id) if node.group_id else None
    credentials = (NodeCredential.query.filter_by(node_id=node.id, is_active=True).all())
    return ok(node.to_dict({
        "group_name": group.name if group else "未分组",
        "credentials": [{"access_key": c.access_key, "token_type": c.token_type,
                         "last_used_at": c.created_at.isoformat() if c.created_at else None}
                        for c in credentials],
        "latest_metrics": telemetry_service.latest_values(node.id),
    }))


@bp.put("/<int:node_id>")
@operator_required
def update_node(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    payload = request.get_json(silent=True) or {}
    text_fields = ("name", "node_type", "model", "serial_no", "ip_address", "mac_address",
                   "location", "os_version", "firmware_version", "remark")
    for field in text_fields:
        if field in payload:
            setattr(node, field, str(payload[field]))
    if "group_id" in payload:
        node.group_id = parse_int(payload["group_id"], 0)
    if "report_interval" in payload:
        node.report_interval = max(parse_int(payload["report_interval"], 60), 5)
    if "capabilities" in payload:
        node.capabilities = payload["capabilities"] or {}
    if "enabled" in payload:
        node.enabled = truthy(payload["enabled"], True)
        node.status = STATUS_OFFLINE if not node.enabled else node.status
    if "longitude" in payload:
        node.longitude = payload["longitude"] or None
    if "latitude" in payload:
        node.latitude = payload["latitude"] or None
    db.session.commit()
    events.publish("node", {"action": "updated", "node": node.to_dict()})
    return ok(node.to_dict(), "节点已更新")


@bp.delete("/<int:node_id>")
@operator_required
def delete_node(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    db.session.delete(node)
    db.session.commit()
    events.publish("node", {"action": "deleted", "node_id": node_id})
    return ok(message="节点已删除")


@bp.post("/<int:node_id>/reset-credential")
@operator_required
def reset_credential(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    NodeCredential.query.filter_by(node_id=node.id).update({"is_active": False})
    access_key = NodeCredential.new_access_key(node.node_uid)
    secret = NodeCredential.new_secret()
    db.session.add(NodeCredential(
        node_id=node.id, access_key=access_key,
        secret_hash=generate_password_hash(secret),
        mqtt_username=access_key, mqtt_password=secret, is_active=True,
    ))
    db.session.commit()
    return ok({"access_key": access_key, "secret": secret},
              "凭证已重置，请更新节点配置")


@bp.post("/<int:node_id>/toggle")
@operator_required
def toggle_node(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    node.enabled = not node.enabled
    node.status = STATUS_OFFLINE if not node.enabled else node.status
    db.session.commit()
    return ok(node.to_dict(), "节点已停用" if not node.enabled else "节点已启用")


# --------------------------------------------------------------------------- #
# 节点数据视图
# --------------------------------------------------------------------------- #
@bp.get("/latest-all")
@login_required
def nodes_latest_all():
    """全部节点的最新值快照，单次请求返回，避免前端并发风暴。

    监控页需要每个节点的最新指标。若逐节点请求（N 个并发），在开发服务器上
    大量连接同时建立/中断会拖慢后续请求；改为一次批量查询，请求数从 N 降为 1。
    """
    nodes = Node.query.order_by(Node.id).all()
    data = {}
    for node in nodes:
        data[node.id] = {
            "node_id": node.id,
            "status": node.status,
            "status_label": node.status_label,
            "last_seen_at": node.last_seen_at.isoformat() + "Z" if node.last_seen_at else None,
            "resource": {
                "cpu_percent": node.cpu_percent, "mem_percent": node.mem_percent,
                "disk_percent": node.disk_percent, "cpu_temp": node.cpu_temp,
                "uptime_seconds": node.uptime_seconds,
            },
            "metrics": telemetry_service.latest_values(node.id),
        }
    return ok(data)


@bp.get("/<int:node_id>/latest")
@login_required
def node_latest(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    return ok({
        "node_id": node.id,
        "status": node.status,
        "status_label": node.status_label,
        "last_seen_at": node.last_seen_at.isoformat() + "Z" if node.last_seen_at else None,
        "resource": {
            "cpu_percent": node.cpu_percent, "mem_percent": node.mem_percent,
            "disk_percent": node.disk_percent, "cpu_temp": node.cpu_temp,
            "uptime_seconds": node.uptime_seconds,
        },
        "metrics": telemetry_service.latest_values(node.id),
    })


@bp.get("/<int:node_id>/telemetry")
@login_required
def node_telemetry(node_id: int):
    node = Node.query.get(node_id)
    if node is None:
        return fail("节点不存在", CODE_NOT_FOUND, 404)
    metric_key = request.args.get("metric", "").strip()
    hours = parse_int(request.args.get("hours"), 6)
    points = parse_int(request.args.get("points"), 400)
    if not metric_key:
        keys = [m["metric_key"] for m in telemetry_service.latest_values(node.id)][:6]
        return ok(telemetry_service.series_for_node(node.id, keys, hours, points),
                  "未指定指标，返回主要指标曲线")
    return ok({metric_key: telemetry_service.history(
        node.id, metric_key, None, None, points)}, "查询成功")


@bp.get("/<int:node_id>/heartbeats")
@login_required
def node_heartbeats(node_id: int):
    hours = parse_int(request.args.get("hours"), 1)
    limit = parse_int(request.args.get("limit"), 300)
    start = utcnow() - timedelta(hours=hours)
    rows = (NodeHeartbeat.query.filter(NodeHeartbeat.node_id == node_id,
                                       NodeHeartbeat.created_at >= start)
            .order_by(NodeHeartbeat.created_at.desc()).limit(limit).all())
    rows.reverse()
    return ok([r.to_dict() for r in rows])


@bp.get("/<int:node_id>/logs")
@login_required
def node_logs(node_id: int):
    page, page_size = get_page_args(50)
    query = NodeLog.query.filter_by(node_id=node_id).order_by(NodeLog.created_at.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return paginated([r.to_dict() for r in rows], total, page, page_size)


@bp.get("/<int:node_id>/statistics")
@login_required
def node_statistics(node_id: int):
    """节点数据资产统计：遥测点数、媒体数量与体积。"""
    from ..models import MediaFile
    total_points = db.session.query(func.count(Telemetry.id)).filter_by(node_id=node_id).scalar() or 0
    media_count = db.session.query(func.count(MediaFile.id)).filter_by(
        node_id=node_id, status="ready").scalar() or 0
    image_count = db.session.query(func.count(MediaFile.id)).filter_by(
        node_id=node_id, status="ready", file_type="image").scalar() or 0
    video_count = db.session.query(func.count(MediaFile.id)).filter_by(
        node_id=node_id, status="ready", file_type="video").scalar() or 0
    storage_bytes = db.session.query(func.coalesce(func.sum(MediaFile.file_size), 0)).filter_by(
        node_id=node_id, status="ready").scalar() or 0
    metric_count = db.session.query(func.count(func.distinct(Telemetry.metric_key))).filter_by(
        node_id=node_id).scalar() or 0
    return ok({
        "total_points": int(total_points), "metric_count": int(metric_count),
        "media_count": int(media_count), "image_count": int(image_count),
        "video_count": int(video_count), "storage_bytes": int(storage_bytes),
    })
