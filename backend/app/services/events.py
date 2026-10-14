"""服务端事件总线，用于 SSE 向 Web 控制台实时推送。

设计取舍
--------
* 不引入 Socket.IO / Redis，采用进程内队列 + SSE（Server-Sent Events）。
  控制台只做「服务端 -> 浏览器」的单向推送（节点状态、新告警、新上传媒体），
  下行操作全部走 REST，因此 SSE 完全够用，且零额外依赖、易横向扩展（多实例时换成 Redis Pub/Sub 即可）。
* 每个订阅者独立队列且有界（maxsize），慢客户端自动丢弃最旧事件，不阻塞采集链路。
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any

from . import _noop  # noqa: F401  (占位，避免循环导入告警)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self, maxsize: int = 256) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: str, data: Any) -> int:
        payload = {"event": event, "data": data}
        dead: list[queue.Queue] = []
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()          # 丢弃最旧事件
                    q.put_nowait(payload)
                except (queue.Empty, queue.Full):
                    dead.append(q)
            except Exception:               # pragma: no cover - 防御性
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)
        return len(targets)

    @staticmethod
    def encode(event: str, data: Any) -> str:
        """SSE 报文格式。"""
        body = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        return f"event: {event}\ndata: {body}\n\n"


bus = EventBus()


def publish(event: str, data: Any) -> None:
    """对外快捷发布接口。"""
    try:
        bus.publish(event, data)
    except Exception:  # pragma: no cover - 推送失败不能影响主业务流程
        pass
