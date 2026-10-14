"""物模型（指标字典）管理接口。"""

from __future__ import annotations

from flask import Blueprint, request
from sqlalchemy import func

from ..extensions import db
from ..models import (DATA_TYPES, METRIC_CATEGORIES, MetricDef, Telemetry,
                      utcnow)
from ..utils.jwt_helper import login_required, operator_required
from ..utils.response import (CODE_CONFLICT, CODE_NOT_FOUND, fail,
                              get_page_args, ok, paginated, parse_float,
                              parse_int)

bp = Blueprint("metrics", __name__)


@bp.get("/categories")
@login_required
def categories():
    return ok({
        "data_types": [{"value": k, "label": v} for k, v in DATA_TYPES.items()],
        "categories": [{"value": k, "label": v} for k, v in METRIC_CATEGORIES.items()],
    })


@bp.get("")
@login_required
def list_metrics():
    page, page_size = get_page_args(50)
    query = MetricDef.query
    if request.args.get("category"):
        query = query.filter(MetricDef.category == request.args["category"])
    if request.args.get("data_type"):
        query = query.filter(MetricDef.data_type == request.args["data_type"])
    keyword = request.args.get("keyword", "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(MetricDef.metric_key.like(like),
                                    MetricDef.name.like(like)))

    total = query.count()
    rows = query.order_by(MetricDef.is_system.desc(), MetricDef.id.asc()) \
        .offset((page - 1) * page_size).limit(page_size).all()

    # 附带每个指标的采样量，便于判断是否可下线
    counts = dict(db.session.query(Telemetry.metric_key, func.count(Telemetry.id))
                  .group_by(Telemetry.metric_key).all())
    items = [m.to_dict({"sample_count": int(counts.get(m.metric_key, 0))}) for m in rows]
    return paginated(items, total, page, page_size)


@bp.get("/<int:metric_id>")
@login_required
def metric_detail(metric_id: int):
    metric = MetricDef.query.get(metric_id)
    if metric is None:
        return fail("指标不存在", CODE_NOT_FOUND, 404)
    return ok(metric.to_dict())


@bp.post("")
@operator_required
def create_metric():
    payload = request.get_json(silent=True) or {}
    metric_key = str(payload.get("metric_key", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not metric_key or not name:
        return fail("指标编码与名称不能为空", 400)
    if MetricDef.query.filter_by(metric_key=metric_key).first():
        return fail(f"指标 {metric_key} 已存在", CODE_CONFLICT)
    metric = MetricDef(
        metric_key=metric_key, name=name,
        data_type=str(payload.get("data_type", "float")),
        unit=str(payload.get("unit", "")),
        category=str(payload.get("category", "custom")),
        min_value=parse_float(payload.get("min_value")),
        max_value=parse_float(payload.get("max_value")),
        precision=parse_int(payload.get("precision"), 2),
        enum_options=payload.get("enum_options") or [],
        applicable_type=str(payload.get("applicable_type", "")),
        description=str(payload.get("description", "")),
    )
    db.session.add(metric)
    db.session.commit()
    return ok(metric.to_dict(), "指标已创建")


@bp.put("/<int:metric_id>")
@operator_required
def update_metric(metric_id: int):
    metric = MetricDef.query.get(metric_id)
    if metric is None:
        return fail("指标不存在", CODE_NOT_FOUND, 404)
    payload = request.get_json(silent=True) or {}
    for field in ("name", "data_type", "unit", "category", "applicable_type", "description"):
        if field in payload:
            setattr(metric, field, str(payload[field]))
    if "min_value" in payload:
        metric.min_value = parse_float(payload["min_value"])
    if "max_value" in payload:
        metric.max_value = parse_float(payload["max_value"])
    if "precision" in payload:
        metric.precision = parse_int(payload["precision"], 2)
    if "enum_options" in payload:
        metric.enum_options = payload["enum_options"] or []
    db.session.commit()
    return ok(metric.to_dict(), "指标已更新")


@bp.delete("/<int:metric_id>")
@operator_required
def delete_metric(metric_id: int):
    metric = MetricDef.query.get(metric_id)
    if metric is None:
        return fail("指标不存在", CODE_NOT_FOUND, 404)
    if metric.is_system:
        return fail("系统内置指标不支持删除", 400)
    used = Telemetry.query.filter_by(metric_key=metric.metric_key).count()
    if used:
        return fail(f"该指标已有 {used} 条历史数据，建议停用而非删除", CODE_CONFLICT)
    db.session.delete(metric)
    db.session.commit()
    return ok(message="指标已删除")
