"""智能管家：会话对话、分析报告、大模型配置。"""

from __future__ import annotations

import io

from flask import Blueprint, Response, request, send_file

from ..extensions import db
from ..models import ButlerMessage, ButlerReport, utcnow
from ..services.butler import engine as butler_engine
from ..services.butler import llm, report as report_service, tools as butler_tools
from ..utils.jwt_helper import current_user, flexible_login_required, login_required, operator_required
from ..utils.response import CODE_NOT_FOUND, fail, get_page_args, ok, parse_int

bp = Blueprint("butler", __name__)


# --------------------------------------------------------------------------
# 会话
# --------------------------------------------------------------------------

@bp.post("/chat")
@login_required
def chat():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    session_id = (body.get("session_id") or "").strip()
    if not message:
        return fail("消息不能为空", 400)
    if not session_id:
        return fail("缺少 session_id", 400)
    if len(message) > 2000:
        return fail("消息过长（上限 2000 字）", 400)
    result = butler_engine.run(session_id, message, current_user())
    return ok(result)


@bp.get("/messages")
@login_required
def messages():
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return fail("缺少 session_id", 400)
    limit = min(parse_int(request.args.get("limit"), 50) or 50, 200)
    rows = (ButlerMessage.query.filter_by(session_id=session_id)
            .order_by(ButlerMessage.id.desc()).limit(limit).all())
    return ok({"items": [m.to_dict() for m in reversed(rows)]})


@bp.get("/sessions")
@login_required
def sessions():
    """最近会话列表（按最后消息时间倒序）。"""
    rows = (db.session.query(ButlerMessage.session_id,
                             db.func.max(ButlerMessage.id).label("last_id"))
            .group_by(ButlerMessage.session_id)
            .order_by(db.func.max(ButlerMessage.id).desc()).limit(20).all())
    items = []
    for session_id, last_id in rows:
        last = db.session.get(ButlerMessage, last_id)
        first_user = (ButlerMessage.query.filter_by(session_id=session_id, role="user")
                      .order_by(ButlerMessage.id.asc()).first())
        items.append({
            "session_id": session_id,
            "title": (first_user.content[:30] if first_user else session_id),
            "last_time": last.created_at.isoformat() + "Z" if last else None,
        })
    return ok({"items": items})


# --------------------------------------------------------------------------
# 分析报告
# --------------------------------------------------------------------------

@bp.post("/reports/generate")
@operator_required
def generate_report():
    body = request.get_json(silent=True) or {}
    report_type = body.get("report_type") or "on_demand"
    if report_type not in ("daily", "weekly", "on_demand"):
        return fail("report_type 仅支持 daily / weekly / on_demand", 400)
    hours = min(max(parse_int(body.get("hours"), 24) or 24, 1), 24 * 30)
    report = report_service.generate_report(
        report_type=report_type, title=(body.get("title") or "").strip(),
        created_by=current_user().username, hours=hours)
    return ok(report.to_dict(with_content=True), "报告生成完成")


@bp.get("/reports")
@login_required
def list_reports():
    page, page_size = get_page_args()
    q = ButlerReport.query.order_by(ButlerReport.id.desc())
    pagination = q.paginate(page=page, per_page=page_size, error_out=False)
    return ok({
        "items": [r.to_dict() for r in pagination.items],
        "total": pagination.total,
        "page": page,
        "page_size": page_size,
        "pages": pagination.pages,
    })


@bp.get("/reports/<int:report_id>")
@login_required
def get_report(report_id: int):
    report = db.session.get(ButlerReport, report_id)
    if report is None:
        return fail("报告不存在", CODE_NOT_FOUND, 404)
    return ok(report.to_dict(with_content=True))


@bp.delete("/reports/<int:report_id>")
@operator_required
def delete_report(report_id: int):
    report = db.session.get(ButlerReport, report_id)
    if report is None:
        return fail("报告不存在", CODE_NOT_FOUND, 404)
    db.session.delete(report)
    db.session.commit()
    return ok(None, "报告已删除")


@bp.get("/reports/<int:report_id>/download")
@flexible_login_required
def download_report(report_id: int):
    report = db.session.get(ButlerReport, report_id)
    if report is None:
        return fail("报告不存在", CODE_NOT_FOUND, 404)
    buf = io.BytesIO(report.content_md.encode("utf-8"))
    filename = f"NovaEdge_report_{report.id}.md"
    return send_file(buf, mimetype="text/markdown", as_attachment=True,
                     download_name=filename)


# --------------------------------------------------------------------------
# 大模型配置
# --------------------------------------------------------------------------

@bp.get("/config")
@login_required
def get_config():
    cfg = llm.get_config(mask_key=True)
    return ok(cfg)


@bp.put("/config")
@operator_required
def save_config():
    body = request.get_json(silent=True) or {}
    base_url = (body.get("base_url") or "").strip()
    model = (body.get("model") or "").strip()
    enabled = bool(body.get("enabled"))
    api_key = (body.get("api_key") or "").strip()  # 空串 = 不修改
    temperature = body.get("temperature", 0.4)
    try:
        temperature = min(max(float(temperature), 0.0), 2.0)
    except (TypeError, ValueError):
        temperature = 0.4
    if enabled and not (base_url and model):
        return fail("启用前请填写 base_url 与模型名称", 400)
    llm.save_config(enabled, base_url, api_key, model, temperature)
    from ..models import AuditLog
    db.session.add(AuditLog(user_id=current_user().id, username=current_user().username,
                            action="butler.save_config", target_type="sys_config",
                            target_id="butler_llm",
                            detail={"enabled": enabled, "base_url": base_url, "model": model},
                            ip=request.remote_addr or "", created_at=utcnow()))
    db.session.commit()
    return ok(llm.get_config(mask_key=True), "配置已保存")


@bp.post("/config/test")
@operator_required
def test_config():
    return ok(llm.test_connection())


@bp.get("/tools")
@login_required
def list_tools():
    """工具清单（供前端展示智能体能力）。"""
    write = butler_tools.WRITE_TOOLS
    items = [{"name": t["name"], "description": t["description"],
              "kind": "write" if t["name"] in write else "read"}
             for t in butler_tools.all_tools()]
    return ok({"items": items, "llm_enabled": llm.is_enabled()})
