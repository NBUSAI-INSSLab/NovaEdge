"""下行指令接口：下发、查询、超时巡检。

指令通道优先级
--------------
1. MQTT（``edge/{node_uid}/cmd``）—— 实时性好，在线节点首选
2. HTTP 轮询（``/device/commands/pending``）—— MQTT 未启用或节点在内网无出站 MQTT 时兜底

两条通道写的是同一张 ``command`` 表、同一套状态机，
因此上层业务与前端无需关心节点实际走哪条链路。
"""

from __future__ import annotations

import uuid

from flask import Blueprint, request

from ..extensions import db
from ..models import (CMD_PENDING, CMD_SENT, CMD_TIMEOUT, COMMAND_CATALOG,
                      Command, Node, STATUS_ONLINE, utcnow)
from ..services import events
from ..utils.jwt_helper import current_user, login_required, operator_required
from ..utils.response import (CODE_NOT_FOUND, fail, get_page_args, ok,
                              paginated, parse_int)

bp = Blueprint("commands", __name__)


@bp.get("/catalog")
@login_required
def catalog():
    """平台支持的指令字典（供前端渲染指令面板）。"""
    return ok([{"command": key, **value} for key, value in COMMAND_CATALOG.items()])


@bp.get("")
@login_required
def list_commands():
    page, page_size = get_page_args(20)
    query = Command.query
    if request.args.get("node_id"):
        query = query.filter(Command.node_id == parse_int(request.args["node_id"]))
    if request.args.get("status"):
        query = query.filter(Command.status == request.args["status"])
    if request.args.get("command"):
        query = query.filter(Command.command == request.args["command"])
    total = query.count()
    rows = query.order_by(Command.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    node_map = {n.id: n for n in Node.query.filter(
        Node.id.in_({r.node_id for r in rows} or {0})).all()}
    items = []
    for row in rows:
        node = node_map.get(row.node_id)
        items.append(row.to_dict({
            "node_name": node.name if node else "未知节点",
            "node_uid": node.node_uid if node else "",
            "online": bool(node and node.status == STATUS_ONLINE),
        }))
    return paginated(items, total, page, page_size)


@bp.get("/<cmd_id>")
@login_required
def command_detail(cmd_id: str):
    cmd = Command.query.filter_by(cmd_id=cmd_id).first()
    if cmd is None:
        return fail("指令不存在", CODE_NOT_FOUND, 404)
    node = Node.query.get(cmd.node_id)
    return ok(cmd.to_dict({"node_name": node.name if node else "未知节点",
                           "node_uid": node.node_uid if node else ""}))


@bp.post("")
@operator_required
def issue_command():
    """下发指令，支持一次对多个节点批量下发。"""
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip()
    if command not in COMMAND_CATALOG:
        return fail(f"不支持的指令：{command}", 400)

    node_ids = payload.get("node_ids") or []
    if payload.get("node_id"):
        node_ids.append(parse_int(payload["node_id"]))
    node_ids = [nid for nid in {parse_int(i, 0) for i in node_ids} if nid]
    if not node_ids:
        return fail("请选择目标节点", 400)

    params = payload.get("params") or {}
    timeout_sec = parse_int(payload.get("timeout_sec"), 30)
    operator_name = current_user().real_name or current_user().username
    now = utcnow()

    created, skipped = [], []
    dispatched = 0
    for node_id in node_ids:
        node = Node.query.get(node_id)
        if node is None:
            skipped.append({"node_id": node_id, "reason": "节点不存在"})
            continue
        if not node.enabled:
            skipped.append({"node_id": node_id, "reason": "节点已停用"})
            continue

        cmd = Command(
            cmd_id=f"cmd_{uuid.uuid4().hex[:20]}", node_id=node.id, command=command,
            params=params, status=CMD_PENDING, issued_by=operator_name,
            timeout_sec=timeout_sec, issued_at=now, created_at=now,
        )
        db.session.add(cmd)
        db.session.flush()

        # MQTT 通道：在线即尝试实时下发
        pushed = _try_mqtt_push(node, cmd)
        cmd.channel = "mqtt" if pushed else "http-poll"
        if pushed:
            cmd.status = CMD_SENT
            cmd.sent_at = now
            dispatched += 1
        created.append(cmd.to_dict({"node_name": node.name, "node_uid": node.node_uid}))
    db.session.commit()

    for item in created:
        events.publish("command", {"action": "issued", "command": item})
    return ok({"commands": created, "skipped": skipped, "mqtt_pushed": dispatched},
              f"已向 {len(created)} 个节点下发指令")


def _try_mqtt_push(node: Node, cmd: Command) -> bool:
    """尝试通过 MQTT 实时下发；未启用或推送失败时返回 False，由 HTTP 轮询兜底。"""
    try:
        from ..protocols.mqtt_client import mqtt_publisher
        return mqtt_publisher.publish_command(node.node_uid, {
            "cmd_id": cmd.cmd_id, "command": cmd.command, "params": cmd.params or {},
            "timeout_sec": cmd.timeout_sec, "issued_at": cmd.issued_at.isoformat() + "Z",
        })
    except Exception:  # pragma: no cover - MQTT 不可用时静默降级
        return False


@bp.post("/<cmd_id>/cancel")
@operator_required
def cancel_command(cmd_id: str):
    cmd = Command.query.filter_by(cmd_id=cmd_id).first()
    if cmd is None:
        return fail("指令不存在", CODE_NOT_FOUND, 404)
    if cmd.status not in {CMD_PENDING, CMD_SENT}:
        return fail("该指令已结束，无法取消", 400)
    cmd.status = "failed"
    cmd.result = {"cancelled_by": current_user().username}
    cmd.ack_at = utcnow()
    db.session.commit()
    return ok(cmd.to_dict(), "指令已取消")


@bp.post("/scan-timeout")
@operator_required
def scan_timeout():
    """巡检超时未回执的指令并置为 timeout（可由定时任务周期调用）。"""
    count = mark_timeouts()
    return ok({"timeout": count}, f"已标记 {count} 条超时指令")


def mark_timeouts() -> int:
    now = utcnow()
    rows = Command.query.filter(Command.status.in_([CMD_PENDING, CMD_SENT])).all()
    count = 0
    for cmd in rows:
        deadline = cmd.sent_at or cmd.issued_at
        if deadline is None:
            continue
        if (now - deadline).total_seconds() > (cmd.timeout_sec or 30):
            cmd.status = CMD_TIMEOUT
            cmd.ack_at = now
            cmd.result = {"message": "节点未在规定时间内回执"}
            count += 1
    if count:
        db.session.commit()
    return count


@bp.get("/pending/count")
@login_required
def pending_count():
    return ok({
        "pending": Command.query.filter_by(status=CMD_PENDING).count(),
        "sent": Command.query.filter_by(status=CMD_SENT).count(),
    })
