"""智能管家引擎：大模型工具调用循环 + 内置规则引擎兜底。

- LLM 已配置：标准 function-calling 循环（最多 6 轮），模型自主选择工具。
- LLM 未配置/失败：内置意图识别，直接调用对应工具并格式化回答。
"""

from __future__ import annotations

import json
import re

from ...extensions import db
from ...models import ButlerMessage, ROLE_OPERATOR, ROLE_VIEWER
from . import llm, tools

MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """你是 NovaEdge 边缘智算管理平台的「智能管家」，负责协助用户管理边缘计算节点。
平台管理树莓派、香橙派等边缘节点，采集传感器遥测数据（温度/湿度/CO2/光照/CPU/内存等）、
图片与视频资产，支持阈值告警与远程指令下发。

你的能力：
1. 通过工具查询平台实时数据（节点、遥测、告警、媒体、指令、系统概况）；
2. 通过工具执行配置操作（修改/新建告警规则、下发节点指令）——这些操作会立即生效并写入审计日志。

要求：
- 用简体中文回答，简洁专业；
- 回答数据问题时先调用工具获取实时数据，不要编造数字；
- 用户要求"调高/调低阈值、关闭规则、下发指令"等配置操作时，先查规则确认 rule_id，再执行写工具；
- 若工具返回 error，向用户说明原因与建议；
- 报告生成类需求请引导用户使用右侧「分析报告」功能。"""


def _allow_write(user) -> bool:
    return getattr(user, "role", ROLE_VIEWER) != ROLE_VIEWER


def run(session_id: str, message: str, user) -> dict:
    """处理一条用户消息，返回 {reply, engine, trace}。"""
    db.session.add(ButlerMessage(session_id=session_id, user_id=getattr(user, "id", 0),
                                 role="user", content=message))
    db.session.commit()

    allow_write = _allow_write(user)
    use_llm = llm.is_enabled()
    try:
        if use_llm:
            reply, trace = _run_llm(session_id, message, user, allow_write)
            engine = "llm"
        else:
            reply, trace = _run_builtin(message, allow_write)
            engine = "builtin"
    except Exception as exc:
        db.session.rollback()
        # LLM 链路异常 → 降级内置引擎兜底，保证功能可用
        reply, trace = _run_builtin(message, allow_write)
        engine = "builtin-fallback"
        trace.append({"event": "llm_error", "detail": str(exc)[:300]})

    db.session.add(ButlerMessage(session_id=session_id, user_id=getattr(user, "id", 0),
                                 role="assistant", content=reply, engine=engine))
    db.session.commit()
    return {"reply": reply, "engine": engine, "trace": trace}


# --------------------------------------------------------------------------
# LLM function-calling 循环
# --------------------------------------------------------------------------

