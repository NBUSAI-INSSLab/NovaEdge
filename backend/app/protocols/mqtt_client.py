"""MQTT 接入与下发（对接 EMQX / Mosquitto 等 MQTT Broker）。

主题规划
--------
上行（节点 -> 平台）::

    edge/{node_uid}/telemetry     传感器遥测（QoS 1，支持批量）
    edge/{node_uid}/heartbeat     资源心跳（QoS 0，允许丢弃）
    edge/{node_uid}/event         事件通知（图片/视频上传完成、异常）
    edge/{node_uid}/cmd/ack       指令执行回执（QoS 1）
    edge/{node_uid}/log           运行日志

下行（平台 -> 节点）::

    edge/{node_uid}/cmd           指令下发（QoS 1）
    edge/{node_uid}/config        配置推送

载荷统一为 JSON，字段与 HTTP 接入层完全一致，
因此同一套业务处理逻辑（``ingest_telemetry`` / 心跳更新 / 指令回执）可复用。

连接失败处理
------------
MQTT 为**可选增强通道**：Broker 不可用时仅打印告警，平台自动退化为
「节点 HTTP 上报 + HTTP 轮询取指令」，核心业务不中断。
"""

from __future__ import annotations

import json
import logging
import threading

from ..extensions import db
from ..models import (CMD_SENT, CMD_SUCCESS, Command, Node, NodeCredential,
                      NodeHeartbeat, NodeLog, STATUS_ONLINE, to_ts, utcnow)
from ..services import events, telemetry_service

logger = logging.getLogger("novaedge.mqtt")

try:  # paho-mqtt 为可选依赖
    import paho.mqtt.client as mqtt
    from paho.mqtt.client import CallbackAPIVersion
    PAHO_AVAILABLE = True
except ImportError:  # pragma: no cover
    mqtt = None
    CallbackAPIVersion = None
    PAHO_AVAILABLE = False


class _Base:
    def __init__(self, app=None):
        self.app = app
        self.client = None
        self._connected = False
        self._lock = threading.Lock()

    def init_app(self, app):
        self.app = app

    @property
    def connected(self) -> bool:
        return self._connected

    def _build_client(self, client_id: str, username: str = "", password: str = ""):
        if not PAHO_AVAILABLE:
            logger.warning("未安装 paho-mqtt，MQTT 通道不可用")
            return None
        try:
            client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id)
        except TypeError:  # pragma: no cover - 兼容 paho 1.x
            client = mqtt.Client(client_id=client_id)
        if username:
            client.username_pw_set(username, password)
        cfg = self.app.config
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.connect_async(cfg["MQTT_HOST"], cfg["MQTT_PORT"],
                             keepalive=cfg["MQTT_KEEPALIVE"])
        return client


