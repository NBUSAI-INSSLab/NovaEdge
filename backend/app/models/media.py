"""媒体资产表：图片、视频的元数据与分片上传会话。

文件本体落磁盘（本地存储），数据库只存元数据 + 相对路径，
生产环境可把 ``storage_type`` 切到 S3/MinIO/OSS，业务层不用改。
"""

from __future__ import annotations

from ..extensions import db
from .base import BigIntPK, SerializerMixin, TimestampMixin

FILE_IMAGE = "image"
FILE_VIDEO = "video"
FILE_OTHER = "other"

FILE_TYPE_LABELS = {FILE_IMAGE: "图片", FILE_VIDEO: "视频", FILE_OTHER: "其他"}

UPLOAD_INIT = "init"
UPLOAD_UPLOADING = "uploading"
UPLOAD_MERGING = "merging"
UPLOAD_DONE = "done"
UPLOAD_FAILED = "failed"
UPLOAD_ABORTED = "aborted"


class MediaFile(db.Model, TimestampMixin, SerializerMixin):
    """图片 / 视频资产。"""

    __tablename__ = "media_file"

    BASE_FIELDS = (
        "id", "node_id", "file_type", "file_name", "storage_type", "storage_path",
        "thumb_path", "file_size", "mime_type", "sha256", "width", "height",
        "duration_sec", "captured_at", "source", "tags", "meta", "status",
        "remark", "created_at", "updated_at",
    )
    DATETIME_FIELDS = ("captured_at", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    file_type = db.Column(db.String(16), default=FILE_IMAGE, nullable=False, index=True)
    file_name = db.Column(db.String(255), nullable=False)
    storage_type = db.Column(db.String(16), default="local", comment="local / s3 / oss")
    storage_path = db.Column(db.String(512), nullable=False, comment="相对存储根目录的路径")
    thumb_path = db.Column(db.String(512), default="", comment="缩略图路径（图片自动生成）")
    file_size = db.Column(BigIntPK, default=0, comment="字节数")
    mime_type = db.Column(db.String(96), default="")
    sha256 = db.Column(db.String(64), default="", index=True, comment="内容指纹，用于秒传与去重")
    width = db.Column(db.Integer, default=0)
    height = db.Column(db.Integer, default=0)
    duration_sec = db.Column(db.Float, default=0.0, comment="视频时长")
    captured_at = db.Column(db.DateTime, nullable=True, index=True, comment="采集时刻（节点侧）")
    source = db.Column(db.String(32), default="camera", comment="camera / scheduled / manual")
    tags = db.Column(db.JSON, default=list, comment="标签数组")
    meta = db.Column(db.JSON, default=dict, comment="EXIF / 视频编码等扩展信息")
    status = db.Column(db.String(16), default="ready", index=True, comment="ready / archived / deleted")
    remark = db.Column(db.String(255), default="")

    @property
    def file_type_label(self) -> str:
        return FILE_TYPE_LABELS.get(self.file_type, self.file_type)

    def to_dict(self, extra: dict | None = None) -> dict:
        payload = {
            "file_type_label": self.file_type_label,
            "url": f"/api/v1/media/{self.id}/raw",
            "thumb_url": f"/api/v1/media/{self.id}/thumb" if self.thumb_path else "",
            "file_size_human": human_size(self.file_size or 0),
        }
        payload.update(extra or {})
        return super().to_dict(payload)


class UploadSession(db.Model, TimestampMixin, SerializerMixin):
    """分片上传会话：支持大视频断点续传、秒传（sha256 命中直接复用）。"""

    __tablename__ = "upload_session"

    BASE_FIELDS = ("id", "upload_id", "node_id", "file_name", "file_type", "file_size",
                   "chunk_size", "total_chunks", "received_chunks", "sha256",
                   "temp_dir", "status", "media_file_id", "captured_at", "error_msg",
                   "expires_at", "created_at", "updated_at")
    DATETIME_FIELDS = ("captured_at", "expires_at", "created_at", "updated_at")

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    upload_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    node_id = db.Column(BigIntPK, db.ForeignKey("node.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(16), default=FILE_IMAGE)
    file_size = db.Column(BigIntPK, default=0)
    chunk_size = db.Column(db.Integer, default=2097152)
    total_chunks = db.Column(db.Integer, default=1)
    received_chunks = db.Column(db.Integer, default=0)
    sha256 = db.Column(db.String(64), default="")
    temp_dir = db.Column(db.String(512), default="")
    status = db.Column(db.String(16), default=UPLOAD_INIT, index=True)
    media_file_id = db.Column(BigIntPK, default=0)
    captured_at = db.Column(db.DateTime, nullable=True)
    error_msg = db.Column(db.String(512), default="")
    expires_at = db.Column(db.DateTime, nullable=True)


def human_size(num: int) -> str:
    """字节数转可读体积。"""
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
