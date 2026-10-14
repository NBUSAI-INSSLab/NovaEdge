"""设备侧接入接口（节点 Agent 调用）。

协议设计
--------
* 认证：``X-Node-Key`` + ``X-Node-Secret`` 请求头（或 ``Authorization: Device key:secret``）
* 遥测：``POST /api/v1/device/telemetry`` —— 支持批量样本，一次请求可上报多个指标
* 心跳：``POST /api/v1/device/heartbeat`` —— 资源画像 + 在线保活
* 指令：MQTT 优先（``edge/{uid}/cmd``），断网或未启用 MQTT 时降级为
  ``GET /api/v1/device/commands/pending`` 轮询，两条链路共用同一份指令表
* 日志：``POST /api/v1/device/logs``
"""

from __future__ import annotations

import logging
import uuid

from flask import Blueprint, current_app, g, request

from ..extensions import db
from ..models import (CMD_SENT, CMD_SUCCESS, Command, Node, NodeHeartbeat,
                      NodeLog, STATUS_ONLINE, to_ts, utcnow)
from ..services import events, telemetry_service
from ..utils.auth import device_auth_required
from ..utils.request_ctx import json_body
from ..utils.response import (CODE_NOT_FOUND, fail, ok, parse_int, truthy)

bp = Blueprint("device", __name__)
logger = logging.getLogger("novaedge.device")

# 心跳中自动落到时序库的资源指标
RESOURCE_METRICS = {
    "cpu_percent": ("CPU 使用率", "%"),
    "mem_percent": ("内存使用率", "%"),
    "disk_percent": ("磁盘使用率", "%"),
    "cpu_temp": ("SoC 温度", "℃"),
    "net_rx_kbps": ("下行速率", "kbps"),
    "net_tx_kbps": ("上行速率", "kbps"),
}


