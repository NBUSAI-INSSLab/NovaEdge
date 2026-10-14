#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NovaEdge 边缘节点采集 Agent（树莓派 / 香橙派 / Jetson 通用）。

职责
----
* **采集**：传感器读数（DS18B20 / DHT22 / ADS1115 / 系统资源）、摄像头抓图与录像
* **处理**：本地聚合打包、按配置降采样、离线缓存
* **上报**：遥测与心跳走 HTTP（可选 MQTT），媒体文件走分片上传
* **执行**：轮询并执行平台下发的下行指令（抓拍、录像、改周期、自检、重启）

用法::

    python agent.py -c config.yaml                 # 正常循环运行
    python agent.py -c config.yaml --once          # 单轮采集后退出（联调自检）
    python agent.py -c config.yaml --no-camera     # 只跑传感器与心跳
    python agent.py -c config.yaml --duration 60   # 运行 60 秒后退出
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collectors import Camera, SensorHub, collect_capabilities  # noqa: E402
from spool import Spool  # noqa: E402
from uploader import Uploader  # noqa: E402

logger = logging.getLogger("agent")

CONFIG_DEFAULT = {
    "node": {"node_uid": "RPI-DEMO-01", "access_key": "", "secret": ""},
    "server": {"base_url": "http://127.0.0.1:5000", "timeout": 30,
               "spool_dir": "spool", "spool_max_batches": 2000},
    "schedule": {"report_interval": 30, "heartbeat_interval": 15,
                 "capture_interval": 120, "record_interval": 0},
    "sensors": {"backends": ["system", "mock"], "mock_metrics": {
        "temperature": {"base": 24.5, "amplitude": 2.0, "noise": 0.3, "unit": "℃"},
        "humidity": {"base": 55.0, "amplitude": 8.0, "noise": 1.5, "unit": "%RH"},
    }},
    "camera": {"backend": "auto", "mock_enabled": True},
    "mqtt": {"enabled": False},
    "logging": {"level": "INFO"},
}


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None) -> dict:
    if not path:
        return CONFIG_DEFAULT
    file_path = Path(path)
    if not file_path.exists():
        logger.warning("配置文件不存在：%s，使用默认配置", path)
        return CONFIG_DEFAULT
    if yaml is None:
        logger.error("未安装 PyYAML，无法读取 YAML 配置（pip install pyyaml）")
        return CONFIG_DEFAULT
    with open(file_path, "r", encoding="utf-8") as fp:
        return deep_merge(CONFIG_DEFAULT, yaml.safe_load(fp) or {})


