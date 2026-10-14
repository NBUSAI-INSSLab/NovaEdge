"""采集器集合。"""

from .camera import Camera
from .sensors import SensorHub, collect_capabilities

__all__ = ["Camera", "SensorHub", "collect_capabilities"]
