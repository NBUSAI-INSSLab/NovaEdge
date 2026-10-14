"""传感器采集：真实硬件后端 + 模拟后端 + 系统资源后端。

现场部署时按需在 ``config.yaml`` 的 ``sensors.backends`` 中列出后端，
每个后端返回 ``{metric_key: value}``，由 Agent 汇总后统一上报。
"""

from __future__ import annotations

import glob
import logging
import math
import os
import random
import time
from pathlib import Path

logger = logging.getLogger("agent.sensors")


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fp:
            return fp.read().strip()
    except OSError:
        return ""


class BaseBackend:
    name = "base"

    def available(self) -> bool:
        return True

    def read(self) -> dict:
        return {}


class SystemBackend(BaseBackend):
    """节点自身资源画像（CPU / 内存 / 磁盘 / SoC 温度 / 网络）。"""

    name = "system"

    def __init__(self) -> None:
        self._last_net = self._net_bytes()
        self._last_ts = time.time()
        try:
            import psutil  # noqa: F401
            self._psutil = True
        except ImportError:
            self._psutil = False

    @staticmethod
    def _net_bytes() -> tuple[int, int]:
        """上一次采样的网卡累计字节数，用于计算速率。"""
        return 0, 0

    def read(self) -> dict:
        data: dict = {}
        if self._psutil:
            import psutil
            data["cpu_percent"] = round(psutil.cpu_percent(interval=0.2), 1)
            data["mem_percent"] = round(psutil.virtual_memory().percent, 1)
            data["disk_percent"] = round(psutil.disk_usage("/").percent, 1)
            try:
                sensors = psutil.sensors_temperatures()
                if sensors:
                    first = next(iter(sensors.values()))
                    if first:
                        data["cpu_temp"] = round(first[0].current, 1)
            except (AttributeError, NotImplementedError, StopIteration):
                pass
            try:
                counters = psutil.net_io_counters()
                now = time.time()
                elapsed = max(now - self._last_ts, 0.001)
                rx_rate = (counters.bytes_recv - self._last_net[0]) * 8 / elapsed / 1000
                tx_rate = (counters.bytes_sent - self._last_net[1]) * 8 / elapsed / 1000
                data["net_rx_kbps"] = round(max(rx_rate, 0), 1)
                data["net_tx_kbps"] = round(max(tx_rate, 0), 1)
                self._last_net = (counters.bytes_recv, counters.bytes_sent)
                self._last_ts = now
            except Exception:  # pragma: no cover
                pass
        else:  # 树莓派精简系统无 psutil 时的兜底
            load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.2
            data["cpu_percent"] = round(min(load / max(os.cpu_count() or 1, 1) * 100, 100), 1)
            meminfo = _read_text("/proc/meminfo")
            if meminfo:
                values = {}
                for line in meminfo.splitlines():
                    parts = line.split(":")
                    if len(parts) == 2:
                        values[parts[0].strip()] = int(parts[1].strip().split()[0])
                total = values.get("MemTotal", 0)
                available = values.get("MemAvailable", 0)
                if total:
                    data["mem_percent"] = round((total - available) / total * 100, 1)
        if "cpu_temp" not in data:
            for pattern in ("/sys/class/thermal/thermal_zone*/temp",):
                for path in glob.glob(pattern):
                    raw = _read_text(path)
                    if raw.isdigit():
                        data["cpu_temp"] = round(int(raw) / 1000, 1)
                        break
                if "cpu_temp" in data:
                    break
        return data


class DS18B20Backend(BaseBackend):
    """1-Wire 数字温度传感器（树莓派最常见接法）。"""

    name = "ds18b20"

    def __init__(self, config: dict) -> None:
        self.device_id = str(config.get("device_id", "")).strip()
        self.sysfs = str(config.get("sysfs_path", "/sys/bus/w1/devices"))
        self.metric = str(config.get("metric", "temperature"))

    def available(self) -> bool:
        if not os.path.isdir(self.sysfs):
            return False
        return bool(self.device_id or glob.glob(f"{self.sysfs}/28-*"))

    def read(self) -> dict:
        device = self.device_id
        if not device:
            candidates = glob.glob(f"{self.sysfs}/28-*")
            if not candidates:
                return {}
            device = Path(candidates[0]).name
        raw = _read_text(f"{self.sysfs}/{device}/w1_slave")
        for token in raw.split():
            if token.startswith("t="):
                try:
                    return {self.metric: round(int(token[2:]) / 1000.0, 2)}
                except ValueError:
                    return {}
        return {}


class DHT22Backend(BaseBackend):
    """DHT22 / AM2302 温湿度传感器。"""

    name = "dht22"

    def __init__(self, config: dict) -> None:
        self.pin = int(config.get("pin", 4))

    def available(self) -> bool:
        try:
            import Adafruit_DHT  # noqa: F401
            return True
        except ImportError:
            return False

    def read(self) -> dict:
        try:
            import Adafruit_DHT
            sensor = Adafruit_DHT.DHT22
            humidity, temperature = Adafruit_DHT.read_retry(sensor, self.pin)
            if humidity is None or temperature is None:
                return {}
            return {"temperature": round(temperature, 1), "humidity": round(humidity, 1)}
        except Exception as exc:  # pragma: no cover
            logger.warning("DHT22 读取失败：%s", exc)
            return {}


