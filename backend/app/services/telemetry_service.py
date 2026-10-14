"""遥测数据服务：写入、最新值维护、历史查询、小时聚合。

写入路径（HTTP / MQTT 共用）::

    接入层 -> ingest_telemetry()
              ├── 自动补全物模型 metric_def
              ├── 批量写 telemetry 明细
              ├── upsert telemetry_latest 快照
              └── 交给 alert_engine 做阈值评估、SSE 推送

所有写操作由调用方控制事务边界，便于批量上报时一次提交。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..extensions import db
from ..models import (MetricDef, Node, Telemetry, TelemetryHourly,
                      TelemetryLatest, utcnow)
from . import events

# 节点资源指标（心跳）不参与告警规则以外的物模型展示
SYSTEM_METRIC_KEYS = {"cpu_percent", "mem_percent", "disk_percent", "cpu_temp",
                      "net_rx_kbps", "net_tx_kbps", "uptime_seconds"}


def _coerce_value(value):
    """把上报值拆成 (数值, 字符串) 两种表示。"""
    if isinstance(value, bool):
        return (1.0 if value else 0.0), str(value).lower()
    if isinstance(value, (int, float)):
        return float(value), ""
    text = "" if value is None else str(value)
    try:
        return float(text), ""
    except (TypeError, ValueError):
        return None, text


def ensure_metric(metric_key: str, unit: str = "", name: str = "") -> MetricDef:
    """按需自动登记物模型指标，保证节点新增传感器时平台可自适应。"""
    metric = MetricDef.query.filter_by(metric_key=metric_key).first()
    if metric is not None:
        return metric
    metric = MetricDef(
        metric_key=metric_key,
        name=name or metric_key,
        unit=unit or "",
        category="system" if metric_key in SYSTEM_METRIC_KEYS else "custom",
        data_type="float",
        is_system=metric_key in SYSTEM_METRIC_KEYS,
        description="由节点上报自动登记",
    )
    db.session.add(metric)
    db.session.flush()
    return metric


def ingest_telemetry(node: Node, samples: list[dict], *, source: str = "http",
                     evaluate_alert: bool = True) -> dict:
    """批量写入遥测样本。

    :param samples: ``[{"metric": "temperature", "value": 24.6, "ts": 1730000000000,
                        "unit": "℃"}, ...]``
    :return: ``{"accepted": n, "latest": {...}, "rejected": [...]}``
    """
    now = utcnow()
    accepted = 0
    rejected: list[dict] = []
    latest_map: dict[str, dict] = {}
    series: dict[str, list[dict]] = {}      # 告警评估用：保留全部样本的时间序列
    rows: list[Telemetry] = []

    for sample in samples or []:
        metric_key = str(sample.get("metric") or sample.get("key") or "").strip()
        if not metric_key:
            rejected.append({"sample": sample, "reason": "缺少 metric 字段"})
            continue
        num, text = _coerce_value(sample.get("value"))
        if num is None and not text:
            rejected.append({"sample": sample, "reason": "value 为空"})
            continue
        ts = sample.get("ts")
        try:
            ts = int(ts) if ts is not None else int(now.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except (TypeError, ValueError):
            ts = int(now.replace(tzinfo=timezone.utc).timestamp() * 1000)

        ensure_metric(metric_key, unit=str(sample.get("unit") or ""),
                      name=str(sample.get("name") or ""))

        rows.append(Telemetry(
            node_id=node.id, metric_key=metric_key, value_num=num, value_str=text,
            ts=ts, quality=1, created_at=now,
        ))
        latest_map[metric_key] = {"metric": metric_key, "value_num": num,
                                  "value_str": text, "ts": ts}
        if num is not None and evaluate_alert:
            series.setdefault(metric_key, []).append({"ts": ts, "value": num})
        accepted += 1

    if rows:
        db.session.bulk_save_objects(rows)

    # upsert 最新值快照
    for metric_key, payload in latest_map.items():
        row = db.session.get(TelemetryLatest, (node.id, metric_key))
        if row is None:
            db.session.add(TelemetryLatest(
                node_id=node.id, metric_key=metric_key,
                value_num=payload["value_num"], value_str=payload["value_str"],
                ts=payload["ts"], updated_at=now,
            ))
        else:
            row.value_num = payload["value_num"]
            row.value_str = payload["value_str"]
            row.ts = payload["ts"]
            row.updated_at = now

    db.session.commit()

    if accepted:
        events.publish("telemetry", {
            "node_id": node.id,
            "node_uid": node.node_uid,
            "node_name": node.name,
            "source": source,
            "samples": latest_map,
            "count": accepted,
        })

    # 告警评估基于完整样本序列（而非仅最新值），
    # 使断网补传的历史数据同样能得到正确的「持续越限」判定。
    alerts = []
    if evaluate_alert and series:
        from .alert_engine import evaluate_series
        alerts = evaluate_series(node, series)

    return {"accepted": accepted, "rejected": rejected, "latest": latest_map,
            "alerts": alerts}


def latest_values(node_id: int, metric_keys: list[str] | None = None) -> list[dict]:
    query = TelemetryLatest.query.filter_by(node_id=node_id)
    if metric_keys:
        query = query.filter(TelemetryLatest.metric_key.in_(metric_keys))
    rows = query.all()
    defs = {m.metric_key: m for m in MetricDef.query.all()}
    result = []
    for row in rows:
        meta = defs.get(row.metric_key)
        result.append({
            "metric_key": row.metric_key,
            "name": meta.name if meta else row.metric_key,
            "unit": meta.unit if meta else "",
            "category": meta.category if meta else "custom",
            "value_num": row.value_num,
            "value_str": row.value_str,
            "ts": row.ts,
        })
    result.sort(key=lambda item: item["name"])
    return result


def history(node_id: int, metric_key: str, start_ts: int | None = None,
            end_ts: int | None = None, limit: int = 1000) -> list[dict]:
    """查询历史明细（升序返回，最多 limit 个点）。"""
    query = Telemetry.query.filter_by(node_id=node_id, metric_key=metric_key)
    end_ts = end_ts or int(utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000)
    start_ts = start_ts or (end_ts - 6 * 3600 * 1000)
    query = query.filter(Telemetry.ts >= start_ts, Telemetry.ts <= end_ts)
    rows = query.order_by(Telemetry.ts.desc()).limit(limit).all()
    rows.reverse()
    return [{"ts": r.ts, "value": r.value_num if r.value_num is not None else r.value_str}
            for r in rows]


def series_for_node(node_id: int, metric_keys: list[str], hours: int = 6,
                    limit_per_metric: int = 360) -> dict[str, list[dict]]:
    end_ts = int(utcnow().replace(tzinfo=timezone.utc).timestamp() * 1000)
    start_ts = end_ts - hours * 3600 * 1000
    data: dict[str, list[dict]] = {}
    for key in metric_keys:
        data[key] = history(node_id, key, start_ts, end_ts, limit_per_metric)
    return data


def footprint_stats(node_ids: list[int]) -> dict:
    """聚合统计：数据点总量、今日新增，用于总览看板。"""
    if not node_ids:
        return {"total_points": 0, "today_points": 0, "media_total": 0}
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ts = int(today_start.replace(tzinfo=timezone.utc).timestamp() * 1000)
    total = db.session.query(func.count(Telemetry.id)).filter(
        Telemetry.node_id.in_(node_ids)).scalar() or 0
    today = db.session.query(func.count(Telemetry.id)).filter(
        Telemetry.node_id.in_(node_ids), Telemetry.ts >= today_ts).scalar() or 0
    return {"total_points": int(total), "today_points": int(today)}


def rollup_hour(bucket_start: datetime | None = None) -> int:
    """把指定小时（默认上一小时）的明细聚合成一条 hourly 记录。"""
    bucket_start = bucket_start or (datetime.utcnow().replace(minute=0, second=0, microsecond=0)
                                    - timedelta(hours=1))
    start_ts = int(bucket_start.replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = start_ts + 3600 * 1000

    rows = (db.session.query(
                Telemetry.node_id, Telemetry.metric_key,
                func.avg(Telemetry.value_num), func.min(Telemetry.value_num),
                func.max(Telemetry.value_num), func.count(Telemetry.id))
            .filter(Telemetry.ts >= start_ts, Telemetry.ts < end_ts,
                    Telemetry.value_num.isnot(None))
            .group_by(Telemetry.node_id, Telemetry.metric_key).all())

    count = 0
    for node_id, metric_key, avg_v, min_v, max_v, samples in rows:
        existing = TelemetryHourly.query.filter_by(
            node_id=node_id, metric_key=metric_key, bucket_ts=start_ts).first()
        if existing is None:
            existing = TelemetryHourly(node_id=node_id, metric_key=metric_key, bucket_ts=start_ts)
            db.session.add(existing)
        existing.avg_value = round(float(avg_v or 0), 4)
        existing.min_value = round(float(min_v or 0), 4)
        existing.max_value = round(float(max_v or 0), 4)
        existing.sample_count = int(samples or 0)
        count += 1
    db.session.commit()
    return count