class MQTTIngest(_Base):
    """订阅节点上行主题，把消息转换为平台内部写入操作。"""

    def start(self):
        cfg = self.app.config
        if not cfg.get("MQTT_ENABLED"):
            logger.info("MQTT 接入未启用（MQTT_ENABLED=false），使用 HTTP 接入通道")
            return False
        client = self._build_client("novaedge-platform",
                                    cfg.get("MQTT_USERNAME", ""),
                                    cfg.get("MQTT_PASSWORD", ""))
        if client is None:
            return False
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self.client = client
        try:
            client.loop_start()
            logger.info("MQTT 接入已启动 -> %s:%s", cfg["MQTT_HOST"], cfg["MQTT_PORT"])
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("MQTT 连接失败，降级为 HTTP 接入：%s", exc)
            return False

    def stop(self):
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:  # pragma: no cover
                pass
        self._connected = False

    # ---------------- 回调 ----------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        prefix = self.app.config["MQTT_TOPIC_PREFIX"]
        topics = [
            (f"{prefix}/+/telemetry", 1),
            (f"{prefix}/+/heartbeat", 0),
            (f"{prefix}/+/event", 1),
            (f"{prefix}/+/cmd/ack", 1),
            (f"{prefix}/+/log", 0),
        ]
        for topic, qos in topics:
            client.subscribe(topic, qos=qos)
        self._connected = True
        logger.info("MQTT 已连接，订阅 %s 下 %s 个主题", prefix, len(topics))
        events.publish("system", {"action": "mqtt_connected"})

    def _on_disconnect(self, client, userdata, flags=None, reason_code=None, properties=None):
        self._connected = False
        logger.warning("MQTT 连接断开，将自动重连")

    def _on_message(self, client, userdata, message):
        try:
            parts = message.topic.split("/")
            if len(parts) < 3:
                return
            node_uid, kind = parts[1], "/".join(parts[2:])
            payload = json.loads(message.payload.decode("utf-8") or "{}")
        except Exception as exc:
            logger.warning("MQTT 消息解析失败: %s", exc)
            return

        with self.app.app_context():
            try:
                node = Node.query.filter_by(node_uid=node_uid).first()
                if node is None or not node.enabled:
                    logger.info("忽略未注册节点的 MQTT 消息: %s", node_uid)
                    return
                handler = {
                    "telemetry": self._handle_telemetry,
                    "heartbeat": self._handle_heartbeat,
                    "event": self._handle_event,
                    "cmd/ack": self._handle_ack,
                    "log": self._handle_log,
                }.get(kind)
                if handler:
                    handler(node, payload)
            except Exception as exc:  # pragma: no cover
                db.session.rollback()
                logger.exception("MQTT 消息处理异常: %s", exc)

    # ---------------- 处理器 ----------------
    def _handle_telemetry(self, node: Node, payload: dict):
        samples = payload.get("samples")
        if not isinstance(samples, list):
            metrics = payload.get("metrics")
            if isinstance(metrics, dict):
                samples = [{"metric": k, "value": v, "ts": payload.get("ts")}
                           for k, v in metrics.items()]
            else:
                samples = []
        if not samples:
            return
        node.touch()
        node.status = STATUS_ONLINE
        telemetry_service.ingest_telemetry(node, samples, source="mqtt")

    def _handle_heartbeat(self, node: Node, payload: dict):
        now = utcnow()

        def num(key):
            try:
                return float(payload.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        db.session.add(NodeHeartbeat(
            node_id=node.id, cpu_percent=num("cpu_percent"), mem_percent=num("mem_percent"),
            disk_percent=num("disk_percent"), cpu_temp=num("cpu_temp"),
            net_rx_kbps=num("net_rx_kbps"), net_tx_kbps=num("net_tx_kbps"),
            uptime_seconds=int(payload.get("uptime_seconds") or 0),
            process_count=int(payload.get("process_count") or 0), created_at=now,
        ))
        node.status = STATUS_ONLINE
        node.last_seen_at = now
        node.cpu_percent = num("cpu_percent")
        node.mem_percent = num("mem_percent")
        node.disk_percent = num("disk_percent")
        node.cpu_temp = num("cpu_temp")
        node.uptime_seconds = int(payload.get("uptime_seconds") or 0)
        if payload.get("agent_version"):
            node.agent_version = str(payload["agent_version"])
        db.session.commit()
        events.publish("node", {"action": "heartbeat", "node": node.to_dict()})

    def _handle_event(self, node: Node, payload: dict):
        node.touch()
        db.session.commit()
        events.publish("node", {"action": "event", "node": node.to_dict(),
                                "payload": payload})

    def _handle_ack(self, node: Node, payload: dict):
        cmd_id = str(payload.get("cmd_id", ""))
        cmd = Command.query.filter_by(cmd_id=cmd_id, node_id=node.id).first()
        if cmd is None:
            return
        cmd.status = CMD_SUCCESS if payload.get("success", True) else "failed"
        cmd.result = payload.get("result") or {}
        cmd.ack_at = utcnow()
        db.session.commit()
        events.publish("command", {"action": "acked", "command": cmd.to_dict(),
                                   "node_name": node.name})

    def _handle_log(self, node: Node, payload: dict):
        now = utcnow()
        items = payload.get("logs") if isinstance(payload.get("logs"), list) else [payload]
        for item in items:
            if not isinstance(item, dict) or not item.get("message"):
                continue
            db.session.add(NodeLog(node_id=node.id,
                                   level=str(item.get("level", "info"))[:16],
                                   module=str(item.get("module", ""))[:64],
                                   message=str(item.get("message"))[:2000],
                                   created_at=now))
        db.session.commit()


class MQTTPublisher(_Base):
    """平台向节点下发消息（指令 / 配置）。"""

    def start(self):
        cfg = self.app.config
        if not cfg.get("MQTT_ENABLED"):
            return False
        client = self._build_client("novaedge-publisher",
                                    cfg.get("MQTT_USERNAME", ""),
                                    cfg.get("MQTT_PASSWORD", ""))
        if client is None:
            return False
        client.on_connect = lambda c, u, f, rc, p=None: setattr(self, "_connected", True)
        client.on_disconnect = lambda *a, **k: setattr(self, "_connected", False)
        self.client = client
        try:
            client.loop_start()
            return True
        except Exception:  # pragma: no cover
            return False

    def publish(self, topic: str, payload: dict, qos: int = 1) -> bool:
        if self.client is None:
            return False
        try:
            info = self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=qos)
            return info.rc == 0
        except Exception:  # pragma: no cover
            return False

    def publish_command(self, node_uid: str, payload: dict) -> bool:
        prefix = self.app.config["MQTT_TOPIC_PREFIX"]
        return self.publish(f"{prefix}/{node_uid}/cmd", payload, qos=1)

    def publish_config(self, node_uid: str, payload: dict) -> bool:
        prefix = self.app.config["MQTT_TOPIC_PREFIX"]
        return self.publish(f"{prefix}/{node_uid}/config", payload, qos=1)


mqtt_ingest = MQTTIngest()
mqtt_publisher = MQTTPublisher()


def verify_device_credentials(client_id: str, username: str, password: str) -> bool:
    """供 EMQX HTTP 认证插件回调：校验设备接入密钥。

    在 EMQX 的 ``emqx_auth_http`` 中配置：
    POST http://平台地址/api/v1/device/mqtt-auth
    返回 ``{"result": "allow"}`` 或 ``{"result": "deny"}``。
    """
    from werkzeug.security import check_password_hash
    cred = NodeCredential.query.filter_by(access_key=username, is_active=True).first()
    if cred is None:
        return False
    if cred.mqtt_password and cred.mqtt_password == password:
        return True
    return check_password_hash(cred.secret_hash, password)
