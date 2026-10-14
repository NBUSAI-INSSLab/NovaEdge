"""告警中心接口：规则配置 + 记录处理。"""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from ..extensions import db
from ..models import (ALERT_ACKED, ALERT_ACTIVE, ALERT_CLEARED,
                      OPERATORS, SEVERITIES, AlertRecord, AlertRule, Node,
                      to_ts, utcnow)
from ..services import events
from ..utils.jwt_helper import current_user, login_required, operator_required
from ..utils.response import (CODE_NOT_FOUND, fail, get_page_args, ok,
                              paginated, parse_float, parse_int, truthy)

bp = Blueprint("alerts", __name__)


@bp.get("/dicts")
@login_required
def dicts():
    return ok({
        "severities": [{"value": k, "label": v} for k, v in SEVERITIES.items()],
        "operators": [{"value": k, "label": v} for k, v in OPERATORS.items()],
    })


# --------------------------------------------------------------------------- #
# 规则
# --------------------------------------------------------------------------- #
@bp.get("/rules")
@login_required
def list_rules():
    page, page_size = get_page_args(50)
    query = AlertRule.query
    if request.args.get("enabled") is not None:
        query = query.filter(AlertRule.enabled == truthy(request.args["enabled"], True))
    if request.args.get("severity"):
        query = query.filter(AlertRule.severity == request.args["severity"])
    total = query.count()
    rows = query.order_by(AlertRule.enabled.desc(), AlertRule.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    node_map = {n.id: n.name for n in Node.query.all()}
    items = [r.to_dict({"node_name": node_map.get(r.node_id, "全部节点") if r.node_id else "全部节点"})
             for r in rows]
    return paginated(items, total, page, page_size)


@bp.post("/rules")
@operator_required
def create_rule():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    metric_key = str(payload.get("metric_key", "")).strip()
    if not name or not metric_key:
        return fail("规则名称与监测指标不能为空", 400)
    threshold = parse_float(payload.get("threshold"))
    if payload.get("operator") != "out_of_range" and threshold is None:
        return fail("请填写阈值", 400)
    rule = AlertRule(
        name=name, node_id=parse_int(payload.get("node_id"), 0),
        group_id=parse_int(payload.get("group_id"), 0), metric_key=metric_key,
        operator=str(payload.get("operator", "gt")),
        threshold=threshold, threshold2=parse_float(payload.get("threshold2")),
        duration_sec=parse_int(payload.get("duration_sec"), 0),
        severity=str(payload.get("severity", "warning")),
        silence_sec=parse_int(payload.get("silence_sec"), 300),
        enabled=truthy(payload.get("enabled"), True),
        notify_channels=payload.get("notify_channels") or ["console"],
        description=str(payload.get("description", "")),
    )
    db.session.add(rule)
    db.session.commit()
    return ok(rule.to_dict(), "告警规则已创建")


@bp.put("/rules/<int:rule_id>")
@operator_required
def update_rule(rule_id: int):
    rule = AlertRule.query.get(rule_id)
    if rule is None:
        return fail("规则不存在", CODE_NOT_FOUND, 404)
    payload = request.get_json(silent=True) or {}
    for field in ("name", "metric_key", "operator", "severity", "description"):
        if field in payload:
            setattr(rule, field, str(payload[field]))
    for field in ("threshold", "threshold2"):
        if field in payload:
            setattr(rule, field, parse_float(payload[field]))
    for field in ("node_id", "group_id", "duration_sec", "silence_sec"):
        if field in payload:
            setattr(rule, field, parse_int(payload[field], 0))
    if "enabled" in payload:
        rule.enabled = truthy(payload["enabled"], True)
    if "notify_channels" in payload:
        rule.notify_channels = payload["notify_channels"] or []
    db.session.commit()
    return ok(rule.to_dict(), "规则已更新")


@bp.delete("/rules/<int:rule_id>")
@operator_required
def delete_rule(rule_id: int):
    rule = AlertRule.query.get(rule_id)
    if rule is None:
        return fail("规则不存在", CODE_NOT_FOUND, 404)
    db.session.delete(rule)
    db.session.commit()
    return ok(message="规则已删除")


# --------------------------------------------------------------------------- #
# 记录
# --------------------------------------------------------------------------- #
@bp.get("/records")
@login_required
def list_records():
    page, page_size = get_page_args(20)
    query = AlertRecord.query
    if request.args.get("status"):
        query = query.filter(AlertRecord.status == request.args["status"])
    if request.args.get("severity"):
        query = query.filter(AlertRecord.severity == request.args["severity"])
    if request.args.get("node_id"):
        query = query.filter(AlertRecord.node_id == parse_int(request.args["node_id"]))
    if request.args.get("hours"):
        hours = parse_int(request.args["hours"], 24)
        query = query.filter(AlertRecord.started_at >= utcnow() - timedelta(hours=hours))
    total = query.count()
    rows = query.order_by(AlertRecord.started_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    node_map = {n.id: n for n in Node.query.filter(
        Node.id.in_({r.node_id for r in rows} or {0})).all()}
    items = []
    for row in rows:
        node = node_map.get(row.node_id)
        items.append(row.to_dict({
            "node_name": node.name if node else "未知节点",
            "node_uid": node.node_uid if node else "",
            "started_at_ts": to_ts(row.started_at),
        }))
    return paginated(items, total, page, page_size)


@bp.post("/records/<int:record_id>/ack")
@operator_required
def ack_record(record_id: int):
    record = AlertRecord.query.get(record_id)
    if record is None:
        return fail("告警记录不存在", CODE_NOT_FOUND, 404)
    record.status = ALERT_ACKED
    record.acked_at = utcnow()
    record.acked_by = current_user().real_name or current_user().username
    db.session.commit()
    events.publish("alert", {"action": "acked", "alert": record.to_dict()})
    return ok(record.to_dict(), "告警已确认")


@bp.post("/records/<int:record_id>/clear")
@operator_required
def clear_record(record_id: int):
    record = AlertRecord.query.get(record_id)
    if record is None:
        return fail("告警记录不存在", CODE_NOT_FOUND, 404)
    record.status = ALERT_CLEARED
    record.cleared_at = utcnow()
    db.session.commit()
    events.publish("alert", {"action": "cleared", "alert": record.to_dict()})
    return ok(record.to_dict(), "告警已手动恢复")


@bp.post("/records/batch-ack")
@operator_required
def batch_ack():
    payload = request.get_json(silent=True) or {}
    ids = [parse_int(i, 0) for i in (payload.get("ids") or [])]
    ids = [i for i in ids if i]
    if not ids:
        return fail("请选择要确认的告警", 400)
    now = utcnow()
    operator_name = current_user().real_name or current_user().username
    count = (AlertRecord.query.filter(AlertRecord.id.in_(ids))
             .update({"status": ALERT_ACKED, "acked_at": now, "acked_by": operator_name},
                     synchronize_session=False))
    db.session.commit()
    return ok({"count": count}, f"已确认 {count} 条告警")


@bp.get("/summary")
@login_required
def summary():
    """告警概览，用于看板卡片与顶部红点。"""
    active = AlertRecord.query.filter_by(status=ALERT_ACTIVE)
    by_severity = dict(db.session.query(AlertRecord.severity, db.func.count(AlertRecord.id))
                       .filter(AlertRecord.status == ALERT_ACTIVE)
                       .group_by(AlertRecord.severity).all())
    recent = AlertRecord.query.order_by(AlertRecord.started_at.desc()).limit(5).all()
    node_map = {n.id: n.name for n in Node.query.all()}
    return ok({
        "active_total": active.count(),
        "by_severity": {k: int(by_severity.get(k, 0)) for k in SEVERITIES},
        "today_total": AlertRecord.query.filter(
            AlertRecord.started_at >= utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        ).count(),
        "recent": [r.to_dict({"node_name": node_map.get(r.node_id, "未知节点")}) for r in recent],
    })