class EdgeAgent:
    def __init__(self, config: dict, enable_camera: bool = True) -> None:
        self.config = config
        self.node_cfg = config.get("node", {})
        self.server_cfg = config.get("server", {})
        self.schedule = dict(config.get("schedule", {}))
        self.node_uid = self.node_cfg.get("node_uid", "UNKNOWN")
        self.base_url = self.server_cfg.get("base_url", "http://127.0.0.1:5000").rstrip("/")
        self.timeout = int(self.server_cfg.get("timeout", 30))

        self.headers = {
            "X-Node-Key": str(self.node_cfg.get("access_key", "")),
            "X-Node-Secret": str(self.node_cfg.get("secret", "")),
        }
        self.session = requests.Session()
        self.uploader = Uploader(self.base_url, self.headers, self.timeout,
                                 session=self.session)

        base_dir = Path(__file__).resolve().parent
        self.spool = Spool(base_dir / self.server_cfg.get("spool_dir", "spool"),
                           self.server_cfg.get("spool_max_batches", 2000))
        self.capture_dir = base_dir / "captures"
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self.sensors = SensorHub(config.get("sensors", {}))
        self.camera = Camera(config.get("camera", {}), self.node_uid) if enable_camera else None
        self.enable_camera = enable_camera

        self.stop_event = threading.Event()
        self.started_at = time.time()
        self.counters = {"telemetry_sent": 0, "telemetry_failed": 0,
                         "media_sent": 0, "media_failed": 0, "commands_done": 0,
                         "spool_flushed": 0}
        self.last_error = ""
        self._record_until = 0.0
        self._report_interval = int(self.schedule.get("report_interval", 30))

    # ------------------------------------------------------------------ #
    # HTTP 基础
    # ------------------------------------------------------------------ #
    def _post(self, path: str, payload: dict, timeout: int | None = None) -> dict | None:
        try:
            resp = self.session.post(f"{self.base_url}{path}", json=payload,
                                     headers=self.headers,
                                     timeout=timeout or self.timeout)
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            self.last_error = f"{path}: {exc}"
            return None
        if body.get("code") != 0:
            self.last_error = f"{path}: {body.get('message')}"
            return None
        return body.get("data")

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        try:
            resp = self.session.get(f"{self.base_url}{path}", headers=self.headers,
                                    params=params, timeout=self.timeout)
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            self.last_error = f"{path}: {exc}"
            return None
        if body.get("code") != 0:
            self.last_error = f"{path}: {body.get('message')}"
            return None
        return body.get("data")

    # ------------------------------------------------------------------ #
    # 注册 / 心跳
    # ------------------------------------------------------------------ #
    def register(self) -> bool:
        capabilities = collect_capabilities(self.config.get("sensors", {}),
                                            self.camera.backend if self.camera else "none")
        data = self._post("/api/v1/device/register", {
            "model": self.node_cfg.get("model", ""),
            "serial_no": self.node_cfg.get("serial_no", ""),
            "location": self.node_cfg.get("location", ""),
            "agent_version": self.node_cfg.get("agent_version", "1.0.0"),
            "os_version": _os_version(),
            "ip_address": _local_ip(),
            "mac_address": _mac_address(),
            "hostname": socket.gethostname(),
            "report_interval": self._report_interval,
            "capabilities": capabilities,
        })
        if data is None:
            logger.warning("节点注册失败：%s", self.last_error)
            return False
        logger.info("节点注册成功：%s（%s），平台下发上报周期 %ss",
                    data.get("name"), self.node_uid, data.get("report_interval"))
        self._report_interval = int(data.get("report_interval") or self._report_interval)
        return True

    def send_heartbeat(self) -> bool:
        resource = self.sensors.read_system()
        payload = dict(resource)
        payload.update({
            "uptime_seconds": int(time.time() - self.started_at),
            "process_count": _process_count(),
            "agent_version": self.node_cfg.get("agent_version", "1.0.0"),
            "ip_address": _local_ip(),
            "report_interval": self._report_interval,
            "os_version": _os_version(),
            "spool": self.spool.stats(),
        })
        data = self._post("/api/v1/device/heartbeat", payload)
        if data is None:
            return False
        return True

    # ------------------------------------------------------------------ #
    # 遥测上报
    # ------------------------------------------------------------------ #
    def collect_and_report(self) -> bool:
        readings = self.sensors.read()
        if not readings:
            return True
        ts = int(time.time() * 1000)
        samples = []
        for metric, value in readings.items():
            samples.append({"metric": metric, "value": value, "ts": ts,
                            "unit": self.sensors.units.get(metric, "")})
        return self.report_samples(samples)

    def report_samples(self, samples: list[dict]) -> bool:
        data = self._post("/api/v1/device/telemetry", {"samples": samples, "ts": int(time.time() * 1000)})
        if data is None:
            self.counters["telemetry_failed"] += 1
            self.spool.push_batch(samples)
            logger.warning("遥测上报失败，已缓存 %d 条（待补传 %d 批）",
                           len(samples), self.spool.pending_count())
            return False
        self.counters["telemetry_sent"] += len(samples)
        logger.info("遥测上报成功：%d 条 %s", data.get("accepted", 0),
                    {s["metric"]: s["value"] for s in samples[:4]})
        return True

    def flush_spool(self) -> int:
        """补传离线缓存的历史批次。"""
        pending = self.spool.pending_batches()
        if not pending:
            return 0
        logger.info("检测到 %d 批离线缓存，开始补传 ...", len(pending))
        flushed = 0
        for path in pending:
            if self.stop_event.is_set():
                break
            samples = self.spool.read_batch(path)
            if not samples:
                self.spool.remove(path)
                continue
            data = self._post("/api/v1/device/telemetry", {"samples": samples})
            if data is None:
                logger.warning("补传中断，剩余 %d 批等待下一轮", len(pending) - flushed)
                break
            self.spool.remove(path)
            flushed += 1
            self.counters["spool_flushed"] += 1
        if flushed:
            logger.info("离线补传完成：%d 批", flushed)
        return flushed

    # ------------------------------------------------------------------ #
    # 媒体采集与上传
    # ------------------------------------------------------------------ #
    def capture_image(self, reason: str = "scheduled", upload: bool = True,
                      command_id: str = "") -> dict | None:
        if not self.camera or not self.camera.available:
            logger.warning("摄像头不可用，跳过抓拍")
            return None
        path = self.camera.capture_image(self.capture_dir)
        if path is None:
            return None
        logger.info("抓拍完成：%s（%.1f KB）", path.name, path.stat().st_size / 1024)
        if not upload:
            return {"local_path": str(path)}
        result = self.uploader.upload_file(path, file_type="image", source=reason,
                                           captured_at=datetime.now())
        if result is None:
            self.counters["media_failed"] += 1
            logger.warning("图片上传失败，本地保留：%s", path)
            return {"local_path": str(path), "uploaded": False}
        self.counters["media_sent"] += 1
        try:
            path.unlink(missing_ok=True)     # 上传成功后清理本地文件
        except OSError:
            pass
        return {"media_id": result.get("id"), "file_name": result.get("file_name"),
                "uploaded": True, "command_id": command_id}

    def record_video(self, duration: int | None = None, reason: str = "scheduled") -> dict | None:
        if not self.camera or not self.camera.available:
            logger.warning("摄像头不可用，跳过录像")
            return None
        path = self.camera.record_video(self.capture_dir, duration)
        if path is None:
            return None
        logger.info("录像完成：%s（%.2f MB）", path.name, path.stat().st_size / 1048576)
        result = self.uploader.upload_file(path, file_type="video", source=reason,
                                           captured_at=datetime.now(),
                                           extra={"duration_sec": duration})
        if result is None:
            self.counters["media_failed"] += 1
            logger.warning("视频上传失败，本地保留：%s", path)
            return {"local_path": str(path), "uploaded": False}
        self.counters["media_sent"] += 1
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"media_id": result.get("id"), "file_name": result.get("file_name"),
                "duration_sec": result.get("duration_sec"), "uploaded": True}

    def retry_local_media(self) -> None:
        """重试上传历史上传失败的媒体文件。"""
        for path in self.spool.media_pending():
            file_type = "video" if path.suffix.lower() in {".mp4", ".avi", ".mov"} else "image"
            result = self.uploader.upload_file(path, file_type=file_type)
            if result is not None:
                self.counters["media_sent"] += 1
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    # 下行指令
    # ------------------------------------------------------------------ #
    def poll_commands(self) -> int:
        commands = self._get("/api/v1/device/commands/pending")
        if not commands:
            return 0
        for cmd in commands:
            self.execute_command(cmd)
        return len(commands)

    def execute_command(self, cmd: dict) -> dict:
        command = cmd.get("command", "")
        params = cmd.get("params") or {}
        cmd_id = cmd.get("cmd_id", "")
        logger.info("执行指令：%s %s", command, params)
        success, result = True, {}

        if command == "capture_image":
            outcome = self.capture_image(reason="manual", command_id=cmd_id)
            success = bool(outcome and outcome.get("uploaded"))
            result = outcome or {"message": "摄像头不可用"}
        elif command == "start_record":
            default_duration = self.camera.duration if self.camera else 10
            duration = int(params.get("duration") or default_duration)
            outcome = self.record_video(duration=duration, reason="manual")
            success = bool(outcome and outcome.get("uploaded"))
            result = outcome or {"message": "录像失败"}
        elif command == "stop_record":
            if self.camera:
                self.camera.stop_record()
            result = {"message": "已请求停止录像"}
        elif command == "set_interval":
            interval = max(int(params.get("interval") or 30), 5)
            self._report_interval = interval
            self.schedule["report_interval"] = interval
            result = {"message": f"上报周期已设置为 {interval} 秒"}
        elif command == "sync_config":
            data = self._get("/api/v1/device/config")
            if data:
                self._report_interval = int(data.get("report_interval") or self._report_interval)
            result = {"config": data}
        elif command == "self_test":
            result = {
                "camera": self.camera.self_test() if self.camera else {"available": False},
                "sensors": [b.name for b in self.sensors.backends],
                "network": {"server": self.base_url, "reachable": self.send_heartbeat()},
                "spool": self.spool.stats(),
                "uptime_seconds": int(time.time() - self.started_at),
            }
            success = result["network"]["reachable"]
        elif command == "reboot":
            delay = int(params.get("delay") or 5)
            result = {"message": f"{delay} 秒后重启（演示环境不实际执行）",
                      "dry_run": True}
            logger.warning("收到重启指令（演示模式不执行实际重启）")
        else:
            success, result = False, {"message": f"未知指令：{command}"}

        self.counters["commands_done"] += 1
        self._post(f"/api/v1/device/commands/{cmd_id}/ack",
                   {"success": success, "result": result})
        return {"cmd_id": cmd_id, "command": command, "success": success, "result": result}

    # ------------------------------------------------------------------ #
    # 循环线程
    # ------------------------------------------------------------------ #
    def _loop(self, name: str, interval_key: str, action) -> None:
        while not self.stop_event.is_set():
            interval = max(int(self.schedule.get(interval_key, 30)), 2)
            started = time.time()
            try:
                action()
            except Exception as exc:  # pragma: no cover
                logger.exception("[%s] 执行异常：%s", name, exc)
            elapsed = time.time() - started
            self.stop_event.wait(max(interval - elapsed, 1))

    def run(self, duration: int | None = None, once: bool = False) -> int:
        logger.info("=" * 66)
        logger.info("NovaEdge 节点 Agent 启动")
        logger.info("  节点编码 : %s", self.node_uid)
        logger.info("  平台地址 : %s", self.base_url)
        logger.info("  摄像头   : %s", self.camera.backend if self.camera else "已禁用")
        logger.info("  传感器   : %s", [b.name for b in self.sensors.backends])
        logger.info("  上报周期 : %ss  心跳 %ss", self._report_interval,
                    self.schedule.get("heartbeat_interval"))
        logger.info("=" * 66)

        if not self.register():
            logger.warning("注册未成功（平台不可达或凭证错误），仍将尝试继续运行并缓存数据")

        if once:
            self.send_heartbeat()
            self.collect_and_report()
            self.poll_commands()
            logger.info("单轮执行完成，统计：%s", self.counters)
            logger.info("缓存状态：%s", self.spool.stats())
            return 0 if not self.last_error else 1

        workers = [
            threading.Thread(target=self._loop, name="heartbeat",
                             args=("heartbeat", "heartbeat_interval", self.send_heartbeat),
                             daemon=True),
            threading.Thread(target=self._loop, name="telemetry",
                             args=("telemetry", "report_interval", self._sensor_cycle),
                             daemon=True),
            threading.Thread(target=self._loop, name="command",
                             args=("command", "heartbeat_interval", self.poll_commands),
                             daemon=True),
        ]
        if self.schedule.get("capture_interval"):
            workers.append(threading.Thread(
                target=self._loop, name="capture",
                args=("capture", "capture_interval",
                      lambda: self.capture_image(reason="scheduled")), daemon=True))
        if self.schedule.get("record_interval") and self.camera and self.camera.available:
            workers.append(threading.Thread(
                target=self._loop, name="record",
                args=("record", "record_interval",
                      lambda: self.record_video(reason="scheduled")), daemon=True))

        for worker in workers:
            worker.start()

        started = time.time()
        try:
            while not self.stop_event.is_set():
                if duration and time.time() - started >= duration:
                    logger.info("已达到设定运行时长 %s 秒，准备退出", duration)
                    break
                self.flush_spool()
                self.retry_local_media()
                self.stop_event.wait(20)
        except KeyboardInterrupt:  # pragma: no cover
            logger.info("收到中断信号，正在退出 ...")
        finally:
            self.stop_event.set()
            for worker in workers:
                worker.join(timeout=5)

        logger.info("Agent 已退出。累计统计：%s", self.counters)
        logger.info("缓存状态：%s", self.spool.stats())
        return 0

    def _sensor_cycle(self) -> None:
        self.collect_and_report()


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _mac_address() -> str:
    import uuid
    value = uuid.getnode()
    return ":".join(f"{(value >> shift) & 0xFF:02X}" for shift in range(40, -1, -8))


