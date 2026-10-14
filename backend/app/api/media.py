"""媒体库接口（Web 控制台侧）：列表、预览、下载、删除、统计。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, request, send_file
from sqlalchemy import func, or_

from ..extensions import db
from ..models import (FILE_TYPE_LABELS, AuditLog, MediaFile, Node, UploadSession,
                      human_size, to_ts, utcnow)
from ..services import events, storage
from ..utils.jwt_helper import (current_user, flexible_login_required,
                                login_required, operator_required)
from ..utils.response import (CODE_NOT_FOUND, fail, get_page_args, ok,
                              paginated, parse_int)

bp = Blueprint("media", __name__)


@bp.get("")
@login_required
def list_media():
    page, page_size = get_page_args(24)
    query = MediaFile.query.filter(MediaFile.status != "deleted")

    if request.args.get("node_id"):
        query = query.filter(MediaFile.node_id == parse_int(request.args["node_id"]))
    if request.args.get("file_type"):
        query = query.filter(MediaFile.file_type == request.args["file_type"])
    if request.args.get("source"):
        query = query.filter(MediaFile.source == request.args["source"])
    keyword = request.args.get("keyword", "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(MediaFile.file_name.like(like), MediaFile.remark.like(like)))
    if request.args.get("start"):
        try:
            start = datetime.strptime(request.args["start"], "%Y-%m-%d")
            query = query.filter(MediaFile.captured_at >= start)
        except ValueError:
            pass
    if request.args.get("end"):
        try:
            end = datetime.strptime(request.args["end"], "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(MediaFile.captured_at < end)
        except ValueError:
            pass

    order = MediaFile.captured_at.desc() if request.args.get("sort", "time") == "time" \
        else MediaFile.file_size.desc()
    total = query.count()
    rows = query.order_by(order, MediaFile.id.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()

    node_map = {n.id: n for n in Node.query.filter(
        Node.id.in_({r.node_id for r in rows} or {0})).all()}
    items = []
    for row in rows:
        node = node_map.get(row.node_id)
        items.append(row.to_dict({
            "node_name": node.name if node else "未知节点",
            "node_uid": node.node_uid if node else "",
            "captured_at_ts": to_ts(row.captured_at),
        }))
    return paginated(items, total, page, page_size)


@bp.get("/statistics")
@login_required
def media_statistics():
    base = MediaFile.query.filter(MediaFile.status != "deleted")
    total = base.count()
    images = base.filter(MediaFile.file_type == "image").count()
    videos = base.filter(MediaFile.file_type == "video").count()
    size_sum = db.session.query(func.coalesce(func.sum(MediaFile.file_size), 0)).filter(
        MediaFile.status != "deleted").scalar() or 0

    by_node = (db.session.query(MediaFile.node_id, func.count(MediaFile.id))
               .filter(MediaFile.status != "deleted")
               .group_by(MediaFile.node_id).order_by(func.count(MediaFile.id).desc())
               .limit(8).all())
    node_map = {n.id: n.name for n in Node.query.filter(
        Node.id.in_({nid for nid, _ in by_node} or {0})).all()}

    # 近 7 天新增
    daily = []
    for offset in range(6, -1, -1):
        day = (utcnow() - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        nxt = day + timedelta(days=1)
        count = base.filter(MediaFile.created_at >= day, MediaFile.created_at < nxt).count()
        daily.append({"date": day.strftime("%m-%d"), "count": count})

    return ok({
        "total": total, "images": images, "videos": videos,
        "storage_bytes": int(size_sum), "storage_human": human_size(int(size_sum)),
        "by_node": [{"node_id": nid, "node_name": node_map.get(nid, f"节点{nid}"), "count": c}
                    for nid, c in by_node],
        "daily": daily,
        "types": [{"value": k, "label": v} for k, v in FILE_TYPE_LABELS.items()],
    })


@bp.get("/<int:media_id>")
@login_required
def media_detail(media_id: int):
    media = MediaFile.query.get(media_id)
    if media is None or media.status == "deleted":
        return fail("媒体文件不存在", CODE_NOT_FOUND, 404)
    node = Node.query.get(media.node_id)
    return ok(media.to_dict({
        "node_name": node.name if node else "未知节点",
        "node_uid": node.node_uid if node else "",
        "storage_abs": str(storage.absolute_path(media.storage_path)),
    }))


@bp.get("/<int:media_id>/raw")
@flexible_login_required
def media_raw(media_id: int):
    """原始文件流。``conditional=True`` 使 Flask 自动响应 Range 请求，视频可拖动进度。"""
    media = MediaFile.query.get(media_id)
    if media is None or media.status == "deleted":
        return fail("媒体文件不存在", CODE_NOT_FOUND, 404)
    path = storage.absolute_path(media.storage_path)
    if not Path(path).exists():
        return fail("物理文件缺失，可能已被清理", CODE_NOT_FOUND, 404)
    return send_file(path, mimetype=media.mime_type or None,
                     as_attachment=False, conditional=True,
                     download_name=media.file_name)


@bp.get("/<int:media_id>/download")
@flexible_login_required
def media_download(media_id: int):
    media = MediaFile.query.get(media_id)
    if media is None or media.status == "deleted":
        return fail("媒体文件不存在", CODE_NOT_FOUND, 404)
    path = storage.absolute_path(media.storage_path)
    if not Path(path).exists():
        return fail("物理文件缺失", CODE_NOT_FOUND, 404)
    return send_file(path, as_attachment=True, download_name=media.file_name,
                     conditional=True)


@bp.get("/<int:media_id>/thumb")
@flexible_login_required
def media_thumb(media_id: int):
    media = MediaFile.query.get(media_id)
    if media is None:
        return fail("媒体文件不存在", CODE_NOT_FOUND, 404)
    if not media.thumb_path:
        path = storage.absolute_path(media.storage_path)
        if Path(path).exists():
            return send_file(path, conditional=True)
        return fail("缩略图不存在", CODE_NOT_FOUND, 404)
    path = storage.absolute_path(media.thumb_path)
    if not Path(path).exists():
        return fail("缩略图缺失", CODE_NOT_FOUND, 404)
    return send_file(path, mimetype="image/jpeg", conditional=True)


@bp.put("/<int:media_id>")
@operator_required
def update_media(media_id: int):
    media = MediaFile.query.get(media_id)
    if media is None:
        return fail("媒体文件不存在", CODE_NOT_FOUND, 404)
    payload = request.get_json(silent=True) or {}
    if "tags" in payload and isinstance(payload["tags"], list):
        media.tags = [str(t)[:32] for t in payload["tags"]][:20]
    if "remark" in payload:
        media.remark = str(payload["remark"])[:255]
    db.session.commit()
    return ok(media.to_dict(), "已更新")


@bp.delete("/<int:media_id>")
@operator_required
def delete_media(media_id: int):
    """逻辑删除 + 物理删除（同 sha256 被其他记录复用时不删物理文件）。"""
    media = MediaFile.query.get(media_id)
    if media is None:
        return fail("媒体文件不存在", CODE_NOT_FOUND, 404)
    reused = MediaFile.query.filter(MediaFile.sha256 == media.sha256,
                                    MediaFile.id != media.id,
                                    MediaFile.status != "deleted").count() if media.sha256 else 0
    if not reused:
        storage.delete_media_files(media.storage_path, media.thumb_path)
    media.status = "deleted"
    db.session.add(AuditLog(user_id=current_user().id, username=current_user().username,
                            action="delete_media", target_type="media",
                            target_id=str(media.id),
                            detail={"file_name": media.file_name}, created_at=utcnow()))
    db.session.commit()
    events.publish("media", {"action": "deleted", "media_id": media_id})
    return ok(message="媒体文件已删除")


@bp.post("/batch-delete")
@operator_required
def batch_delete():
    payload = request.get_json(silent=True) or {}
    ids = [parse_int(i, 0) for i in (payload.get("ids") or []) if parse_int(i, 0)]
    if not ids:
        return fail("请选择要删除的文件", 400)
    rows = MediaFile.query.filter(MediaFile.id.in_(ids)).all()
    deleted = 0
    for media in rows:
        reused = MediaFile.query.filter(MediaFile.sha256 == media.sha256,
                                        MediaFile.id != media.id,
                                        MediaFile.status != "deleted").count() if media.sha256 else 0
        if not reused:
            storage.delete_media_files(media.storage_path, media.thumb_path)
        media.status = "deleted"
        deleted += 1
    db.session.commit()
    events.publish("media", {"action": "deleted", "media_id": ids})
    return ok({"deleted": deleted}, f"已删除 {deleted} 个文件")


@bp.get("/uploads")
@login_required
def upload_sessions():
    """查看进行中/失败的上传会话，便于排查节点上传卡点。"""
    page, page_size = get_page_args(20)
    query = UploadSession.query
    if request.args.get("node_id"):
        query = query.filter(UploadSession.node_id == parse_int(request.args["node_id"]))
    if request.args.get("status"):
        query = query.filter(UploadSession.status == request.args["status"])
    total = query.count()
    rows = query.order_by(UploadSession.id.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()
    node_map = {n.id: n.name for n in Node.query.filter(
        Node.id.in_({r.node_id for r in rows} or {0})).all()}
    return paginated([r.to_dict({"node_name": node_map.get(r.node_id, "未知节点"),
                                 "progress": round(r.received_chunks /
                                                   max(r.total_chunks, 1) * 100, 1)})
                      for r in rows], total, page, page_size)
