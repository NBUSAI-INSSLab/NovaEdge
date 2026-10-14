"""实时事件推送（SSE）。

为什么选 SSE 而不是 WebSocket
------------------------------
控制台只需要「服务端 -> 浏览器」单向推送（节点在线、遥测、告警、媒体上传完成），
下行操作全部走 REST + JWT。SSE 基于普通 HTTP、天然支持断线重连（EventSource 自动重连），
浏览器/代理兼容性好，服务端实现只需一个生成器，无需引入 Socket.IO 或额外中间件。

鉴权：``EventSource`` 无法自定义请求头，因此 JWT 通过 ``?token=`` 查询参数传入，
服务端在建立连接前完成一次校验（连接建立后不再重复校验）。
"""

from __future__ import annotations

import queue
import time

from flask import Blueprint, Response, request, stream_with_context
from flask_jwt_extended import decode_token

from ..models import User
from ..services.events import bus
from ..utils.response import CODE_UNAUTHORIZED, fail, ok

bp = Blueprint("stream", __name__)

HEARTBEAT_INTERVAL = 20       # 秒，期间无事件则发送注释帧保持连接
MAX_CONNECTION_SECONDS = 60 * 60


@bp.get("/events")
def events_stream():
    token = request.args.get("token", "")
    if not token:
        return fail("缺少访问令牌", CODE_UNAUTHORIZED, 401)
    try:
        claims = decode_token(token)
    except Exception:
        return fail("访问令牌无效或已过期", CODE_UNAUTHORIZED, 401)

    user = User.query.get(int(claims.get("sub", 0)))
    if user is None or not user.is_active:
        return fail("账号不存在或已禁用", CODE_UNAUTHORIZED, 401)

    def generate():
        channel = bus.subscribe()
        started = time.time()
        try:
            yield "retry: 5000\n\n"
            yield bus.encode("connected", {"message": "实时通道已建立",
                                           "user": user.username})
            while True:
                if time.time() - started > MAX_CONNECTION_SECONDS:
                    yield bus.encode("reconnect", {"message": "连接已达上限，请重连"})
                    break
                try:
                    payload = channel.get(timeout=HEARTBEAT_INTERVAL)
                    yield bus.encode(payload["event"], payload["data"])
                except queue.Empty:
                    yield f": keep-alive {int(time.time())}\n\n"
        finally:
            bus.unsubscribe(channel)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"     # 关闭 Nginx 缓冲，保证实时性
    return response


@bp.get("/status")
def stream_status():
    return ok({"subscribers": bus.subscriber_count()})
