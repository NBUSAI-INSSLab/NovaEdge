"""平台配置。

通过环境变量切换运行环境：

    DB_TYPE=sqlite   -> 本地测试（默认，零依赖，开箱即用）
    DB_TYPE=mysql    -> 生产部署（pymysql 驱动，utf8mb4）

示例（生产）::

    set DB_TYPE=mysql
    set MYSQL_HOST=127.0.0.1
    set MYSQL_USER=novaedge
    set MYSQL_PASSWORD=******
    set MYSQL_DB=novaedge
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent          # backend/
PROJECT_DIR = BASE_DIR.parent                        # NovaEdge/


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # ---------- 基础 ----------
    APP_NAME = "NovaEdge 边缘智算管理平台"
    SECRET_KEY = os.getenv("SECRET_KEY", "novaedge-dev-secret-please-change-in-prod")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_HOURS", "12")))
    JSON_AS_ASCII = False
    RESTFUL_JSON = {"ensure_ascii": False}

    # ---------- 数据库 ----------
    DB_TYPE = os.getenv("DB_TYPE", "sqlite").strip().lower()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    if DB_TYPE == "mysql":
        MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
        MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
        MYSQL_USER = os.getenv("MYSQL_USER", "root")
        MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
        MYSQL_DB = os.getenv("MYSQL_DB", "novaedge")
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/"
            f"{MYSQL_DB}?charset=utf8mb4"
        )
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "pool_size": 10,
            "max_overflow": 20,
        }
    else:
        SQLITE_PATH = os.getenv("SQLITE_PATH", str(BASE_DIR / "data" / "novaedge.db"))
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{SQLITE_PATH}"

    # ---------- 文件存储 ----------
    STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", str(BASE_DIR / "storage")))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(2 * 1024 * 1024 * 1024)))  # 2GB
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", str(2 * 1024 * 1024)))       # 分片 2MB
    LARGE_CHUNK_SIZE = int(os.getenv("LARGE_CHUNK_SIZE", str(8 * 1024 * 1024)))  # 视频 8MB
    UPLOAD_SESSION_TTL = int(os.getenv("UPLOAD_SESSION_TTL", str(24 * 3600)))    # 会话有效期
    THUMB_SIZE = (480, 360)
    ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
    ALLOWED_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".h264", ".flv", ".webm"}

    # ---------- MQTT（EMQX / Mosquitto） ----------
    MQTT_ENABLED = _env_bool("MQTT_ENABLED", False)
    MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
    MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
    MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "edge")
    MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))

    # ---------- 业务参数 ----------
    HEARTBEAT_TIMEOUT = int(os.getenv("HEARTBEAT_TIMEOUT", "180"))   # 超过该秒数判离线
    DEFAULT_REPORT_INTERVAL = int(os.getenv("DEFAULT_REPORT_INTERVAL", "60"))
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")

    # ---------- 跨域 ----------
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")


class TestingConfig(Config):
    TESTING = True
    DB_TYPE = "sqlite"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    MQTT_ENABLED = False
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False


CONFIG_MAP = {"default": Config, "testing": TestingConfig, "production": Config}
