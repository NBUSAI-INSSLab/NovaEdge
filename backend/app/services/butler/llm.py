"""大模型客户端：OpenAI 兼容接口（DeepSeek / 通义 / Kimi / Ollama 等均可）。

配置存于 SysConfig（cfg_key = butler_llm）：
    {enabled, base_url, api_key, model, temperature}
未配置或调用失败时，上层引擎自动降级为内置规则引擎。
"""

from __future__ import annotations

import json

import requests

from ...extensions import db
from ...models import SysConfig

CFG_KEY = "butler_llm"
DEFAULT_TIMEOUT = 60


def get_config(mask_key: bool = False) -> dict:
    row = SysConfig.query.filter_by(cfg_key=CFG_KEY).first()
    cfg = dict(row.cfg_value or {}) if row else {}
    cfg.setdefault("enabled", False)
    cfg.setdefault("base_url", "")
    cfg.setdefault("api_key", "")
    cfg.setdefault("model", "")
    cfg.setdefault("temperature", 0.4)
    if mask_key and cfg["api_key"]:
        key = cfg["api_key"]
        cfg["api_key"] = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
        cfg["api_key_set"] = True
    else:
        cfg["api_key_set"] = bool(cfg["api_key"])
        if mask_key:
            cfg["api_key"] = ""
    return cfg


def save_config(enabled: bool, base_url: str, api_key: str | None, model: str,
                temperature: float = 0.4) -> None:
    row = SysConfig.query.filter_by(cfg_key=CFG_KEY).first()
    if row is None:
        row = SysConfig(cfg_key=CFG_KEY, category="butler", description="智能管家大模型配置")
        db.session.add(row)
    old = dict(row.cfg_value or {})
    new_key = old.get("api_key", "")
    if api_key:  # 传空串表示不修改
        new_key = api_key
    row.cfg_value = {
        "enabled": bool(enabled), "base_url": (base_url or "").rstrip("/"),
        "api_key": new_key, "model": model or "", "temperature": float(temperature),
    }
    db.session.commit()


def is_enabled() -> bool:
    cfg = get_config()
    return bool(cfg["enabled"] and cfg["base_url"] and cfg["api_key"] and cfg["model"])


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """调用 chat/completions。返回 assistant message dict；失败抛异常。"""
    cfg = get_config()
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.4)),
    }
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]
    resp = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        json=payload, timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]


def chat_text(system: str, user: str, max_tokens: int = 3000) -> str:
    """无工具的纯文本调用（报告润色等）。"""
    msg = chat([{"role": "system", "content": system},
                {"role": "user", "content": user}])
    return msg.get("content") or ""


def test_connection() -> dict:
    """连通性测试：发送一句问候，返回模型响应摘要。"""
    try:
        text = chat_text("你是平台助手，用一句中文回应。", "收到请回复：连接成功")
        return {"ok": True, "reply": text.strip()[:120]}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "请求超时（60 秒）"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "无法连接到 base_url，请检查地址"}
    except requests.exceptions.HTTPError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = exc.response.text[:200] if exc.response is not None else ""
        return {"ok": False, "error": f"HTTP {exc.response.status_code if exc.response is not None else '?'}: {detail}"}
    except (KeyError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"响应格式异常: {exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
