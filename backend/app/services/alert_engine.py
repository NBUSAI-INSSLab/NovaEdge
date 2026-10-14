"""告警引擎：阈值规则评估 + 告警生命周期管理。

规则匹配顺序
------------
1. 精确匹配节点（``node_id``）
2. 匹配节点所属分组（``group_id``）
3. 全局规则（``node_id=0 且 group_id=0``）

判定语义
--------
* ``duration_sec``：要求条件**连续满足**该秒数才产生告警。判定基于
  **数据本身的时间戳**（而非服务端处理时刻），因此无论节点是实时上报、
  还是断网后批量补传历史数据，告警判定结论都一致。
* ``silence_sec``：同一规则、同一节点的静默期，期内只累加 ``count``，
  不重复产生新记录，避免抖动刷屏。
* 条件不再满足时，自动把该节点该指标上的活动告警置为 ``cleared``。

状态缓存
--------
持续计时（``_first_hit``）与静默计时（``_last_fire``）保存在进程内存中，
属于「短窗口判定」状态，重启后从头计时即可，无需持久化。
单实例足够；多实例部署时可将其迁移到 Redis 以保证判定一致性。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from ..extensions import db
from ..models import (ALERT_ACKED, ALERT_ACTIVE, ALERT_CLEARED, AlertRecord,
                      AlertRule, Node, utcnow)
from . import events

_lock = threading.Lock()
_first_hit: dict[tuple[int, int], int] = {}    # (rule_id, node_id) -> 首次命中时间戳(ms)
_last_fire: dict[tuple[int, int], int] = {}    # (rule_id, node_id) -> 上次产生告警的时间戳(ms)


def _ms_to_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).replace(tzinfo=None)


def _compare(operator: str, value: float, threshold: float | None,
             threshold2: float | None = None) -> bool:
    if threshold is None:
        return False
    if operator == "gt":
        return value > threshold
    if operator == "ge":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "le":
        return value <= threshold
    if operator == "eq":
        return abs(value - threshold) < 1e-9
    if operator == "ne":
        return abs(value - threshold) >= 1e-9
    if operator == "out_of_range":
        upper = threshold2 if threshold2 is not None else threshold
        return value < min(threshold, upper) or value > max(threshold, upper)
    return False


def _matching_rules(node: Node, metric_key: str) -> list[AlertRule]:
    """取该节点该指标适用的全部启用规则。"""
    query = AlertRule.query.filter(AlertRule.enabled.is_(True),
                                   AlertRule.metric_key == metric_key)
    if node.group_id:
        query = query.filter(db.or_(
            AlertRule.node_id == node.id,
            AlertRule.group_id == node.group_id,
            (AlertRule.node_id == 0) & (AlertRule.group_id == 0),
        ))
    else:
        query = query.filter(db.or_(AlertRule.node_id == node.id,
                                    (AlertRule.node_id == 0) & (AlertRule.group_id == 0)))
    return query.all()


def _active_alert(node_id: int, metric_key: str) -> AlertRecord | None:
    return (AlertRecord.query
            .filter(AlertRecord.node_id == node_id, AlertRecord.metric_key == metric_key,
                    AlertRecord.status.in_([ALERT_ACTIVE, ALERT_ACKED]))
            .order_by(AlertRecord.started_at.desc()).first())


def evaluate_series(node: Node, series: dict[str, list[dict]]) -> list[dict]:
    """按时间序评估一个或多个指标的数据点。

    :param series: ``{metric_key: [{"ts": ms, "value": float}, ...]}``
    :return: 本次触发的告警摘要列表
    """
    fired: list[dict] = []
    if not series:
        return fired

    for metric_key, points in series.items():
        if not points:
            continue
        rules = _matching_rules(node, metric_key)
        if not rules:
            continue

        ordered = sorted(points, key=lambda item: item["ts"])
        active = _active_alert(node.id, metric_key)     # 循环内维护，减少 DB 往返
        hit_any = False
        last_ts = ordered[-1]["ts"]
        last_value = float(ordered[-1]["value"])

        for point in ordered:
            ts = int(point["ts"])
            value = float(point["value"])
            hit_this_point = False

            for rule in rules:
                if not _compare(rule.operator, value, rule.threshold, rule.threshold2):
                    with _lock:
                        _first_hit.pop((rule.id, node.id), None)
                    continue

                hit_this_point = True
                key = (rule.id, node.id)
                with _lock:
                    first = _first_hit.setdefault(key, ts)
                if (ts - first) / 1000.0 < float(rule.duration_sec or 0):
                    continue        # 已命中但未达到持续时长，继续观察

                with _lock:
                    previous = _last_fire.get(key)
                in_silence = (previous is not None and
                              (ts - previous) / 1000.0 < float(rule.silence_sec or 0))

                if active is not None and active.rule_id == rule.id:
                    active.count = (active.count or 0) + 1
                    active.trigger_value = value
                    if not in_silence:
                        with _lock:
                            _last_fire[key] = ts
                    break
                if in_silence:
                    break

                record = AlertRecord(
                    rule_id=rule.id, node_id=node.id, metric_key=metric_key,
                    severity=rule.severity,
                    title=f"{node.name} · {rule.name}",
                    content=_describe(rule, metric_key, value),
                    trigger_value=value, status=ALERT_ACTIVE, count=1,
                    started_at=_ms_to_dt(ts), created_at=utcnow(),
                )
                db.session.add(record)
                rule.trigger_count = (rule.trigger_count or 0) + 1
                db.session.flush()
                active = record
                with _lock:
                    _last_fire[key] = ts
                fired.append({"id": record.id, "node_id": node.id, "node_name": node.name,
                              "metric_key": metric_key, "severity": rule.severity,
                              "title": record.title, "value": value})
                events.publish("alert", {"action": "created", "alert": record.to_dict(
                    {"node_name": node.name, "node_uid": node.node_uid})})
                break

            hit_any = hit_this_point

        # 序列末尾仍未命中条件 -> 自动恢复
        if not hit_any and active is not None:
            _auto_clear(active, node, last_value, _ms_to_dt(last_ts))

    db.session.commit()
    return fired


def _describe(rule: AlertRule, metric_key: str, value: float) -> str:
    unit = ""
    try:
        from ..models import MetricDef
        metric = MetricDef.query.filter_by(metric_key=metric_key).first()
        unit = metric.unit if metric else ""
    except Exception:  # pragma: no cover
        pass
    base = f"{metric_key} 当前值 {value}{unit}，{rule.operator_label} {rule.threshold}"
    if rule.threshold2 is not None:
        base += f"（区间上限 {rule.threshold2}）"
    if rule.duration_sec:
        base += f"，已持续超过 {rule.duration_sec} 秒"
    return base


def _auto_clear(record: AlertRecord, node: Node, value: float, when: datetime) -> None:
    record.status = ALERT_CLEARED
    record.cleared_at = when
    record.clear_value = value
    events.publish("alert", {"action": "cleared", "alert": record.to_dict(
        {"node_name": node.name, "node_uid": node.node_uid})})


def reset_runtime_state() -> None:
    """测试辅助：清空内存态的持续计时与静默计时。"""
    with _lock:
        _first_hit.clear()
        _last_fire.clear()


def auto_clear_stale(days: int = 3) -> int:
    """运维辅助：把长期无人处理且指标早已恢复的活动告警归档为已恢复。"""
    cutoff = utcnow() - timedelta(days=days)
    rows = (AlertRecord.query
            .filter(AlertRecord.status == ALERT_ACTIVE,
                    AlertRecord.started_at < cutoff).all())
    for record in rows:
        record.status = ALERT_CLEARED
        record.cleared_at = utcnow()
    if rows:
        db.session.commit()
    return len(rows)