def _run_llm(session_id: str, message: str, user, allow_write: bool) -> tuple[str, list]:
    history = (ButlerMessage.query.filter_by(session_id=session_id)
               .order_by(ButlerMessage.id.desc()).limit(12).all())
    context = []
    for m in reversed(history):
        if m.role == "user" and m.content:
            context.append({"role": "user", "content": m.content})
        elif m.role == "assistant" and m.content:
            context.append({"role": "assistant", "content": m.content})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + context
    tool_schemas = tools.all_tools()
    if not allow_write:  # 只读角色隐藏写工具，双保险
        tool_schemas = [t for t in tool_schemas if t["name"] not in tools.WRITE_TOOLS]

    trace = []
    for _ in range(MAX_TOOL_ROUNDS):
        assistant = llm.chat(messages, tools=tool_schemas)
        calls = assistant.get("tool_calls") or []
        if not calls:
            return assistant.get("content") or "（模型未返回内容）", trace

        messages.append({"role": "assistant",
                         "content": assistant.get("content") or "",
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = tools.dispatch(name, args, user=user, allow_write=allow_write)
            trace.append({"tool": name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "content": json.dumps(result, ensure_ascii=False)})
    return "（已达工具调用轮次上限，请拆分需求后再试）", trace


# --------------------------------------------------------------------------
# 内置规则引擎（无 LLM 时的兜底）
# --------------------------------------------------------------------------

_HELP = """我是 NovaEdge 智能管家，可以帮你：

📊 **查数据**：「现在有几个节点在线？」「最近24小时温度情况」「看看告警」「图片视频有多少」
⚙️ **配系统**：「把CPU告警阈值调到90」「新建一条内存告警规则」「给2号节点发个重启指令」（需操作员权限）
📄 **出报告**：在右侧「分析报告」中一键生成平台分析报告

> 💡 在「设置」中配置 OpenAI 兼容大模型接口（DeepSeek / 通义 / Kimi / Ollama 均可）后，
> 我将具备更强的自然语言理解与多步推理能力。当前为内置规则引擎模式。"""

_TOOL_BY_INTENT = [
    (r"帮助|你能做什么|怎么用", "help"),
    (r"(节点|设备).*(在线|状态|列表)|在线.*节点", "query_nodes"),
    (r"告警规则|规则.*(阈值|列表)", "query_alert_rules"),
    (r"告警|报警", "query_alerts"),
    (r"(图片|视频|媒体|资产|存储的文件)", "query_media_stats"),
    (r"(指令|命令|下发).*(统计|记录|情况)|(指令|命令)中心", "query_commands"),
    (r"(系统|平台).*(概况|健康|状态|状况|运行|存储)|存储占用", "query_system"),
    (r"分组", "query_groups"),
    (r"(温度|湿度|CO2|光照|CPU|内存|遥测|传感|指标|数据量|统计)", "query_telemetry_stats"),
]


def _extract_hours(text: str) -> int:
    m = re.search(r"(\d+)\s*(?:个)?小时", text)
    if m:
        return min(int(m.group(1)), 24 * 30)
    m = re.search(r"(\d+)\s*天", text)
    if m:
        return min(int(m.group(1)) * 24, 24 * 30)
    return 24


def _extract_state(text: str) -> str:
    if "在线" in text:
        return "online"
    if "离线" in text:
        return "offline"
    return "all"


def _pick_metric(text: str) -> str | None:
    pairs = [("温度", "temperature"), ("湿度", "humidity"), ("CO2", "co2"),
             ("光照", "light"), ("CPU", "cpu_percent"), ("内存", "mem_percent")]
    for zh, key in pairs:
        if zh.lower() in text.lower():
            return key
    return None


def _pick_node_id(text: str) -> int | None:
    from ...models import Node
    m = re.search(r"(\d+)\s*号", text)
    if m:
        node = Node.query.filter_by(id=int(m.group(1))).first()
        if node:
            return node.id
    for node in Node.query.all():
        if node.name and node.name in text:
            return node.id
    return None


def _run_builtin(message: str, allow_write: bool) -> tuple[str, list]:
    text = message.strip()
    trace = []

    # ---- 配置类意图（关键词直配） ----
    cfg_like = ("阈值" in text or "指令" in text or "下发" in text or "新建" in text
                or re.search(r"(调到|调整为|改成|设为)", text))
    if allow_write:
        cfg_reply, cfg_trace = _try_builtin_config(text, allow_write)
        if cfg_reply is not None:
            return cfg_reply, cfg_trace
    elif cfg_like:
        return ("⚠️ 配置操作（修改阈值 / 新建规则 / 下发指令）需要**操作员或管理员**角色，"
                "当前账号为只读访客。请联系统管理员，或用你的操作员账号登录后再试。"), []

    # ---- 查询类意图 ----
    intent = None
    for pattern, tool in _TOOL_BY_INTENT:
        if re.search(pattern, text):
            intent = tool
            break

    # 「N号节点」/「节点详情」单节点意图
    if intent is None:
        m_node = re.search(r"(\d+)\s*号", text)
        if m_node and ("节点" in text or "设备" in text):
            args = {"node_id": int(m_node.group(1))}
            result = tools.dispatch("query_node_detail", args)
            trace.append({"tool": "query_node_detail", "args": args, "result": result})
            return _format("query_node_detail", args, result), trace

    if intent is None or intent == "help":
        return _HELP, trace

    args: dict = {}
    if intent == "query_nodes":
        args["state"] = _extract_state(text)
    elif intent in ("query_alerts", "query_media_stats", "query_commands", "query_telemetry_stats"):
        args["hours"] = _extract_hours(text)
    if intent == "query_alerts":
        if "严重" in text or "critical" in text.lower():
            args["severity"] = "critical"
        if "未恢复" in text or "激活" in text:
            args["status"] = "active"
    if intent == "query_telemetry_stats":
        node_id = _pick_node_id(text)
        if node_id:
            args["node_id"] = node_id

    result = tools.dispatch(intent, args)
    trace.append({"tool": intent, "args": args, "result": result})
    return _format(intent, args, result), trace


def _try_builtin_config(text: str, allow_write: bool) -> tuple[str | None, list]:
    from ...models import AlertRule, Node

    # 修改阈值：「把/将 …(规则名或指标)… 阈值调到/改成 N」
    m = re.search(r"(?:调到|调整为|改成|设为|设置为)\s*([\d.]+)", text)
    if m and ("阈值" in text or "调" in text):
        target_val = float(m.group(1))
        rules = AlertRule.query.all()
        rule = None
        pairs = [("温度", "temperature"), ("湿度", "humidity"), ("CO2", "co2"),
                 ("光照", "light"), ("CPU", "cpu_percent"), ("内存", "mem_percent")]
        for zh, key in pairs:
            if zh.lower() in text.lower():
                rule = next((r for r in rules if r.metric_key == key), None)
                break
        if rule is None:
            m2 = re.search(r"规则\s*(\d+)", text)
            if m2:
                rule = db.session.get(AlertRule, int(m2.group(1)))
        if rule is None:
            return ("未定位到要修改的告警规则，请指明指标（如 CPU、温度）或规则编号。"
                    "当前规则：" + "；".join(f"{r.id}.{r.name}" for r in rules)), []
        old = rule.threshold
        result = tools.dispatch("update_alert_rule",
                                {"rule_id": rule.id, "threshold": target_val},
                                allow_write=allow_write)
        trace = [{"tool": "update_alert_rule",
                  "args": {"rule_id": rule.id, "threshold": target_val}, "result": result}]
        if result.get("ok"):
            return (f"✅ 已将告警规则「{rule.name}」的阈值从 {old} 调整为 {target_val}，"
                    f"该操作已写入审计日志。"), trace
        return f"❌ 修改失败：{result.get('error')}", trace

    # 下发指令：「给 N 号节点 发/下发 <指令>」
    m = re.search(r"(?:给|向)\s*(\d+)\s*号\s*(?:节点)?\s*(?:发送|下发|执行)?\s*(开始录像|停止录像|同步配置|重启|抓拍|拍照|录像|停止|校时|自检)?", text)
    if m and ("指令" in text or "下发" in text or "发送" in text or m.group(2)):
        from ...models import COMMAND_CATALOG
        zh_map = {"重启": "reboot", "抓拍": "capture_image", "拍照": "capture_image",
                  "录像": "start_record", "开始录像": "start_record",
                  "停止": "stop_record", "停止录像": "stop_record",
                  "自检": "self_test", "同步配置": "sync_config", "校时": "sync_config"}
        cmd_zh = m.group(2)
        if not cmd_zh:
            catalog = "、".join(f"{k}（{v['label']}）" for k, v in COMMAND_CATALOG.items())
            return ("请说明要下发的指令，例如：重启 / 抓拍 / 录像 / 校时 / 自检。可用指令：" + catalog), []
        node_id = int(m.group(1))
        result = tools.dispatch("send_node_command",
                                {"node_id": node_id, "command": zh_map[cmd_zh]},
                                allow_write=allow_write)
        trace = [{"tool": "send_node_command",
                  "args": {"node_id": node_id, "command": zh_map[cmd_zh]}, "result": result}]
        if result.get("ok"):
            return (f"✅ 已向节点 {result['node']} 下发「{result['command']}」指令"
                    f"（通道：{result['channel']}，状态：{result['status']}）。"), trace
        return f"❌ 下发失败：{result.get('error')}", trace

    # 新建规则：「新建/添加一条 … 告警规则，阈值 N」
    if re.search(r"新建|添加|新增", text) and "规则" in text:
        m_val = re.search(r"阈值\s*([\d.]+)", text)
        metric = _pick_metric(text)
        if not (m_val and metric):
            return ("新建告警规则需要指明指标与阈值，例如：「新建一条 CPU 告警规则，阈值 90」。"
                    f"支持的指标关键词：温度/湿度/CO2/光照/CPU/内存。"), []
        name = f"{metric} 智能管家规则"
        result = tools.dispatch("create_alert_rule",
                                {"name": name, "metric_key": metric, "operator": "gt",
                                 "threshold": float(m_val.group(1))},
                                allow_write=allow_write)
        trace = [{"tool": "create_alert_rule",
                  "args": {"metric_key": metric, "threshold": float(m_val.group(1))},
                  "result": result}]
        if result.get("ok"):
            return f"✅ 已创建告警规则「{result['rule_name']}」，阈值 {m_val.group(1)}。", trace
        return f"❌ 创建失败：{result.get('error')}", trace

    return None, []


def _fmt_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def _format(tool: str, args: dict, result: dict) -> str:
    if result.get("error"):
        return f"❌ 查询失败：{result['error']}"
    lines: list[str] = []
    if tool == "query_node_detail":
        mark = "🟢" if result["status"] == "online" else "🔴"
        lines.append(f"{mark} **{result['name']}**（{result['status']}）· 分组 {result['group'] or '未分组'}"
                     f" · 最近上线 {result['last_seen_at'] or '—'}")
        lines.append("最新指标：")
        for key, item in list(result["latest_metrics"].items())[:12]:
            lines.append(f"- {key}: {item['value']}（{item['time']}）")
        return "\n".join(lines)
    if tool == "query_nodes":
        state = args.get("state", "all")
        state_label = {"online": "在线", "offline": "离线"}.get(state, "全部")
        nodes = result["nodes"]
        if state != "all":
            lines.append(f"**{state_label}节点（{result['total']} 个）**：")
        else:
            online = sum(1 for n in nodes if n["status"] == "online")
            lines.append(f"**节点共 {result['total']} 个，在线 {online} 个，离线 {result['total'] - online} 个**")
        for n in nodes[:15]:
            mark = "🟢" if n["status"] == "online" else "🔴"
            lines.append(f"- {mark} {n['name']}（{n['type']}）· 分组 {n['group'] or '未分组'}"
                         f" · 最近上线 {n['last_seen_at'] or '—'}")
    elif tool == "query_telemetry_stats":
        lines.append(f"**最近 {result['hours']} 小时遥测概况**（按各节点最新值统计）：")
        for m in result["metrics"][:12]:
            lines.append(f"- {m['metric_name']}：均值 {m['avg']}，范围 {m['min']} ~ {m['max']}（{m['node_count']} 节点）")
        if result.get("top_nodes_by_points"):
            tops = "、".join(f"{t['node']}（{t['points']} 条）" for t in result["top_nodes_by_points"])
            lines.append(f"\n数据量 TOP5：{tops}")
    elif tool == "query_alerts":
        lines.append(f"**最近 {result['hours']} 小时告警共 {result['total']} 条**"
                     f"（严重 {result['by_severity'].get('critical', 0)} /"
                     f" 主要 {result['by_severity'].get('major', 0)} /"
                     f" 一般 {result['by_severity'].get('minor', 0)} /"
                     f" 提示 {result['by_severity'].get('warning', 0)}）")
        for r in result["records"][:10]:
            lines.append(f"- {r['started_at']} 【{r['severity']}】{r['title']}")
    elif tool == "query_alert_rules":
        lines.append(f"**告警规则共 {result['total']} 条**：")
        for r in result["rules"]:
            op = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤"}.get(r["operator"], r["operator"])
            cond = f"{op} {r['threshold']}"
            if r["threshold2"] is not None:
                cond += f" 且 < {r['threshold2']}"
            lines.append(f"- {'✅' if r['enabled'] else '⏸'} #{r['id']} {r['name']}："
                         f"{r['metric_key']} {cond}（持续 {r['duration_sec']}s，{r['severity']}）")
    elif tool == "query_media_stats":
        cnt = result["count_by_type"]
        size = result["size_bytes_by_type"]
        lines.append(f"**数据资产统计**（最近 {result['hours']} 小时新增 {result['recent_count']} 个）：")
        lines.append(f"- 图片 {cnt.get('image', 0)} 个（{_fmt_size(size.get('image', 0))}）")
        lines.append(f"- 视频 {cnt.get('video', 0)} 个（{_fmt_size(size.get('video', 0))}）")
        lines.append(f"- 其他文件 {cnt.get('other', 0)} 个（{_fmt_size(size.get('other', 0))}）")
        lines.append(f"- 合计 {result['total_count']} 个，占用 {_fmt_size(sum(size.values()))}")
    elif tool == "query_commands":
        st = result["count_by_status"]
        lines.append(f"**最近 {result['hours']} 小时指令统计**：待执行 {st.get('pending', 0)}、"
                     f"已发送 {st.get('sent', 0)}、成功 {st.get('success', 0)}、"
                     f"失败 {st.get('failed', 0)}、超时 {st.get('timeout', 0)}")
        if result["pending"]:
            lines.append("待执行：")
            for p in result["pending"]:
                lines.append(f"- #{p['id']} 节点 {p['node_id']} · {p['command']}（{p['issued_by']}）")
    elif tool == "query_system":
        total = result["nodes_total"] or 1
        lines.append("**平台系统概况**：")
        lines.append(f"- 节点：{result['nodes_total']} 个，在线 {result['nodes_online']}"
                     f"（在线率 {result['nodes_online'] / total * 100:.0f}%）")
        lines.append(f"- 遥测数据点累计：{result['telemetry_points']:,}")
        lines.append(f"- 媒体存储占用：{_fmt_size(result['media_storage_bytes'])}")
        lines.append(f"- 大模型：{'已配置' if result['llm_configured'] else '未配置（内置规则引擎模式）'}")
        lines.append(f"- 服务器时间：{result['server_time']}")
    elif tool == "query_groups":
        lines.append("**节点分组**：")
        for g in result["groups"]:
            lines.append(f"- {g['name']}：{g['node_count']} 个节点")
    else:
        return json.dumps(result, ensure_ascii=False)
    return "\n".join(lines)
