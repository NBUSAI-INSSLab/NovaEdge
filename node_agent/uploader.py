"""媒体上传客户端：分片上传 + 断点续传 + 秒传。

流程
----
1. ``POST /api/v1/upload/init``    —— 上报文件名/大小/指纹，获取 upload_id 与已收到的分片
2. ``POST /api/v1/upload/chunk``   —— 循环提交分片（multipart）
3. ``POST /api/v1/upload/complete``—— 服务端合并、生成缩略图/探测视频、写入媒体库

小文件（< 1MB，通常为单帧图片）自动改走 ``POST /api/v1/upload/direct`` 一次提交，减少往返。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import Path

import requests

logger = logging.getLogger("agent.uploader")

DIRECT_THRESHOLD = 1 * 1024 * 1024
CODE_NEED_MORE_CHUNKS = 1001


def file_sha256(path: Path, block: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(block)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class Uploader:
    def __init__(self, base_url: str, headers: dict, timeout: int = 30,
                 chunk_size: int = 2 * 1024 * 1024,
                 large_chunk_size: int = 8 * 1024 * 1024,
                 session: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.large_chunk_size = large_chunk_size
        self.session = session or requests.Session()

    # ------------------------------------------------------------------ #
    def upload_file(self, path: Path, *, file_type: str = "", captured_at=None,
                    source: str = "camera", tags: list[str] | None = None,
                    extra: dict | None = None) -> dict | None:
        path = Path(path)
        if not path.exists() or path.stat().st_size == 0:
            return None
        size = path.stat().st_size
        if size <= DIRECT_THRESHOLD:
            result = self._direct(path, file_type, captured_at, source, tags, extra)
            if result is not None:
                return result
            logger.info("直传失败，回退分片上传：%s", path.name)

        chunk_size = self.large_chunk_size if (file_type == "video" or
                                               path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}) \
            else self.chunk_size
        try:
            init = self._init(path, file_type, size, chunk_size, captured_at, tags, extra)
        except requests.RequestException as exc:
            logger.warning("初始化上传失败：%s", exc)
            return None
        if init is None:
            return None
        if init.get("skip"):
            logger.info("秒传命中：%s -> media_id=%s", path.name, init.get("media_id"))
            return init

        upload_id = init["upload_id"]
        total = init["total_chunks"]
        received = set(init.get("received_chunks") or [])
        if received:
            logger.info("断点续传：%s 已有 %d/%d 片", path.name, len(received), total)

        with open(path, "rb") as fp:
            for index in range(total):
                if index in received:
                    continue
                fp.seek(index * init["chunk_size"])
                blob = fp.read(init["chunk_size"])
                try:
                    resp = self.session.post(
                        f"{self.base_url}/api/v1/upload/chunk",
                        headers=self.headers,
                        data={"upload_id": upload_id, "index": index},
                        files={"chunk": (f"chunk_{index}", blob, "application/octet-stream")},
                        timeout=self.timeout,
                    )
                    body = resp.json()
                except (requests.RequestException, ValueError) as exc:
                    logger.warning("分片 %d 上传失败：%s", index, exc)
                    return None
                if body.get("code") != 0:
                    logger.warning("分片 %d 被拒绝：%s", index, body.get("message"))
                    return None

        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/upload/complete", headers=self.headers,
                json={"upload_id": upload_id, "source": source, "tags": tags or [],
                      "captured_at": _iso(captured_at), **(extra or {})},
                timeout=max(self.timeout, 120),
            )
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("合并上传文件失败：%s", exc)
            return None

        if body.get("code") == CODE_NEED_MORE_CHUNKS:
            logger.warning("服务端仍缺少分片，本轮放弃，下轮续传：%s", body.get("data"))
            return None
        if body.get("code") != 0:
            logger.warning("文件入库失败：%s", body.get("message"))
            return None
        logger.info("媒体上传成功：%s -> media_id=%s", path.name, body["data"].get("id"))
        return body["data"]

    # ------------------------------------------------------------------ #
    def _direct(self, path: Path, file_type: str, captured_at, source: str,
                tags: list[str] | None, extra: dict | None = None) -> dict | None:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            with open(path, "rb") as fp:
                resp = self.session.post(
                    f"{self.base_url}/api/v1/upload/direct", headers=self.headers,
                    data={"file_type": file_type, "source": source,
                          "captured_at": _iso(captured_at),
                          "tags": ",".join(tags or []),
                          **{k: str(v) for k, v in (extra or {}).items()}},
                    files={"file": (path.name, fp, mime)},
                    timeout=max(self.timeout, 60),
                )
            body = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("直传失败：%s", exc)
            return None
        if body.get("code") != 0:
            return None
        logger.info("媒体直传成功：%s -> media_id=%s", path.name, body["data"].get("id"))
        return body["data"]

    def _init(self, path: Path, file_type: str, size: int, chunk_size: int,
              captured_at, tags: list[str] | None, extra: dict | None = None) -> dict | None:
        payload = {
            "file_name": path.name,
            "file_type": file_type,
            "file_size": size,
            "chunk_size": chunk_size,
            "sha256": file_sha256(path),
            "captured_at": _iso(captured_at),
            "tags": tags or [],
            **(extra or {}),
        }
        resp = self.session.post(f"{self.base_url}/api/v1/upload/init",
                                 headers=self.headers, json=payload,
                                 timeout=self.timeout)
        body = resp.json()
        if body.get("code") != 0:
            logger.warning("初始化上传被拒绝：%s", body.get("message"))
            return None
        return body["data"]


def _iso(value):
    if value is None:
        return None
    try:
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    except AttributeError:
        return str(value)
