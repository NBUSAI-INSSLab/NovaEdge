"""平台分析报告生成器：数据快照 → 启发式分析 → Markdown 报告（LLM 可润色）。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func

from ...extensions import db
from ...models import (AlertRecord, AlertRule, ButlerReport, Command, MediaFile,
                       Node, NodeGroup, Telemetry, TelemetryLatest, utcnow)


def _fmt_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def collect_snapshot(hours: int = 24) -> dict:
    """采集平台数据快照（供分析与 LLM 使用）。"""
    since = utcnow() - timedelta(hours=hours)

    nodes = Node.query.all()
    groups = {g.id: g.name for g in NodeGroup.query.all()}

    by_status: dict[str, int] = {}
    for n in nodes:
        by_status[n.status] = by_status.get(n.status, 0) + 1
    offline_nodes = [{"id": n.id, "name": n.name, "type": n.node_type,
                      "group": groups.get(n.group_id), "last_seen":
                      n.last_seen_at.isoformat(sep=" ") if n.last_seen_at else None}
                     for n in nodes if n.status != "online"]

    # 遥测：窗口内总量、按小时趋势、按节点 TOP
    tel_total = db.session.query(func.count(Telemetry.id)).filter(Telemetry.created_at >= since).scalar() or 0
    trend_rows = (db.session.query(func.strftime("%Y-%m-%d %H:00", Telemetry.created_at), func.count())
                  .filter(Telemetry.created_at >= since)
                  .group_by(func.strftime("%Y-%m-%d %H:00", Telemetry.created_at))
                  .order_by(func.strftime("%Y-%m-%d %H:00", Telemetry.created_at)).all())
    top_nodes = (db.session.query(Node.name, func.count(Telemetry.id).label("cnt"))
                 .join(Telemetry, Telemetry.node_id == Node.id)
                 .filter(Telemetry.created_at >= since)
                 .group_by(Node.name).order_by(func.count(Telemetry.id).desc()).limit(5).all())

    # 最新值分布（跨节点各指标 min/max/avg）
    latest = TelemetryLatest.query.all()
    metric_stats: dict[str, dict] = {}
    for m in latest:
        if m.value_num is None:
            continue
        s = metric_stats.setdefault(m.metric_key, {"values": [], "nodes": set()})
        s["values"].append(float(m.value_num))
        s["nodes"].add(m.node_id)
    metrics = []
    for key, s in sorted(metric_stats.items()):
        vals = s["values"]
        metrics.append({"metric_key": key, "node_count": len(s["nodes"]),
                        "min": round(min(vals), 3), "max": round(max(vals), 3),
                        "avg": round(sum(vals) / len(vals), 3) if vals else 0})

    # 告警
    alerts = (AlertRecord.query.filter(AlertRecord.started_at >= since)
              .order_by(AlertRecord.started_at.desc()).all())
    alert_by_sev: dict[str, int] = {}
    alert_by_status: dict[str, int] = {}
    for a in alerts:
        alert_by_sev[a.severity] = alert_by_sev.get(a.severity, 0) + 1
        alert_by_status[a.status] = alert_by_status.get(a.status, 0) + 1
    node_names = {n.id: n.name for n in Node.query.all()}
    active_alerts = [{"title": a.title, "severity": a.severity,
                      "node": node_names.get(a.node_id, f"#{a.node_id}"),
                      "started_at": a.started_at.isoformat(sep=" ")}
                     for a in alerts if a.status == "active"][:10]

    # 规则触发排行
    top_rules = (AlertRule.query.order_by(AlertRule.trigger_count.desc()).limit(5).all())
    rules_brief = [{"name": r.name, "metric_key": r.metric_key, "threshold": r.threshold,
                    "operator": r.operator, "enabled": r.enabled,
                    "trigger_count": r.trigger_count} for r in top_rules]

    # 媒体
    media_by_type = dict(db.session.query(MediaFile.file_type, func.count())
                         .group_by(MediaFile.file_type).all())
    media_size = dict(db.session.query(MediaFile.file_type,
                                       func.coalesce(func.sum(MediaFile.file_size), 0))
                      .group_by(MediaFile.file_type).all())
    media_recent = MediaFile.query.filter(MediaFile.created_at >= since).count()

    # 指令
    cmd_by_status = dict(db.session.query(Command.status, func.count())
                         .filter(Command.created_at >= since)
                         .group_by(Command.status).all())

    return {
        "hours": hours,
        "generated_at": utcnow().isoformat(sep=" ", timespec="seconds"),
        "nodes": {"total": len(nodes), "by_status": by_status, "offline": offline_nodes},
        "telemetry": {"window_points": tel_total,
                      "hourly_trend": [{"hour": h, "count": c} for h, c in trend_rows],
                      "top_nodes": [{"node": n, "points": c} for n, c in top_nodes],
                      "metrics": metrics},
        "alerts": {"window_total": len(alerts), "by_severity": alert_by_sev,
                   "by_status": alert_by_status, "active": active_alerts},
        "rules": rules_brief,
        "media": {"by_type": media_by_type, "size_bytes": {k: int(v) for k, v in media_size.items()},
                  "window_new": media_recent},
        "commands": {"by_status": cmd_by_status},
    }


def _analyze(snapshot: dict) -> list[str]:
    """启发式分析结论（无 LLM 也能给出有价值的洞察）。"""
    findings: list[str] = []
    nodes = snapshot["nodes"]
    total = max(nodes["total"], 1)
    online = nodes["by_status"].get("online", 0)
    rate = online / total * 100
    if rate >= 99:
        findings.append(f"节点在线率 {rate:.0f}%，全部节点运行正常。")
    else:
        names = "、".join(n["name"] for n in nodes["offline"][:5]) or "未知节点"
        findings.append(f"节点在线率 {rate:.0f}%，离线节点：{names}，建议检查其网络与电源状态。")

    metrics = {m["metric_key"]: m for m in snapshot["telemetry"]["metrics"]}
    temp = metrics.get("temperature")
    if temp and temp["max"] >= 45:
        findings.append(f"环境温度最高达 {temp['max']}℃，注意机房/设备散热。")
    cpu = metrics.get("cpu_percent")
    if cpu and cpu["max"] >= 90:
        findings.append(f"有节点 CPU 使用率峰值达 {cpu['max']}%，建议排查高负载进程。")
    mem = metrics.get("mem_percent")
    if mem and mem["max"] >= 85:
        findings.append(f"有节点内存使用率峰值达 {mem['max']}%，注意内存泄漏风险。")

    alerts = snapshot["alerts"]
    if alerts["window_total"] == 0:
        findings.append(f"最近 {snapshot['hours']} 小时无告警触发，系统运行平稳。")
    else:
        crit = alerts["by_severity"].get("critical", 0)
        if crit:
            findings.append(f"窗口内出现 {crit} 条严重告警，请优先处理。")
        act = len(alerts["active"])
        if act:
            findings.append(f"当前仍有 {act} 条告警未恢复，建议尽快确认。")

    tel = snapshot["telemetry"]
    if tel["hourly_trend"]:
        counts = [p["count"] for p in tel["hourly_trend"]]
        avg = sum(counts) / len(counts)
        if avg > 0:
            gaps = [p["hour"] for p in tel["hourly_trend"] if p["count"] < avg * 0.3]
            if gaps:
                findings.append(f"数据上报存在低谷时段（如 {gaps[0]}），可能存在节点断网补传或采集间隙。")

    storage = sum(snapshot["media"]["size_bytes"].values())
    if storage > 1024 ** 3:
        findings.append(f"媒体存储已达 {_fmt_size(storage)}，建议制定归档与生命周期策略。")
    return findings


def _builtin_markdown(snapshot: dict, title: str) -> tuple[str, str]:
    """模板化 Markdown 报告。返回 (正文, 一句话摘要)。"""
    h = snapshot["hours"]
    nodes = snapshot["nodes"]
    total = max(nodes["total"], 1)
    online = nodes["by_status"].get("online", 0)
    tel = snapshot["telemetry"]
    alerts = snapshot["alerts"]
    media = snapshot["media"]
    cmds = snapshot["commands"]

    findings = _analyze(snapshot)
    summary = (f"平台 {nodes['total']} 个节点在线率 "
               f"{online / total * 100:.0f}%；{h} 小时遥测 {tel['window_points']:,} 条、"
               f"告警 {alerts['window_total']} 条、新增媒体 {media['window_new']} 个。")

    L: list[str] = []
    L.append(f"# {title}\n")
    L.append(f"> 生成时间：{snapshot['generated_at']} · 统计窗口：最近 {h} 小时 · "
             f"生成引擎：内置分析引擎\n")

    L.append("## 一、平台概况\n")
    L.append(f"| 指标 | 数值 |\n| --- | --- |")
    L.append(f"| 接入节点 | {nodes['total']} 个（在线 {online}，离线 {nodes['by_status'].get('offline', 0)}） |")
    L.append(f"| 在线率 | **{online / total * 100:.1f}%** |")
    L.append(f"| 遥测数据点（窗口内） | {tel['window_points']:,} |")
    L.append(f"| 告警（窗口内） | {alerts['window_total']} 条（活动 {len(alerts['active'])}） |")
    L.append(f"| 数据资产 | 图片 {media['by_type'].get('image', 0)} / 视频 {media['by_type'].get('video', 0)}"
             f" / 其他 {media['by_type'].get('other', 0)}，共 {_fmt_size(sum(media['size_bytes'].values()))} |")
    L.append(f"| 指令（窗口内） | {sum(cmds['by_status'].values())} 条 |")
    L.append("")

    L.append("## 二、节点状态\n")
    if nodes["offline"]:
        L.append("| 离线节点 | 类型 | 分组 | 最近上线 |")
        L.append("| --- | --- | --- | --- |")
        for n in nodes["offline"]:
            L.append(f"| {n['name']} | {n['type']} | {n['group'] or '—'} | {n['last_seen'] or '—'} |")
    else:
        L.append("全部节点在线，无异常。")
    L.append("")

    L.append("## 三、数据采集分析\n")
    L.append(f"窗口内共入库 {tel['window_points']:,} 个遥测数据点。各指标最新值分布：\n")
    L.append("| 指标 | 节点数 | 最小值 | 最大值 | 平均值 |")
    L.append("| --- | --- | --- | --- | --- |")
    for m in tel["metrics"]:
        L.append(f"| {m['metric_key']} | {m['node_count']} | {m['min']} | {m['max']} | {m['avg']} |")
    L.append("")
    if tel["top_nodes"]:
        L.append("数据量 TOP5 节点：" + "、".join(
            f"{t['node']}（{t['points']:,} 条）" for t in tel["top_nodes"]) + "\n")
    if tel["hourly_trend"]:
        L.append("<details><summary>逐小时上报趋势</summary>\n")
        for p in tel["hourly_trend"]:
            bar = "█" * max(1, round(p["count"] / max(1, max(q["count"] for q in tel["hourly_trend"])) * 20))
            L.append(f"- `{p['hour'][5:]}` {bar} {p['count']}")
        L.append("\n</details>\n")

    L.append("## 四、告警分析\n")
    L.append(f"窗口内触发告警 **{alerts['window_total']}** 条："
             f"严重 {alerts['by_severity'].get('critical', 0)}、主要 {alerts['by_severity'].get('major', 0)}、"
             f"一般 {alerts['by_severity'].get('minor', 0)}、提示 {alerts['by_severity'].get('warning', 0)}；"
             f"状态：活动 {alerts['by_status'].get('active', 0)}、"
             f"已确认 {alerts['by_status'].get('acked', 0)}、已恢复 {alerts['by_status'].get('cleared', 0)}。\n")
    if alerts["active"]:
        L.append("| 活动告警 | 级别 | 节点 | 触发时间 |")
        L.append("| --- | --- | --- | --- |")
        for a in alerts["active"]:
            L.append(f"| {a['title']} | {a['severity']} | {a['node']} | {a['started_at']} |")
        L.append("")
    rules = snapshot["rules"]
    hot = [r for r in rules if r["trigger_count"] > 0]
    if hot:
        L.append("触发最频繁的规则：" + "；".join(
            f"{r['name']}（{r['trigger_count']} 次）" for r in hot[:3]) + "\n")

    L.append("## 五、数据资产管理\n")
    size = media["size_bytes"]
    L.append(f"- 图片 {media['by_type'].get('image', 0)} 个（{_fmt_size(size.get('image', 0))}）、"
             f"视频 {media['by_type'].get('video', 0)} 个（{_fmt_size(size.get('video', 0))}）、"
             f"其他 {media['by_type'].get('other', 0)} 个（{_fmt_size(size.get('other', 0))}）")
    L.append(f"- 窗口内新增 {media['window_new']} 个文件\n")

    L.append("## 六、结论与建议\n")
    for i, f in enumerate(findings, 1):
        L.append(f"{i}. {f}")
    L.append("")
    L.append("---")
    L.append("*本报告由 NovaEdge 智能管家自动生成。*")
    return "\n".join(L), summary


def _llm_polish(snapshot: dict, builtin_md: str) -> str | None:
    """LLM 润色：把快照数据交给模型写一份更专业的报告；失败返回 None。"""
    from . import llm
    if not llm.is_enabled():
        return None
    system = ("你是 NovaEdge 物联网平台的资深运维分析师。请基于提供的平台数据快照，"
              "撰写一份中文 Markdown 格式的《平台运行分析报告》，结构包含：平台概况、节点状态、"
              "数据采集分析、告警分析、数据资产管理、结论与建议。要求：数字必须来自快照不得编造；"
              "使用 Markdown 表格呈现关键数据；给出有依据的运维建议；篇幅适中（600~1200 字）。")
    try:
        return llm.chat_text(system, "```json\n" +
                             _compact(snapshot) + "\n```", max_tokens=4000)
    except Exception:
        return None


def _compact(snapshot: dict) -> str:
    """压缩快照：截断超长趋势数组，控制 token。"""
    import json as _json
    snap = dict(snapshot)
    if len(snap.get("telemetry", {}).get("hourly_trend", [])) > 30:
        snap["telemetry"] = dict(snap["telemetry"])
        snap["telemetry"]["hourly_trend"] = snap["telemetry"]["hourly_trend"][-30:]
    return _json.dumps(snap, ensure_ascii=False)


def generate_report(report_type: str = "on_demand", title: str = "",
                    created_by: str = "", hours: int = 24) -> ButlerReport:
    """生成并持久化报告。LLM 可用时润色，否则内置模板。"""
    from . import llm

    if not title:
        now = utcnow()
        prefix = {"daily": "每日", "weekly": "每周"}.get(report_type, "平台运行")
        title = f"{prefix}分析报告 · {now.strftime('%Y-%m-%d %H:%M')}"

    snapshot = collect_snapshot(hours=hours)
    builtin_md, summary = _builtin_markdown(snapshot, title)
    content = None
    engine = "builtin"
    if llm.is_enabled():
        content = _llm_polish(snapshot, builtin_md)
        if content:
            engine = "llm"
    report = ButlerReport(
        title=title, report_type=report_type, status="done",
        content_md=content or builtin_md, summary=summary,
        data_snapshot=snapshot, engine=engine, created_by=created_by,
        node_count=snapshot["nodes"]["total"],
        alert_count=snapshot["alerts"]["window_total"],
        telemetry_count=snapshot["telemetry"]["window_points"],
    )
    db.session.add(report)
    db.session.commit()
    return report
