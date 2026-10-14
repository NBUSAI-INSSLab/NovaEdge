"""本地数据缓存（Spool）——断网不丢数据的关键。

策略
----
* 遥测批次以「一个 JSON 文件 = 一个批次」落盘，上报成功后立即删除；
* 网络异常时直接跳过本批，文件保留，恢复后按时间顺序补传；
* 目录内文件数超过 ``max_batches`` 时删除最旧批次，避免占满磁盘。

媒体文件（图片/视频）在采样时写入本地采集目录，
上传成功后删除本地文件；上传失败则保留，等下一轮重试。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("agent.spool")


class Spool:
    def __init__(self, spool_dir: str | Path, max_batches: int = 2000) -> None:
        self.root = Path(spool_dir)
        self.max_batches = max(int(max_batches), 10)
        self.telemetry_dir = self.root / "telemetry"
        self.media_dir = self.root / "media"
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 遥测批次 ----------------
    def push_batch(self, samples: list[dict]) -> Path:
        name = f"{int(time.time() * 1000):013d}_{len(samples):04d}.json"
        path = self.telemetry_dir / name
        path.write_text(json.dumps(samples, ensure_ascii=False), encoding="utf-8")
        self._trim()
        return path

    def pending_batches(self) -> list[Path]:
        return sorted(self.telemetry_dir.glob("*.json"))

    def read_batch(self, path: Path) -> list[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def remove(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def pending_count(self) -> int:
        return len(list(self.telemetry_dir.glob("*.json")))

    def _trim(self) -> None:
        files = self.pending_batches()
        if len(files) <= self.max_batches:
            return
        for path in files[: len(files) - self.max_batches]:
            logger.warning("缓存批次超出上限，丢弃最旧数据：%s", path.name)
            self.remove(path)

    # ---------------- 媒体文件 ----------------
    def stage_media(self, path: Path) -> Path:
        """把采集出的媒体文件登记到缓存目录（便于统一重试）。"""
        return path

    def media_pending(self) -> list[Path]:
        files = []
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.mp4", "*.avi", "*.mov"):
            files.extend(self.media_dir.glob(pattern))
        return sorted(files, key=lambda p: p.stat().st_mtime)

    # ---------------- 状态 ----------------
    def stats(self) -> dict:
        return {
            "pending_telemetry_batches": self.pending_count(),
            "pending_media_files": len(self.media_pending()),
            "spool_dir": str(self.root),
        }