class ADS1115Backend(BaseBackend):
    """I²C 16 位 ADC，用于采集电压、电流等模拟量。"""

    name = "ads1115"

    def __init__(self, config: dict) -> None:
        self.address = int(config.get("i2c_address", 0x48))
        self.channels = config.get("channels", [])

    def available(self) -> bool:
        try:
            import Adafruit_ADS1x15  # noqa: F401
            return True
        except ImportError:
            return False

    def read(self) -> dict:
        try:
            import Adafruit_ADS1x15
            adc = Adafruit_ADS1x15.ADS1115(address=self.address)
            data = {}
            for item in self.channels:
                raw = adc.read_adc(int(item.get("channel", 0)), gain=1)
                volts = raw / 32767.0 * 4.096 * float(item.get("scale", 1.0))
                data[item.get("metric", f"adc{item.get('channel')}")] = round(volts, 3)
            return data
        except Exception as exc:  # pragma: no cover
            logger.warning("ADS1115 读取失败：%s", exc)
            return {}


class MockBackend(BaseBackend):
    """无硬件联调：按正弦波 + 随机噪声生成合理的环境数据。

    引入相位漂移让曲线有真实感（缓慢起伏而非纯噪声），
    便于验证前端折线图、告警阈值触发与小时聚合逻辑。
    """

    name = "mock"

    def __init__(self, config: dict) -> None:
        self.metrics = config or {}
        self._start = time.time()

    def read(self) -> dict:
        elapsed = time.time() - self._start
        data = {}
        for key, spec in self.metrics.items():
            base = float(spec.get("base", 25))
            amplitude = float(spec.get("amplitude", 1))
            noise = float(spec.get("noise", 0.1))
            # 周期 10 分钟的正弦波动 + 高斯噪声
            wave = math.sin(elapsed / 600.0 * 2 * math.pi) * amplitude
            value = base + wave + random.gauss(0, noise)
            data[key] = round(value, 2)
        return data


class SensorHub:
    """按配置装载后端，聚合读取结果。"""

    def __init__(self, config: dict) -> None:
        self.config = config or {}
        self.backends: list[BaseBackend] = []
        self.units: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        names = self.config.get("backends") or ["system"]
        factory = {
            "system": lambda: SystemBackend(),
            "mock": lambda: MockBackend(self.config.get("mock_metrics", {})),
            "ds18b20": lambda: DS18B20Backend(self.config.get("ds18b20", {})),
            "dht22": lambda: DHT22Backend(self.config.get("dht22", {})),
            "ads1115": lambda: ADS1115Backend(self.config.get("ads1115", {})),
        }
        for name in names:
            builder = factory.get(name)
            if builder is None:
                logger.warning("未知的传感器后端：%s", name)
                continue
            backend = builder()
            if backend.available():
                self.backends.append(backend)
                logger.info("传感器后端已启用：%s", name)
            else:
                logger.info("传感器后端不可用，已跳过：%s", name)

        for item in (self.config.get("ads1115", {}).get("channels") or []):
            self.units[item.get("metric", "")] = item.get("unit", "")
        for key, spec in (self.config.get("mock_metrics") or {}).items():
            self.units[key] = spec.get("unit", "")
        self.units["temperature"] = self.units.get("temperature", "℃")
        self.units["humidity"] = self.units.get("humidity", "%RH")

    def read(self) -> dict[str, float]:
        merged: dict = {}
        for backend in self.backends:
            try:
                merged.update(backend.read())
            except Exception as exc:  # pragma: no cover
                logger.warning("后端 %s 读取异常：%s", backend.name, exc)
        # 系统资源指标由心跳通道上报，传感器通道不再重复
        for key in ("cpu_percent", "mem_percent", "disk_percent", "cpu_temp",
                    "net_rx_kbps", "net_tx_kbps"):
            merged.pop(key, None)
        return merged

    def read_system(self) -> dict[str, float]:
        for backend in self.backends:
            if backend.name == "system":
                return backend.read()
        return {}


def collect_capabilities(sensor_config: dict, camera_backend: str) -> dict:
    """生成能力清单，节点上线时上报给平台。"""
    backends = sensor_config.get("backends") or []
    sensors = []
    for spec in (sensor_config.get("mock_metrics") or {}):
        sensors.append(spec)
    if "ds18b20" in backends:
        sensors.append("ds18b20_temp")
    if "dht22" in backends:
        sensors.extend(["temperature", "humidity"])
    if "ads1115" in backends:
        sensors.extend([c.get("metric", "") for c in sensor_config.get("ads1115", {}).get("channels", [])])
    return {
        "camera": camera_backend not in ("none",),
        "video": camera_backend not in ("none",),
        "sensors": sorted({s for s in sensors if s}),
    }
