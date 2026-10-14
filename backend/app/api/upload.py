"""媒体文件上传接口（节点 Agent 调用）。

两条通道
--------
1. **分片上传**（推荐，用于视频与大图）：
   ``init`` -> ``chunk`` x N -> ``complete``；支持断点续传（init 返回已收到的分片序号）
   与秒传（sha256 命中已有文件时直接复用，不重复占用磁盘）。
2. **直传**（小图快捷通道）：``direct`` 一次性 multipart 提交。

上传完成后统一由 :func:`_finalize_media` 落库、生成缩略图、探测视频元信息，
并通过 SSE 通知 Web 控制台实时刷新媒体库。
"""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, g, request

from ..extensions import db
from ..models import (FILE_IMAGE, MediaFile, Node, UploadSession, utcnow)
from ..services import events, storage
from ..utils.auth import device_auth_required
from ..utils.request_ctx import json_body
from ..utils.response import (CODE_NOT_FOUND, fail, ok, parse_int)

bp = Blueprint("upload", __name__)

UPLOAD_ROOT_NAME = "temp"
# 业务码：分片未传完，需要继续上传
CODE_NEED_MORE_CHUNKS = 1001


def _parse_captured(value) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None)
    text = str(value).replace("Z", "").replace("+00:00", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def _session_dir(upload_id: str) -> Path:
    path = storage.storage_root() / UPLOAD_ROOT_NAME / upload_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _received_indexes(session: UploadSession) -> list[int]:
    folder = _session_dir(session.upload_id)
    indexes = []
    for item in folder.glob("chunk_*.part"):
        try:
            indexes.append(int(item.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(indexes)


# --------------------------------------------------------------------------- #
# 1. 初始化
# --------------------------------------------------------------------------- #
@bp.post("/init")
@device_auth_required
def init_upload():
    node: Node = g.node
    payload = json_body()
    file_name = str(payload.get("file_name", "")).strip()
    if not file_name:
        return fail("缺少 file_name", 400)

    file_type = storage.classify_file_type(file_name, str(payload.get("file_type", "")))
    file_size = parse_int(payload.get("file_size"), 0)
    sha256 = str(payload.get("sha256", "")).strip().lower()
    captured_at = _parse_captured(payload.get("captured_at"))

    # ---- 秒传：内容指纹已存在则直接复用物理文件 ----
    if sha256:
        existing = (MediaFile.query.filter_by(sha256=sha256, status="ready")
                    .order_by(MediaFile.id.asc()).first())
        if existing is not None and Path(storage.absolute_path(existing.storage_path)).exists():
            media = MediaFile(
                node_id=node.id, file_type=existing.file_type, file_name=file_name,
                storage_type=existing.storage_type, storage_path=existing.storage_path,
                thumb_path=existing.thumb_path, file_size=existing.file_size,
                mime_type=existing.mime_type, sha256=sha256,
                width=existing.width, height=existing.height,
                duration_sec=existing.duration_sec, captured_at=captured_at or utcnow(),
                source=str(payload.get("source", "camera")),
                tags=payload.get("tags") or [],
                meta={"dedup": True, "ref_media_id": existing.id},
                status="ready",
            )
            db.session.add(media)
            db.session.commit()
            events.publish("media", {"action": "created", "media": media.to_dict(
                {"node_name": node.name, "node_uid": node.node_uid})})
            return ok({"skip": True, "media_id": media.id, "sha256": sha256,
                       "message": "命中秒传，已直接入库"}, "秒传成功")

    # ---- 断点续传：同节点同文件名同大小且未过期的会话直接复用 ----
    reuse = (UploadSession.query
             .filter_by(node_id=node.id, file_name=file_name, file_size=file_size)
             .filter(UploadSession.status.in_(["init", "uploading"]))
             .filter(UploadSession.expires_at > utcnow())
             .order_by(UploadSession.id.desc()).first())

    if reuse is not None:
        session = reuse
        received = _received_indexes(session)
    else:
        chunk_size = parse_int(payload.get("chunk_size"),
                               current_app.config["LARGE_CHUNK_SIZE"]
                               if file_type == "video" else current_app.config["CHUNK_SIZE"])
        chunk_size = max(256 * 1024, min(chunk_size, 32 * 1024 * 1024))
        total_chunks = max(1, (file_size + chunk_size - 1) // chunk_size) if file_size else 1
        upload_id = f"up_{uuid.uuid4().hex[:20]}"
        session = UploadSession(
            upload_id=upload_id, node_id=node.id, file_name=file_name,
            file_type=file_type, file_size=file_size, chunk_size=chunk_size,
            total_chunks=total_chunks, sha256=sha256,
            temp_dir=str(Path(UPLOAD_ROOT_NAME) / upload_id),
            status="uploading", captured_at=captured_at,
            expires_at=utcnow() + timedelta(seconds=current_app.config["UPLOAD_SESSION_TTL"]),
        )
        db.session.add(session)
        db.session.commit()
        _session_dir(upload_id)
        received = []

    return ok({
        "upload_id": session.upload_id,
        "chunk_size": session.chunk_size,
        "total_chunks": session.total_chunks,
        "received_chunks": received,
        "uploaded_count": len(received),
        "file_type": session.file_type,
        "resumed": bool(received),
        "expires_at": session.expires_at.isoformat() + "Z" if session.expires_at else None,
    }, "上传会话已就绪")


# --------------------------------------------------------------------------- #
# 2. 上传分片
# --------------------------------------------------------------------------- #
@bp.post("/chunk")
@device_auth_required
def upload_chunk():
    node: Node = g.node
    upload_id = request.form.get("upload_id") or request.args.get("upload_id", "")
    index = parse_int(request.form.get("index") or request.args.get("index"), -1)
    if not upload_id or index < 0:
        return fail("缺少 upload_id 或 index", 400)
    session = UploadSession.query.filter_by(upload_id=upload_id, node_id=node.id).first()
    if session is None:
        return fail("上传会话不存在", CODE_NOT_FOUND, 404)
    if index >= session.total_chunks:
        return fail(f"分片序号越界（共 {session.total_chunks} 片）", 400)

    blob = request.files.get("chunk") or request.files.get("file")
    if blob is None:
        return fail("缺少分片数据（字段名 chunk）", 400)

    target = _session_dir(upload_id) / f"chunk_{index:06d}.part"
    blob.save(target)

    received = _received_indexes(session)
    session.received_chunks = len(received)
    session.status = "uploading"
    db.session.commit()

    return ok({"upload_id": upload_id, "index": index, "size": target.stat().st_size,
               "received_chunks": len(received), "total_chunks": session.total_chunks,
               "progress": round(len(received) / max(session.total_chunks, 1) * 100, 1)},
              f"分片 {index} 已接收")


# --------------------------------------------------------------------------- #
# 3. 完成 / 取消 / 查询
# --------------------------------------------------------------------------- #
def _finalize_media(session: UploadSession, merged: Path, node: Node,
                    payload: dict) -> MediaFile:
    """合并后的收尾工作：指纹、缩略图、元信息、入库。"""
    relative = storage.build_relative_path(node.node_uid, session.file_type,
                                           session.file_name, session.captured_at)
    final_path = storage.absolute_path(relative)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        final_path.unlink()
    shutil.move(str(merged), str(final_path))

    digest = session.sha256 or storage.sha256_of(final_path)
    size = final_path.stat().st_size
    thumb_rel, width, height = "", 0, 0
    duration, meta = 0.0, {}

    if session.file_type == FILE_IMAGE:
        thumb_rel, width, height = storage.make_thumbnail(final_path, relative)
    elif session.file_type == "video":
        duration, meta = storage.probe_video(final_path)
        width = meta.get("width", 0)
        height = meta.get("height", 0)
        thumb_rel = ""   # 视频封面由前端按首帧渲染，或后续接入 FFmpeg 抽帧

    media = MediaFile(
        node_id=node.id, file_type=session.file_type, file_name=session.file_name,
        storage_type="local", storage_path=relative, thumb_path=thumb_rel,
        file_size=size, mime_type=(payload.get("mime_type") or _guess_mime(session.file_name)),
        sha256=digest, width=int(width or 0), height=int(height or 0),
        duration_sec=_as_float(payload.get("duration_sec")) or float(duration or 0),
        captured_at=session.captured_at or utcnow(),
        source=str(payload.get("source", "camera")), tags=payload.get("tags") or [],
        meta={k: v for k, v in meta.items() if v not in ("", None)},
        status="ready", remark=str(payload.get("remark", "")),
    )
    db.session.add(media)
    session.status = "done"
    session.media_file_id = 0
    db.session.flush()
    session.media_file_id = media.id
    db.session.commit()

    events.publish("media", {"action": "created", "media": media.to_dict(
        {"node_name": node.name, "node_uid": node.node_uid})})

    # 清理分片临时目录
    try:
        shutil.rmtree(_session_dir(session.upload_id), ignore_errors=True)
    except Exception:  # pragma: no cover
        pass
    return media


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _guess_mime(file_name: str) -> str:
    import mimetypes
    return mimetypes.guess_type(file_name)[0] or "application/octet-stream"


@bp.post("/complete")
@device_auth_required
def complete_upload():
    node: Node = g.node
    payload = json_body()
    upload_id = str(payload.get("upload_id") or request.args.get("upload_id", ""))
    session = UploadSession.query.filter_by(upload_id=upload_id, node_id=node.id).first()
    if session is None:
        return fail("上传会话不存在", CODE_NOT_FOUND, 404)

    folder = _session_dir(upload_id)
    received = _received_indexes(session)
    missing = [i for i in range(session.total_chunks) if i not in received]
    if missing:
        return ok({"need_chunks": missing[:50], "received": len(received),
                   "total": session.total_chunks},
                  f"仍有 {len(missing)} 个分片未上传", code=CODE_NEED_MORE_CHUNKS)

    # 顺序合并
    session.status = "merging"
    db.session.commit()
    merged = folder / f"merged{Path(session.file_name).suffix}"
    with open(merged, "wb") as out:
        for index in range(session.total_chunks):
            part = folder / f"chunk_{index:06d}.part"
            if not part.exists():
                session.status = "failed"
                session.error_msg = f"分片 {index} 丢失"
                db.session.commit()
                return fail(f"分片 {index} 丢失，请重新初始化上传", 400)
            with open(part, "rb") as fp:
                shutil.copyfileobj(fp, out, 1024 * 1024)

    try:
        media = _finalize_media(session, merged, node, payload)
    except Exception as exc:  # pragma: no cover
        session.status = "failed"
        session.error_msg = str(exc)[:500]
        db.session.commit()
        return fail(f"文件入库失败：{exc}", 500)

    return ok(media.to_dict({"node_uid": node.node_uid, "node_name": node.name}),
              "文件上传完成")


@bp.post("/abort")
@device_auth_required
def abort_upload():
    node: Node = g.node
    payload = json_body()
    upload_id = str(payload.get("upload_id", ""))
    session = UploadSession.query.filter_by(upload_id=upload_id, node_id=node.id).first()
    if session is None:
        return fail("上传会话不存在", CODE_NOT_FOUND, 404)
    shutil.rmtree(_session_dir(upload_id), ignore_errors=True)
    session.status = "aborted"
    db.session.commit()
    return ok({"upload_id": upload_id}, "上传已取消")


@bp.get("/status/<upload_id>")
@device_auth_required
def upload_status(upload_id: str):
    node: Node = g.node
    session = UploadSession.query.filter_by(upload_id=upload_id, node_id=node.id).first()
    if session is None:
        return fail("上传会话不存在", CODE_NOT_FOUND, 404)
    received = _received_indexes(session)
    return ok({
        "upload_id": upload_id, "status": session.status,
        "received_chunks": received, "total_chunks": session.total_chunks,
        "progress": round(len(received) / max(session.total_chunks, 1) * 100, 1),
        "media_file_id": session.media_file_id,
    })


# --------------------------------------------------------------------------- #
# 4. 小文件直传
# --------------------------------------------------------------------------- #
@bp.post("/direct")
@device_auth_required
def direct_upload():
    """图片等小文件一次性上传（multipart/form-data，字段名 file）。"""
    node: Node = g.node
    blob = request.files.get("file")
    if blob is None:
        return fail("缺少文件字段 file", 400)
    file_name = blob.filename or "unnamed.jpg"
    file_type = storage.classify_file_type(file_name, request.form.get("file_type", ""))

    temp_dir = _session_dir(f"direct_{uuid.uuid4().hex[:12]}")
    staged = temp_dir / file_name
    blob.save(staged)

    relative = storage.build_relative_path(node.node_uid, file_type, file_name,
                                           _parse_captured(request.form.get("captured_at")))
    final_path = storage.absolute_path(relative)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(final_path))

    digest = storage.sha256_of(final_path)
    thumb_rel, width, height = ("", 0, 0)
    duration, meta = 0.0, {}
    if file_type == FILE_IMAGE:
        thumb_rel, width, height = storage.make_thumbnail(final_path, relative)
    elif file_type == "video":
        duration, meta = storage.probe_video(final_path)

    media = MediaFile(
        node_id=node.id, file_type=file_type, file_name=file_name, storage_type="local",
        storage_path=relative, thumb_path=thumb_rel, file_size=final_path.stat().st_size,
        mime_type=blob.mimetype or _guess_mime(file_name), sha256=digest,
        width=int(width or meta.get("width") or 0), height=int(height or meta.get("height") or 0),
        duration_sec=_as_float(request.form.get("duration_sec")) or float(duration or 0),
        captured_at=_parse_captured(request.form.get("captured_at")) or utcnow(),
        source=request.form.get("source", "camera"),
        tags=(request.form.get("tags") or "").split(",") if request.form.get("tags") else [],
        meta=meta, status="ready",
    )
    db.session.add(media)
    db.session.commit()
    shutil.rmtree(temp_dir, ignore_errors=True)

    events.publish("media", {"action": "created", "media": media.to_dict(
        {"node_name": node.name, "node_uid": node.node_uid})})
    return ok(media.to_dict({"node_uid": node.node_uid, "node_name": node.name}), "上传成功")


@bp.get("/sessions")
@device_auth_required
def list_sessions():
    """查询本节点未完成的上传会话，用于断网恢复后续传。"""
    node: Node = g.node
    rows = (UploadSession.query
            .filter_by(node_id=node.id)
            .filter(UploadSession.status.in_(["init", "uploading", "failed"]))
            .order_by(UploadSession.id.desc()).limit(50).all())
    return ok([r.to_dict({"received_chunks_list": _received_indexes(r)}) for r in rows])
