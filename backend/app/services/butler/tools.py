"""智能管家工具集：平台数据查询与白名单配置操作。

每个工具 = (名称, 描述, JSON Schema 参数, 处理函数)。
处理函数在 Flask 应用上下文内执行，返回 JSON 可序列化字典。
写操作（update_alert_rule / create_alert_rule / send_node_command）
仅对 operator / admin 角色开放，并写入审计日志。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func

from ...extensions import db
from ...models import (ALERT_ACTIVE, CMD_PENDING, AuditLog, AlertRecord, AlertRule,
                       Command, MediaFile, MetricDef, Node, NodeGroup, SysConfig,
                       TelemetryLatest, utcnow)

WRITE_TOOLS = {"update_alert_rule", "create_alert_rule", "send_node_command"}


# --------------------------------------------------------------------------
# 读取类工具
# --------------------------------------------------------------------------

def tool_query_nodes(args: dict) -> dict:
    state = (args.get("state") or "all").lower()
    q = Node.query
    if state == "online":
        q = q.filter(Node.status == "online")
    elif state == "offline":
        q = q.filter(Node.status == "offline")
    nodes = q.order_by(Node.id).all()
    group_names = {g.id: g.name for g in NodeGroup.query.all()}
    return {
        "total": len(nodes),
        "nodes": [{
            "id": n.id, "name": n.name, "node_uid": n.node_uid,
            "type": n.node_type, "status": n.status,
            "group": group_names.get(n.group_id),
            "last_seen_at": n.last_seen_at.isoformat(sep=" ") if n.last_seen_at else None,
            "firmware": n.firmware_version or "",
        } for n in nodes],
    }


def tool_query_node_detail(args: dict) -> dict:
    node_id = int(args.get("node_id") or 0)
    node = db.session.get(Node, node_id)
    if not node:
        return {"error": f"节点 {node_id} 不存在"}
    latest = TelemetryLatest.query.filter_by(node_id=node_id).all()
    group = db.session.get(NodeGroup, node.group_id) if node.group_id else None
    return {
        "id": node.id, "name": node.name, "status": node.status,
        "group": group.name if group else None,
        "last_seen_at": node.last_seen_at.isoformat(sep=" ") if node.last_seen_at else None,
        "latest_metrics": {m.metric_key: {
            "value": m.value_num if m.value_num is not None else m.value_str,
            "time": m.updated_at.isoformat(sep=" ")} for m in latest},
    }


def tool_query_telemetry_stats(args: dict) -> dict:
    hours = int(args.get("hours") or 24)
    node_id = args.get("node_id")
    since = utcnow() - timedelta(hours=hours)

    latest_q = TelemetryLatest.query
    if node_id:
        latest_q = latest_q.filter(TelemetryLatest.node_id == int(node_id))
    latest = latest_q.all()

    stats: dict[str, list] = {}
    for m in latest:
        if m.value_num is None:
            continue
        stats.setdefault(m.metric_key, []).append(float(m.value_num))

    result = []
    for key, values in sorted(stats.items()):
        result.append({
            "metric_key": key,
            "node_count": len(values),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "avg": round(sum(values) / len(values), 3),
        })

    # 指标中文说明
    defs = {d.metric_key: d.name for d in MetricDef.query.all()}
    for row in result:
        row["metric_name"] = defs.get(row["metric_key"], row["metric_key"])

    # 节点维度：最近 N 小时遥测条数 TOP
    from ...models import Telemetry
    top = (db.session.query(Node.name, func.count(Telemetry.id).label("cnt"))
           .join(Telemetry, Telemetry.node_id == Node.id)
           .filter(Telemetry.created_at >= since)
           .group_by(Node.name).order_by(func.count(Telemetry.id).desc())
           .limit(5).all())
    return {
        "hours": hours,
        "metrics": result,
        "top_nodes_by_points": [{"node": name, "points": cnt} for name, cnt in top],
    }


def tool_query_alerts(args: dict) -> dict:
    hours = int(args.get("hours") or 24)
    status = args.get("status")
    severity = args.get("severity")
    since = utcnow() - timedelta(hours=hours)

    base = AlertRecord.query.filter(AlertRecord.started_at >= since)
    q = base
    if status:
        q = q.filter(AlertRecord.status == status)
    if severity:
        q = q.filter(AlertRecord.severity == severity)
    records = q.order_by(AlertRecord.started_at.desc()).limit(30).all()

    total = q.count()
    by_sev: dict[str, int] = {}
    for sev, cnt in (db.session.query(AlertRecord.severity, func.count())
                     .filter(AlertRecord.started_at >= since)
                     .group_by(AlertRecord.severity).all()):
        by_sev[sev] = cnt
    node_names = {n.id: n.name for n in Node.query.all()}
    return {
        "hours": hours,
        "total": total,
        "by_severity": by_sev,
        "records": [{
            "id": r.id, "node": node_names.get(r.node_id, f"#{r.node_id}"),
            "metric": r.metric_key, "severity": r.severity, "status": r.status,
            "title": r.title, "trigger_value": r.trigger_value,
            "started_at": r.started_at.isoformat(sep=" "),
        } for r in records],
    }


def tool_query_alert_rules(args: dict) -> dict:
    rules = AlertRule.query.order_by(AlertRule.id).all()
    return {"total": len(rules), "rules": [{
        "id": r.id, "name": r.name, "metric_key": r.metric_key,
        "operator": r.operator, "threshold": r.threshold, "threshold2": r.threshold2,
        "duration_sec": r.duration_sec, "severity": r.severity,
        "enabled": r.enabled, "node_id": r.node_id, "trigger_count": r.trigger_count,
    } for r in rules]}


def tool_query_media_stats(args: dict) -> dict:
    hours = int(args.get("hours") or 24)
    since = utcnow() - timedelta(hours=hours)
    by_type = dict(db.session.query(MediaFile.file_type, func.count())
                   .group_by(MediaFile.file_type).all())
    size_by_type = dict(db.session.query(MediaFile.file_type, func.coalesce(func.sum(MediaFile.file_size), 0))
                        .group_by(MediaFile.file_type).all())
    recent_cnt = MediaFile.query.filter(MediaFile.created_at >= since).count()
    return {
        "hours": hours,
        "count_by_type": by_type,
        "size_bytes_by_type": {k: int(v) for k, v in size_by_type.items()},
        "recent_count": recent_cnt,
        "total_count": sum(by_type.values()),
    }


def tool_query_commands(args: dict) -> dict:
    hours = int(args.get("hours") or 24)
    since = utcnow() - timedelta(hours=hours)
    by_status = dict(db.session.query(Command.status, func.count())
                     .filter(Command.created_at >= since)
                     .group_by(Command.status).all())
    pending = Command.query.filter_by(status=CMD_PENDING).order_by(Command.id.desc()).limit(10).all()
    return {
        "hours": hours,
        "count_by_status": by_status,
        "pending": [{"id": c.id, "node_id": c.node_id, "command": c.command,
                     "issued_by": c.issued_by,
                     "created_at": c.created_at.isoformat(sep=" ")} for c in pending],
    }


def tool_query_system(args: dict) -> dict:
    from ...models import Telemetry
    nodes_total = Node.query.count()
    nodes_online = Node.query.filter(Node.status == "online").count()
    storage_row = db.session.query(func.coalesce(func.sum(MediaFile.file_size), 0)).scalar()
    tel_row = db.session.query(func.count(Telemetry.id)).scalar()
    cfg = SysConfig.query.filter_by(cfg_key="butler_llm").first()
    return {
        "nodes_total": nodes_total,
        "nodes_online": nodes_online,
        "nodes_offline": nodes_total - nodes_online,
        "telemetry_points": tel_row,
        "media_storage_bytes": int(storage_row or 0),
        "llm_configured": bool(cfg and (cfg.cfg_value or {}).get("api_key")),
        "server_time": datetime.now().isoformat(sep=" ", timespec="seconds"),
    }


def tool_query_groups(args: dict) -> dict:
    groups = NodeGroup.query.order_by(NodeGroup.id).all()
    counts = dict(db.session.query(Node.group_id, func.count()).group_by(Node.group_id).all())
    return {"groups": [{"id": g.id, "name": g.name, "node_count": counts.get(g.id, 0)}
                       for g in groups]}


# --------------------------------------------------------------------------
# 写操作类工具（operator / admin 专属，写审计日志）
# --------------------------------------------------------------------------

def _audit(user, action: str, target_type: str, target_id: str, detail) -> None:
    db.session.add(AuditLog(
        user_id=getattr(user, "id", 0), username=getattr(user, "username", "system"),
        action=action, target_type=target_type, target_id=str(target_id),
        detail=detail if isinstance(detail, dict) else {"info": str(detail)},
        ip="", created_at=utcnow(),
    ))


def tool_update_alert_rule(args: dict, user=None) -> dict:
    rule_id = int(args.get("rule_id") or 0)
    rule = db.session.get(AlertRule, rule_id)
    if not rule:
        return {"error": f"告警规则 {rule_id} 不存在"}
    changed = []
    for field in ("threshold", "threshold2", "duration_sec", "silence_sec", "severity"):
        if field in args and args[field] is not None:
            old = getattr(rule, field)
            new = args[field]
            if field in ("threshold", "threshold2"):
                new = float(new)
            elif field in ("duration_sec", "silence_sec"):
                new = int(new)
            setattr(rule, field, new)
            changed.append(f"{field}: {old} → {new}")
    if "enabled" in args and args["enabled"] is not None:
        rule.enabled = bool(args["enabled"])
        changed.append(f"enabled: → {rule.enabled}")
    if not changed:
        return {"error": "未提供任何要修改的字段"}
    db.session.commit()
    _audit(user, "butler.update_alert_rule", "alert_rule", rule_id,
           {"rule": rule.name, "changed": changed})
    return {"ok": True, "rule_id": rule_id, "rule_name": rule.name, "changed": changed}


def tool_create_alert_rule(args: dict, user=None) -> dict:
    name = (args.get("name") or "").strip()
    metric_key = (args.get("metric_key") or "").strip()
    operator = (args.get("operator") or "gt").strip()
    if not name or not metric_key:
        return {"error": "缺少 name 或 metric_key"}
    if operator not in ("gt", "gte", "lt", "lte", "between", "outside"):
        return {"error": f"不支持的比较符: {operator}"}
    if "threshold" not in args:
        return {"error": "缺少 threshold"}
    rule = AlertRule(
        name=name, metric_key=metric_key, operator=operator,
        threshold=float(args["threshold"]),
        threshold2=float(args["threshold2"]) if args.get("threshold2") is not None else None,
        duration_sec=int(args.get("duration_sec") or 0),
        severity=args.get("severity") or "warning",
        node_id=int(args.get("node_id") or 0),
        enabled=True,
    )
    db.session.add(rule)
    db.session.commit()
    _audit(user, "butler.create_alert_rule", "alert_rule", rule.id,
           {"name": name, "metric_key": metric_key, "operator": operator,
            "threshold": args["threshold"]})
    return {"ok": True, "rule_id": rule.id, "rule_name": rule.name}


def tool_send_node_command(args: dict, user=None) -> dict:
    import uuid

    from ...models import CMD_PENDING, CMD_SENT, COMMAND_CATALOG

    node_id = int(args.get("node_id") or 0)
    node = db.session.get(Node, node_id)
    if not node:
        return {"error": f"节点 {node_id} 不存在"}
    command = (args.get("command") or "").strip()
    if not command:
        return {"error": "缺少 command"}
    known = set(COMMAND_CATALOG.keys())
    if command not in known:
        return {"error": f"未知指令 {command}，可用：{sorted(known)}"}
    params = args.get("params") or {}
    now = utcnow()
    cmd = Command(
        cmd_id=f"cmd_{uuid.uuid4().hex[:20]}", node_id=node.id, command=command,
        params=params, status=CMD_PENDING, issued_by=f"butler({getattr(user, 'username', 'system')})",
        timeout_sec=int(args.get("timeout_sec") or 30), issued_at=now, created_at=now,
    )
    db.session.add(cmd)
    db.session.flush()

    # MQTT 通道：在线即尝试实时下发，失败时 HTTP 轮询兜底
    pushed = False
    try:
        from ...protocols.mqtt_client import mqtt_publisher
        pushed = mqtt_publisher.publish_command(node.node_uid, {
            "cmd_id": cmd.cmd_id, "command": cmd.command, "params": cmd.params or {},
            "timeout_sec": cmd.timeout_sec, "issued_at": cmd.issued_at.isoformat() + "Z",
        })
    except Exception:
        pushed = False
    cmd.channel = "mqtt" if pushed else "http-poll"
    if pushed:
        cmd.status = CMD_SENT
        cmd.sent_at = now
    db.session.commit()
    _audit(user, "butler.send_command", "node", node_id,
           {"node": node.name, "command": command, "params": params, "channel": cmd.channel})
    return {"ok": True, "command_id": cmd.id, "node": node.name,
            "command": command, "channel": cmd.channel, "status": cmd.status}


# --------------------------------------------------------------------------
# 工具注册表
# --------------------------------------------------------------------------

def all_tools() -> list[dict]:
    """返回工具描述列表（OpenAI function calling 格式）。"""
    return [
        {"name": "query_nodes", "description": "查询节点列表与在线状态",
         "params": {"type": "object", "properties": {
             "state": {"type": "string", "enum": ["all", "online", "offline"], "description": "按状态筛选"}}}},
        {"name": "query_node_detail", "description": "查询单个节点详情与最新指标值",
         "params": {"type": "object", "properties": {"node_id": {"type": "integer"}}, "required": ["node_id"]}},
        {"name": "query_telemetry_stats", "description": "查询遥测数据统计（各指标最新值的 min/max/avg、数据量 TOP 节点）",
         "params": {"type": "object", "properties": {
             "hours": {"type": "integer", "description": "统计窗口小时数，默认24"},
             "node_id": {"type": "integer", "description": "限定节点，可省略"}}}},
        {"name": "query_alerts", "description": "查询告警记录与分级统计",
         "params": {"type": "object", "properties": {
             "hours": {"type": "integer"},
             "status": {"type": "string", "enum": ["active", "acked", "cleared"]},
             "severity": {"type": "string", "enum": ["critical", "major", "minor", "warning"]}}}},
        {"name": "query_alert_rules", "description": "查询告警规则列表", "params": {"type": "object", "properties": {}}},
        {"name": "query_media_stats", "description": "查询数据资产（图片/视频/文件）统计",
         "params": {"type": "object", "properties": {"hours": {"type": "integer"}}}},
        {"name": "query_commands", "description": "查询下发指令统计与待执行指令",
         "params": {"type": "object", "properties": {"hours": {"type": "integer"}}}},
        {"name": "query_system", "description": "查询系统概况（节点数/在线率/遥测量/存储占用）",
         "params": {"type": "object", "properties": {}}},
        {"name": "query_groups", "description": "查询节点分组", "params": {"type": "object", "properties": {}}},
        {"name": "update_alert_rule", "description": "修改告警规则（阈值/持续时间/严重级别/启停）【配置操作】",
         "params": {"type": "object", "properties": {
             "rule_id": {"type": "integer"},
             "threshold": {"type": "number"}, "threshold2": {"type": "number"},
             "duration_sec": {"type": "integer"}, "silence_sec": {"type": "integer"},
             "severity": {"type": "string", "enum": ["critical", "major", "minor", "warning"]},
             "enabled": {"type": "boolean"}},
             "required": ["rule_id"]}},
        {"name": "create_alert_rule", "description": "新建告警规则【配置操作】",
         "params": {"type": "object", "properties": {
             "name": {"type": "string"}, "metric_key": {"type": "string"},
             "operator": {"type": "string", "enum": ["gt", "gte", "lt", "lte", "between", "outside"]},
             "threshold": {"type": "number"}, "threshold2": {"type": "number"},
             "duration_sec": {"type": "integer"}, "severity": {"type": "string"},
             "node_id": {"type": "integer", "description": "0 表示全部节点"}},
             "required": ["name", "metric_key", "threshold"]}},
        {"name": "send_node_command", "description": "向节点下发控制指令【配置操作】",
         "params": {"type": "object", "properties": {
             "node_id": {"type": "integer"}, "command": {"type": "string"},
             "params": {"type": "object"}, "timeout_sec": {"type": "integer"}},
             "required": ["node_id", "command"]}},
    ]


def dispatch(name: str, args: dict, user=None, allow_write: bool = False) -> dict:
    """按名称执行工具；写操作需 allow_write。"""
    handlers = {
        "query_nodes": tool_query_nodes,
        "query_node_detail": tool_query_node_detail,
        "query_telemetry_stats": tool_query_telemetry_stats,
        "query_alerts": tool_query_alerts,
        "query_alert_rules": tool_query_alert_rules,
        "query_media_stats": tool_query_media_stats,
        "query_commands": tool_query_commands,
        "query_system": tool_query_system,
        "query_groups": tool_query_groups,
    }
    write_handlers = {
        "update_alert_rule": tool_update_alert_rule,
        "create_alert_rule": tool_create_alert_rule,
        "send_node_command": tool_send_node_command,
    }
    if name in WRITE_TOOLS:
        if not allow_write:
            return {"error": "权限不足：配置操作需要操作员或管理员角色"}
        handler = write_handlers.get(name)
    else:
        handler = handlers.get(name)
    if not handler:
        return {"error": f"未知工具: {name}"}
    try:
        return handler(args, user) if name in WRITE_TOOLS else handler(args)
    except Exception as exc:  # 工具异常不应中断会话
        db.session.rollback()
        return {"error": f"工具执行异常: {exc}"}
