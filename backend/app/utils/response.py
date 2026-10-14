"""统一响应体、分页与通用工具。"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

CODE_OK = 0
CODE_PARAM_ERROR = 400
CODE_UNAUTHORIZED = 401
CODE_FORBIDDEN = 403
CODE_NOT_FOUND = 404
CODE_CONFLICT = 409
CODE_ERROR = 500


def ok(data: Any = None, message: str = "操作成功", **extra) -> tuple:
    body = {"code": CODE_OK, "message": message, "data": data}
    body.update(extra)
    return jsonify(body), 200


def fail(message: str = "操作失败", code: int = CODE_ERROR, http_status: int = 200, **extra) -> tuple:
    body = {"code": code, "message": message, "data": None}
    body.update(extra)
    return jsonify(body), http_status


def paginated(items: list, total: int, page: int, page_size: int, message: str = "查询成功"):
    return ok({
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
    }, message)


def get_page_args(default_size: int = 20, max_size: int = 200) -> tuple[int, int]:
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.args.get("page_size", default_size))
    except (TypeError, ValueError):
        page_size = default_size
    page = max(page, 1)
    page_size = min(max(page_size, 1), max_size)
    return page, page_size


def parse_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_float(value, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def truthy(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
