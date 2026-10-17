"""NovaEdge 应用工厂。"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory

from .api import register_blueprints
from .extensions import cors, db, jwt
from .models import utcnow
from .utils.response import CODE_NOT_FOUND, fail

logger = logging.getLogger("novaedge")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(config_object=None, config_overrides: dict | None = None) -> Flask:
    from config import CONFIG_MAP, TestingConfig

    app = Flask(__name__, static_folder=None)

    if config_object is None:
        config_object = TestingConfig if _detect_testing() else CONFIG_MAP["default"]
    if isinstance(config_object, str):
        config_object = CONFIG_MAP.get(config_object, CONFIG_MAP["default"])
    app.config.from_object(config_object)
    if config_overrides:
        app.config.update(config_overrides)

    _setup_logging(app)
    _setup_storage(app)

    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
                  supports_credentials=True)

    register_blueprints(app)
    _register_error_handlers(app)
    _register_meta_routes(app)
    _register_jwt_handlers(app)

    with app.app_context():
        # SQLite 需要先建库文件目录
        if app.config["DB_TYPE"] == "sqlite":
            uri = app.config["SQLALCHEMY_DATABASE_URI"]
            if "memory" not in uri:
                Path(uri.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
        db.create_all()

    # MQTT 通道（可选）
    if app.config.get("MQTT_ENABLED"):
        from .protocols.mqtt_client import mqtt_ingest, mqtt_publisher
        mqtt_ingest.init_app(app)
        mqtt_publisher.init_app(app)
        mqtt_ingest.start()
        mqtt_publisher.start()

    _serve_frontend(app)
    logger.info("%s 已启动 | 数据库=%s", app.config["APP_NAME"], app.config["DB_TYPE"])
    return app


def _detect_testing() -> bool:
    import os
    return os.getenv("FLASK_ENV") == "testing" or bool(os.getenv("PYTEST_CURRENT_TEST"))


def _setup_logging(app: Flask) -> None:
    level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    app.logger.setLevel(level)


def _setup_storage(app: Flask) -> None:
    root = Path(app.config["STORAGE_ROOT"])
    for sub in ("images", "videos", "thumbs", "temp"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def _register_jwt_handlers(app: Flask) -> None:
    @jwt.unauthorized_loader
    def _missing(reason):
        return fail("未提供访问令牌，请先登录", 401, 401)

    @jwt.invalid_token_loader
    def _invalid(reason):
        return fail("访问令牌无效", 401, 401)

    @jwt.expired_token_loader
    def _expired(header, payload):
        return fail("登录已过期，请重新登录", 401, 401)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def _not_found(error):
        if request.path.startswith("/api/"):
            return fail(f"接口不存在：{request.path}", CODE_NOT_FOUND, 404)
        return _spa_or_index()

    @app.errorhandler(405)
    def _method_not_allowed(error):
        return fail(f"请求方法不被允许：{request.method} {request.path}", 405, 405)

    @app.errorhandler(413)
    def _too_large(error):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return fail(f"文件超出单次上传上限（{limit} MB），请使用分片上传接口", 413, 413)

    @app.errorhandler(500)
    def _server_error(error):
        logger.exception("服务器内部错误: %s", error)
        return fail("服务器内部错误，请查看服务端日志", 500, 500)


def _register_meta_routes(app: Flask) -> None:
    @app.get("/api/v1")
    def api_index():
        return jsonify({
            "code": 0,
            "message": "NovaEdge 边缘智算管理平台 API",
            "data": {
                "version": "1.0.0",
                "docs": "/api/v1/meta/endpoints",
                "server_time": utcnow().isoformat() + "Z",
            },
        })

    @app.get("/api/v1/meta/endpoints")
    def endpoints():
        """列出全部已注册接口，便于联调与自查。"""
        groups: dict[str, list] = {}
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
            if not str(rule).startswith("/api/"):
                continue
            if rule.endpoint == "static":
                continue
            path = str(rule)
            tag = path.split("/")[3] if len(path.split("/")) > 3 else "root"
            methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
            groups.setdefault(tag, []).append({"path": path, "methods": methods,
                                               "endpoint": rule.endpoint})
        total = sum(len(v) for v in groups.values())
        return jsonify({"code": 0, "message": f"共 {total} 个接口", "data": groups})


def _serve_frontend(app: Flask) -> None:
    """打包后的 Vue 前端由 Flask 直接托管（单端口部署）。"""
    dist = Path(FRONTEND_DIST)

    @app.get("/")
    def index():
        if (dist / "index.html").exists():
            return send_from_directory(dist, "index.html")
        return jsonify({
            "code": 0,
            "message": "NovaEdge 后端已就绪；前端请运行 npm run dev 或 npm run build",
            "data": {"frontend_dist_exists": False, "api": "/api/v1/meta/endpoints"},
        })

    @app.get("/<path:path>")
    def spa(path: str):
        if path.startswith("api/"):
            return fail(f"接口不存在：/{path}", CODE_NOT_FOUND, 404)
        target = dist / path
        if target.is_file():
            return send_from_directory(dist, path)
        if (dist / "index.html").exists():
            return send_from_directory(dist, "index.html")
        return redirect("/")