def _os_version() -> str:
    import platform
    return f"{platform.system()} {platform.release()}"


def _process_count() -> int:
    try:
        import psutil
        return len(psutil.pids())
    except Exception:  # pragma: no cover
        return 0


def setup_logging(config: dict) -> None:
    level = getattr(logging, str(config.get("logging", {}).get("level", "INFO")).upper(),
                    logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = config.get("logging", {}).get("file")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, handlers=handlers,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", force=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="NovaEdge 边缘节点采集 Agent")
    parser.add_argument("-c", "--config", default=str(Path(__file__).parent / "config.yaml"),
                        help="配置文件路径（默认同目录 config.yaml）")
    parser.add_argument("--once", action="store_true", help="单轮采集后退出")
    parser.add_argument("--duration", type=int, default=0, help="运行时长（秒），0 为常驻")
    parser.add_argument("--no-camera", action="store_true", help="禁用摄像头采集")
    parser.add_argument("--print-config", action="store_true", help="打印有效配置后退出")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)
    if args.print_config:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0

    agent = EdgeAgent(config, enable_camera=not args.no_camera)

    def _handler(signum, frame):  # pragma: no cover
        logger.info("收到系统信号 %s，正在优雅退出 ...", signum)
        agent.stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):  # pragma: no cover
            pass

    return agent.run(duration=args.duration or None, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