# --------------------------------------------------------------------------- #
# 注册 / 上线
# --------------------------------------------------------------------------- #
@bp.post("/register")
@device_auth_required
def register():
    """节点首次上线：上报自描述信息，平台补全档案并返回运行配置。"""
    node: Node = g.node
    payload = json_body()
    for field in ("model", "serial_no", "os_version", "agent_version",
                  "firmware_version", "mac_address"):
        value = str(payload.get(field, "")).strip()
        if value:
            setattr(node, field, value)
    if payload.get("ip_address"):
        node.ip_address = str(payload["ip_address"])
    elif request.remote_addr:
        node.ip_address = request.remote_addr
    if isinstance(payload.get("capabilities"), dict):
        node.capabilities = payload["capabilities"]
    if payload.get("report_interval"):
        node.report_interval = max(parse_int(payload["report_interval"], 60), 5)

    node.status = STATUS_ONLINE
    node.last_boot_at = utcnow()
    node.touch()
    db.session.commit()

    events.publish("node", {"action": "online", "node": node.to_dict()})
    return ok({
        "node_id": node.id,
        "node_uid": node.node_uid,
        "name": node.name,
        "report_interval": node.report_interval,
        "heartbeat_interval": max(node.report_interval // 2, 15),
        "server_time": to_ts(utcnow()),
        "storage": {"mode": "chunk", "chunk_size": current_app.config["CHUNK_SIZE"],
                    "large_chunk_size": current_app.config["LARGE_CHUNK_SIZE"]},
        "mqtt": {
            "enabled": current_app.config["MQTT_ENABLED"],
            "host": current_app.config["MQTT_HOST"],
            "port": current_app.config["MQTT_PORT"],
            "topic_prefix": current_app.config["MQTT_TOPIC_PREFIX"],
        },
        "message": "注册成功，配置已下发",
    })


# --------------------------------------------------------------------------- #
# 遥测上报
# --------------------------------------------------------------------------- #
def _normalize_samples(payload: dict) -> list[dict]:
    """兼容三种上报格式：samples 数组 / metrics 字典 / 单条 metric+value。"""
    if isinstance(payload.get("samples"), list):
        return [s for s in payload["samples"] if isinstance(s, dict)]
    if isinstance(payload.get("metrics"), dict):
        ts = payload.get("ts")
        return [{"metric": k, "value": v, "ts": ts} for k, v in payload["metrics"].items()]
    if payload.get("metric"):
        return [{"metric": payload["metric"], "value": payload.get("value"),
                 "ts": payload.get("ts"), "unit": payload.get("unit")}]
    return []


@bp.post("/telemetry")
@device_auth_required
def telemetry():
    node: Node = g.node
    payload = json_body()
    samples = _normalize_samples(payload)
    if not samples:
        return fail("未解析到有效遥测数据，请使用 samples / metrics 字段", 400)

    node.touch()
    node.status = STATUS_ONLINE
    result = telemetry_service.ingest_telemetry(node, samples, source="http")

    if result["accepted"]:
        events.publish("node", {"action": "seen", "node": node.to_dict()})
    return ok({"accepted": result["accepted"], "rejected": result["rejected"],
               "server_time": to_ts(utcnow())},
              f"接收 {result['accepted']} 条数据")


# --------------------------------------------------------------------------- #
# 心跳 / 资源画像
# --------------------------------------------------------------------------- #
@bp.post("/heartbeat")
@device_auth_required
def heartbeat():
    node: Node = g.node
    payload = json_body()
    now = utcnow()

    def num(key, default=0.0):
        try:
            return float(payload.get(key, default) or 0)
        except (TypeError, ValueError):
            return default

    record = NodeHeartbeat(
        node_id=node.id,
        cpu_percent=num("cpu_percent"),
        mem_percent=num("mem_percent"),
        disk_percent=num("disk_percent"),
        cpu_temp=num("cpu_temp"),
        net_rx_kbps=num("net_rx_kbps"),
        net_tx_kbps=num("net_tx_kbps"),
        uptime_seconds=parse_int(payload.get("uptime_seconds"), 0),
        process_count=parse_int(payload.get("process_count"), 0),
        created_at=now,
    )
    db.session.add(record)

    node.status = STATUS_ONLINE
    node.last_seen_at = now
    node.cpu_percent = record.cpu_percent
    node.mem_percent = record.mem_percent
    node.disk_percent = record.disk_percent
    node.cpu_temp = record.cpu_temp
    node.uptime_seconds = record.uptime_seconds
    if payload.get("agent_version"):
        node.agent_version = str(payload["agent_version"])
    if payload.get("ip_address"):
        node.ip_address = str(payload["ip_address"])
    if payload.get("os_version"):
        node.os_version = str(payload["os_version"])
    if payload.get("report_interval"):
        node.report_interval = max(parse_int(payload["report_interval"], 60), 5)
    if isinstance(payload.get("capabilities"), dict):
        node.capabilities = payload["capabilities"]
    if truthy(payload.get("cold_boot"), False):
        node.last_boot_at = now
    db.session.commit()

    # 资源指标同样进入时序库，便于绘制节点负载曲线
    samples = [{"metric": key, "value": getattr(record, key),
                "unit": RESOURCE_METRICS[key][1], "name": RESOURCE_METRICS[key][0]}
               for key in RESOURCE_METRICS]
    telemetry_service.ingest_telemetry(node, samples, source="heartbeat",
                                       evaluate_alert=True)

    events.publish("node", {"action": "heartbeat", "node": node.to_dict(),
                            "resource": record.to_dict()})
    return ok({
        "server_time": to_ts(now),
        "report_interval": node.report_interval,
        "pending_commands": Command.query.filter_by(node_id=node.id, status="pending").count(),
    }, "心跳已接收")


# --------------------------------------------------------------------------- #
# 配置下发 / 指令
# --------------------------------------------------------------------------- #
@bp.get("/config")
@device_auth_required
def get_config():
    node: Node = g.node
    return ok({
        "node_uid": node.node_uid,
        "report_interval": node.report_interval,
        "heartbeat_interval": max(node.report_interval // 2, 15),
        "collect": node.capabilities or {},
        "server_time": to_ts(utcnow()),
    })


@bp.get("/commands/pending")
@device_auth_required
def pending_commands():
    """HTTP 轮询方式拉取待执行指令（MQTT 不可用时的降级通道）。"""
    node: Node = g.node
    rows = (Command.query.filter_by(node_id=node.id, status="pending")
            .order_by(Command.issued_at.asc()).limit(10).all())
    now = utcnow()
    payload = []
    for cmd in rows:
        cmd.status = CMD_SENT
        cmd.sent_at = now
        cmd.channel = "http-poll"
        payload.append({"cmd_id": cmd.cmd_id, "command": cmd.command,
                        "params": cmd.params or {}, "timeout_sec": cmd.timeout_sec,
                        "issued_at": cmd.issued_at.isoformat() + "Z"})
    db.session.commit()
    return ok(payload, f"共 {len(payload)} 条待执行指令")


@bp.post("/commands/<cmd_id>/ack")
@device_auth_required
def command_ack(cmd_id: str):
    node: Node = g.node
    payload = json_body()
    cmd = Command.query.filter_by(cmd_id=cmd_id, node_id=node.id).first()
    if cmd is None:
        return fail("指令不存在", CODE_NOT_FOUND, 404)
    success = truthy(payload.get("success"), True)
    cmd.status = CMD_SUCCESS if success else "failed"
    cmd.result = payload.get("result") or {}
    cmd.ack_at = utcnow()
    db.session.commit()
    events.publish("command", {"action": "acked", "command": cmd.to_dict(),
                               "node_name": node.name})
    return ok(cmd.to_dict(), "回执已记录")


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #
@bp.post("/logs")
@device_auth_required
def push_logs():
    node: Node = g.node
    payload = json_body()
    items = payload.get("logs") if isinstance(payload.get("logs"), list) else [payload]
    now = utcnow()
    count = 0
    for item in items:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        db.session.add(NodeLog(
            node_id=node.id,
            level=str(item.get("level", "info")).lower()[:16],
            module=str(item.get("module", ""))[:64],
            message=str(item.get("message"))[:2000],
            created_at=now,
        ))
        count += 1
    db.session.commit()
    events.publish("node", {"action": "log", "node_id": node.id, "node_name": node.name,
                            "count": count, "level": str(payload.get("level", "info"))})
    return ok({"accepted": count}, "日志已接收")


@bp.get("/time")
@device_auth_required
def server_time():
    """节点时间校准。"""
    now = utcnow()
    return ok({"epoch_ms": to_ts(now), "utc": now.isoformat() + "Z"})


# --------------------------------------------------------------------------- #
# EMQX HTTP 认证回调（无需设备凭证，EMQX 主动调用）
# --------------------------------------------------------------------------- #
@bp.post("/mqtt-auth")
def mqtt_auth():
    """供 EMQX ``emqx_auth_http`` 插件调用，校验设备 MQTT 连接口令。

    EMQX 配置（emqx.conf）::

        authentication {
          mechanism = password_based
          backend = http
          method = post
          url = "http://<平台地址>/api/v1/device/mqtt-auth"
          body { clientid = "${clientid}", username = "${username}", password = "${password}" }
        }

    平台返回 ``{"result": "allow"}`` 表示放行，``{"result": "deny"}`` 表示拒绝。
    """
    from ..protocols.mqtt_client import verify_device_credentials
    payload = json_body()
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    client_id = str(payload.get("clientid", ""))
    allowed = verify_device_credentials(client_id, username, password)
    if not allowed:
        logger.warning("MQTT 认证拒绝：clientid=%s username=%s", client_id, username)
    return ok({"result": "allow" if allowed else "deny",
               "is_superuser": False},
              "认证通过" if allowed else "认证失败")


def generate_cmd_id() -> str:
    return f"cmd_{uuid.uuid4().hex[:20]}"
