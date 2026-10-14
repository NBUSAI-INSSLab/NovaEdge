"""本地对象存储实现：媒体文件落盘、缩略图生成、路径规划。"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from flask import current_app

VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".h264", ".flv", ".webm"}


def storage_root() -> Path:
    root = Path(current_app.config["STORAGE_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    return root


def classify_file_type(file_name: str, declared: str = "") -> str:
    """按扩展名归类：image / video / other。"""
    if declared in {"image", "video"}:
        return declared
    ext = Path(file_name or "").suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}:
        return "image"
    return "other"


def build_relative_path(node_uid: str, file_type: str, file_name: str,
                        captured_at: datetime | None = None) -> str:
    """按 年/月/日/节点 分目录，避免单目录文件过多。"""
    stamp = captured_at or datetime.utcnow()
    ext = Path(file_name).suffix.lower() or (".mp4" if file_type == "video" else ".jpg")
    bucket = "videos" if file_type == "video" else ("images" if file_type == "image" else "others")
    safe_uid = (node_uid or "unknown").replace("/", "_").replace("\\", "_")
    unique = uuid.uuid4().hex[:16]
    return f"{bucket}/{stamp:%Y/%m/%d}/{safe_uid}/{stamp:%H%M%S}_{unique}{ext}"


def absolute_path(relative: str) -> Path:
    return storage_root() / relative


def sha256_of(path: Path, block: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(block)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def make_thumbnail(source: Path, relative_source: str) -> tuple[str, int, int]:
    """生成图片缩略图，返回 (缩略图相对路径, 宽, 高)。

    未安装 Pillow 或格式不支持时优雅降级：返回空缩略图与 0 尺寸。
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return "", 0, 0
    try:
        with Image.open(source) as img:
            width, height = img.size
            thumb_rel = str(Path("thumbs") / Path(relative_source).relative_to(Path(relative_source).parts[0]))
            thumb_abs = absolute_path(thumb_rel)
            thumb_abs.parent.mkdir(parents=True, exist_ok=True)
            target = current_app.config.get("THUMB_SIZE", (480, 360))
            img.thumbnail(target)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(thumb_abs, "JPEG", quality=82)
            return thumb_rel.replace("\\", "/"), width, height
    except Exception:  # pragma: no cover
        return "", 0, 0


def probe_video(path: Path) -> tuple[float, dict]:
    """探测视频时长/分辨率。优先 ffprobe，缺失时返回空。"""
    import json
    import subprocess
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0, {}
    try:
        out = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=20, check=False,
        )
        info = json.loads(out.stdout.decode("utf-8", "ignore") or "{}")
        duration = float(info.get("format", {}).get("duration", 0) or 0)
        meta = {"format": info.get("format", {}).get("format_name", "")}
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                meta.update({
                    "codec": stream.get("codec_name", ""),
                    "width": int(stream.get("width") or 0),
                    "height": int(stream.get("height") or 0),
                    "fps": stream.get("r_frame_rate", ""),
                })
                break
        return duration, meta
    except Exception:  # pragma: no cover
        return 0.0, {}


def delete_media_files(*relative_paths: str) -> None:
    for rel in relative_paths:
        if not rel:
            continue
        try:
            target = absolute_path(rel)
            if target.exists() and target.is_file():
                target.unlink()
        except Exception:  # pragma: no cover
            pass
