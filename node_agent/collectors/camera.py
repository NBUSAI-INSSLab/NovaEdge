"""摄像头采集：抓拍图片与录制视频。

支持多种后端，按 ``config.yaml`` 的 ``camera.backend`` 选择（auto 自动探测）：

====================  ==================================================
backend               说明
====================  ==================================================
``picamera2``         树莓派官方 CSI 摄像头（libcamera 栈），性能最优
``opencv``            USB 摄像头 / V4L2 设备（``cv2.VideoCapture``）
``ffmpeg``            ffmpeg 拉流或直接录制设备
``mock``              无硬件时的合成图像/视频，用于联调与演示
``none``              关闭摄像头能力
====================  ==================================================

无论哪种后端，对外都返回**本地文件路径**，交给 :mod:`uploader` 统一分片上传，
采集与传输解耦，便于断网缓存与重试。
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("agent.camera")

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False

try:
    import numpy as np
    import cv2
    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover
    np = None
    cv2 = None
    CV2_AVAILABLE = False


class Camera:
    def __init__(self, config: dict, node_name: str = "") -> None:
        self.config = config or {}
        self.node_name = node_name
        self.backend = str(self.config.get("backend", "auto")).lower()
        self.mock_enabled = bool(self.config.get("mock_enabled", True))
        self.resolution = tuple(self.config.get("image_resolution", [1280, 720]))
        self.video_resolution = tuple(self.config.get("video_resolution", [1280, 720]))
        self.quality = int(self.config.get("image_quality", 88))
        self.fps = int(self.config.get("video_fps", 20))
        self.duration = int(self.config.get("video_duration", 10))
        self._recording = False
        self._resolve_backend()

    # ------------------------------------------------------------------ #
    # 后端探测
    # ------------------------------------------------------------------ #
    def _resolve_backend(self) -> None:
        if self.backend == "none":
            return
        if self.backend == "auto":
            if self._picamera2_available():
                self.backend = "picamera2"
            elif self._video_devices():
                self.backend = "opencv"
            elif shutil.which("ffmpeg"):
                self.backend = "ffmpeg"
            elif self.mock_enabled:
                self.backend = "mock"
            else:
                self.backend = "none"
        if self.backend == "mock" and not (PIL_AVAILABLE and CV2_AVAILABLE):
            if not PIL_AVAILABLE:
                logger.warning("未安装 Pillow，无法启用 mock 摄像头")
                self.backend = "none"
        logger.info("摄像头后端：%s", self.backend)

    @staticmethod
    def _picamera2_available() -> bool:
        try:
            import picamera2  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _video_devices() -> list[str]:
        return sorted(str(p) for p in Path("/dev").glob("video*")) if Path("/dev").exists() else []

    @property
    def available(self) -> bool:
        return self.backend != "none"

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def capture_image(self, output_dir: Path | str) -> Path | None:
        """抓拍一张图片，返回本地文件路径。"""
        if not self.available:
            return None
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"IMG_{datetime.now():%Y%m%d_%H%M%S}_{int(time.time() * 1000) % 1000:03d}.jpg"
        try:
            if self.backend == "picamera2":
                return self._capture_picamera2(target)
            if self.backend == "opencv":
                return self._capture_opencv(target)
            if self.backend == "ffmpeg":
                return self._capture_ffmpeg(target)
            return self._capture_mock(target)
        except Exception as exc:  # pragma: no cover
            logger.warning("抓拍失败（%s）：%s", self.backend, exc)
            return None

    def record_video(self, output_dir: Path | str, duration: int | None = None) -> Path | None:
        """录制一段视频，返回本地文件路径。"""
        if not self.available:
            return None
        duration = duration or self.duration
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"VID_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        self._recording = True
        try:
            if self.backend == "opencv":
                return self._record_opencv(target, duration)
            if self.backend == "ffmpeg":
                return self._record_ffmpeg(target, duration)
            return self._record_mock(target, duration)
        except Exception as exc:  # pragma: no cover
            logger.warning("录像失败（%s）：%s", self.backend, exc)
            return None
        finally:
            self._recording = False

    def stop_record(self) -> None:
        """请求提前结束当前录像（由下行指令触发）。"""
        self._recording = False

    def self_test(self) -> dict:
        """自检摄像头可用性。"""
        result = {"backend": self.backend, "available": self.available,
                  "resolution": list(self.resolution)}
        if self.backend == "opencv" and CV2_AVAILABLE:
            cap = cv2.VideoCapture(0)
            result["device_opened"] = bool(cap.isOpened())
            cap.release()
        return result

    # ------------------------------------------------------------------ #
    # 具体实现
    # ------------------------------------------------------------------ #
    def _capture_picamera2(self, target: Path) -> Path | None:
        from picamera2 import Picamera2  # pragma: no cover - 仅树莓派
        camera = Picamera2()
        cfg = camera.create_still_configuration(
            main={"size": self.resolution, "format": "RGB888"})
        camera.configure(cfg)
        camera.start()
        time.sleep(0.6)          # 等待自动曝光稳定
        camera.capture_file(str(target))
        camera.stop()
        camera.close()
        return target

    def _capture_opencv(self, target: Path) -> Path | None:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            cap.release()
            return self._capture_mock(target) if self.mock_enabled else None
        for _ in range(3):        # 丢弃前几帧，避免曝光未完成
            cap.read()
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return None
        frame = self._draw_overlay_cv(frame)
        cv2.imwrite(str(target), frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
        return target

    def _capture_ffmpeg(self, target: Path) -> Path | None:
        device = self._video_devices()[0] if self._video_devices() else "/dev/video0"
        cmd = ["ffmpeg", "-y", "-f", "v4l2", "-i", device, "-frames:v", "1",
               "-q:v", "3", str(target)]
        done = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        if done.returncode != 0 or not target.exists():
            logger.warning("ffmpeg 抓拍失败：%s", done.stderr.decode("utf-8", "ignore")[-200:])
            return self._capture_mock(target) if self.mock_enabled else None
        return target

    def _record_opencv(self, target: Path, duration: int) -> Path | None:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            cap.release()
            return self._record_mock(target, duration) if self.mock_enabled else None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.video_resolution[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.video_resolution[1])
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(target), fourcc, self.fps,
                                 (self.video_resolution[0], self.video_resolution[1]))
        started = time.time()
        try:
            while self._recording and time.time() - started < duration:
                ok, frame = cap.read()
                if not ok:
                    break
                writer.write(self._draw_overlay_cv(frame))
        finally:
            writer.release()
            cap.release()
        return target if target.exists() and target.stat().st_size > 0 else None

    def _record_ffmpeg(self, target: Path, duration: int) -> Path | None:
        device = self._video_devices()[0] if self._video_devices() else "/dev/video0"
        cmd = ["ffmpeg", "-y", "-f", "v4l2", "-framerate", str(self.fps), "-i", device,
               "-t", str(duration), "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(target)]
        done = subprocess.run(cmd, capture_output=True, timeout=duration + 60, check=False)
        if done.returncode != 0:
            return self._record_mock(target, duration) if self.mock_enabled else None
        return target

    # ---------------- mock：合成图像 / 视频 ----------------
    def _capture_mock(self, target: Path) -> Path | None:
        if not PIL_AVAILABLE:
            return None
        width, height = self.resolution
        image = Image.new("RGB", (width, height), (14, 32, 54))
        draw = ImageDraw.Draw(image)
        # 渐变背景
        for y in range(height):
            ratio = y / max(height - 1, 1)
            draw.line([(0, y), (width, y)],
                      fill=(int(14 + 30 * ratio), int(32 + 55 * ratio), int(54 + 80 * ratio)))
        # 模拟被识别的目标框
        objects = int(self.config.get("mock_objects", 2))
        for index in range(objects):
            seed = (time.time() // 3 + index * 37) % 100
            x = int(width * (0.12 + 0.17 * index)) % max(width - 200, 1)
            y = int(height * (0.35 + 0.05 * math.sin(seed + index))) % max(height - 160, 1)
            w, h = 120, 150
            draw.rectangle([x, y, x + w, y + h], outline=(80, 220, 190), width=3)
            draw.rectangle([x, y - 22, x + 86, y], fill=(80, 220, 190))
            draw.text((x + 6, y - 17), f"person {0.86 + index * 0.03:.2f}", fill=(10, 30, 45))
        # HUD 信息
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.rectangle([0, 0, width, 34], fill=(8, 22, 38))
        draw.text((12, 10), f"{self.node_name or 'EdgeNode'}  |  {stamp}",
                  fill=(150, 225, 235))
        draw.text((12, height - 26), f"SIMULATED CAMERA  {width}x{height}",
                  fill=(120, 160, 180))
        image.save(target, "JPEG", quality=self.quality)
        return target

    def _record_mock(self, target: Path, duration: int) -> Path | None:
        """用 OpenCV 把合成帧写成真实可播放的 MP4（便于验证视频链路端到端可用）。"""
        if not CV2_AVAILABLE or not PIL_AVAILABLE:
            logger.warning("缺少 OpenCV/Pillow，跳过模拟录像")
            return None
        width, height = self.video_resolution
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(target), fourcc, self.fps, (width, height))
        total_frames = max(int(duration * self.fps), 1)
        tmp_dir = Path(tempfile.mkdtemp(prefix="mockframe_"))
        try:
            for index in range(total_frames):
                if not self._recording:
                    break
                frame_path = tmp_dir / "frame.jpg"
                self._capture_mock(frame_path)
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    continue
                frame = cv2.resize(frame, (width, height))
                # 帧序号与水印，确保视频内容可见变化
                cv2.putText(frame, f"FRAME {index:04d}/{total_frames:04d}",
                            (20, height - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (90, 225, 200), 2)
                cv2.circle(frame, (width - 60 - (index * 4) % (width - 120), 60), 12,
                           (60, 200, 255), -1)
                writer.write(frame)
        finally:
            writer.release()
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if not target.exists() or target.stat().st_size == 0:
            return None
        logger.info("模拟录像完成：%s（%.2f MB，%d 帧）",
                    target.name, target.stat().st_size / 1048576, total_frames)
        return target

    def _draw_overlay_cv(self, frame):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 32), (20, 30, 45), -1)
        cv2.putText(frame, f"{self.node_name or 'EdgeNode'}  {stamp}", (12, 23),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (150, 225, 235), 1, cv2.LINE_AA)
        return frame
