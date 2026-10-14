# -*- coding: utf-8 -*-
"""数据库初始化脚本。

用法::

    python init_db.py              # 建表
    python init_db.py --seed       # 建表 + 写入演示数据（推荐首次使用）
    python init_db.py --reset      # 清空重建（危险，仅开发环境）

生产环境切 MySQL::

    set DB_TYPE=mysql
    set MYSQL_HOST=127.0.0.1
    set MYSQL_USER=root
    set MYSQL_PASSWORD=yourpass
    set MYSQL_DB=novaedge
    python init_db.py --seed
"""

from __future__ import annotations

import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import (AlertRule, MetricDef, Node, NodeCredential, NodeGroup,
                        SysConfig, User, utcnow)
from werkzeug.security import generate_password_hash

# --------------------------------------------------------------------------- #
# 物模型：环境量 / 电气量 / 视觉量 / 系统量
# --------------------------------------------------------------------------- #
METRIC_SEEDS = [
    # key,          名称,          类型,   单位,    分类,     下限,  上限, 小数位
    ("temperature", "空气温度", "float", "℃", "env", -40, 125, 1),
    ("humidity", "空气湿度", "float", "%RH", "env", 0, 100, 1),
    ("light_lux", "光照强度", "float", "lux", "env", 0, 200000, 0),
    ("co2_ppm", "CO₂ 浓度", "float", "ppm", "env", 0, 10000, 0),
    ("pm25", "PM2.5 浓度", "float", "μg/m³", "env", 0, 1000, 0),
    ("noise_db", "环境噪声", "float", "dB", "env", 0, 140, 1),
    ("voltage", "电压", "float", "V", "power", 0, 400, 1),
    ("current", "电流", "float", "A", "power", 0, 100, 2),
    ("power_watt", "有功功率", "float", "W", "power", 0, 20000, 1),
    ("person_count", "识别人数", "int", "人", "vision", 0, 500, 0),
    ("object_count", "目标数量", "int", "个", "vision", 0, 500, 0),
    ("confidence", "识别置信度", "float", "%", "vision", 0, 100, 1),
    ("motion_detected", "移动侦测", "bool", "", "vision", 0, 1, 0),
    ("cpu_percent", "CPU 使用率", "float", "%", "system", 0, 100, 1),
    ("mem_percent", "内存使用率", "float", "%", "system", 0, 100, 1),
    ("disk_percent", "磁盘使用率", "float", "%", "system", 0, 100, 1),
    ("cpu_temp", "SoC 温度", "float", "℃", "system", 0, 120, 1),
    ("net_rx_kbps", "下行速率", "float", "kbps", "system", 0, 1000000, 1),
    ("net_tx_kbps", "上行速率", "float", "kbps", "system", 0, 1000000, 1),
]

NODE_SEEDS = [
    # uid,              名称,             类型,          分组索引, 型号,                  位置,               能力
    ("RPI-LAB-A01", "实验楼A区-图像采集节点", "raspberrypi", 0,
     "Raspberry Pi 4B 8GB", "实验楼A区 305 机房", {"camera": True, "video": True,
                                                "sensors": ["temperature", "humidity", "light_lux"]}),
    ("OPI-LAB-A02", "实验楼A区-环境监测节点", "orangepi", 0,
     "Orange Pi 5 Plus 16GB", "实验楼A区 306 机房", {"camera": True, "video": False,
                                                  "sensors": ["temperature", "humidity", "co2_ppm", "pm25"]}),
    ("OPI-LAB-B01", "实验楼B区-电力监测节点", "orangepi", 1,
     "Orange Pi 5 8GB", "实验楼B区 配电间", {"camera": False, "video": False,
                                           "sensors": ["voltage", "current", "power_watt"]}),
    ("RPI-GATE-01", "厂区北门-人员通行节点", "raspberrypi", 2,
     "Raspberry Pi 4B 4GB", "厂区北门", {"camera": True, "video": True,
                                       "sensors": ["person_count", "motion_detected"]}),
    ("JETSON-VIS-01", "视觉分析-边缘算力节点", "jetson", 2,
     "Jetson Orin Nano 8GB", "厂区北门 机柜 3", {"camera": True, "video": True,
                                              "sensors": ["person_count", "object_count", "confidence"]}),
]

GROUP_SEEDS = [
    ("实验楼 A 区", "LAB-A", "教学实验区域，部署图像与环境监测节点"),
    ("实验楼 B 区", "LAB-B", "教学实验区域，部署电力监测节点"),
    ("厂区北门", "GATE-N", "室外场景，部署人员通行与视觉分析节点"),
]

RULE_SEEDS = [
    # name,                     指标,            算子, 阈值,  第二阈值, 持续秒, 级别,      静默
    ("机房温度过高", "temperature", "gt", 32, None, 60, "major", 300),
    ("机房温度偏低", "temperature", "lt", 5, None, 120, "minor", 600),
    ("空气湿度过高", "humidity", "gt", 85, None, 120, "minor", 600),
    ("CO₂ 浓度超标", "co2_ppm", "gt", 1500, None, 180, "major", 600),
    ("PM2.5 浓度超标", "pm25", "gt", 150, None, 300, "minor", 900),
    ("节点 CPU 过载", "cpu_percent", "gt", 90, None, 120, "warning", 300),
    ("SoC 温度过高", "cpu_temp", "gt", 78, None, 60, "critical", 180),
    ("磁盘空间不足", "disk_percent", "gt", 85, None, 0, "major", 3600),
    ("电压越限", "voltage", "out_of_range", 198, 242, 30, "critical", 300),
    ("人员聚集预警", "person_count", "gt", 20, None, 10, "warning", 300),
]


def seed_users():
    users = [
        ("admin", "admin123", "管理员", "admin", "信息化中心", "admin@example.edu.cn"),
        ("operator", "operator123", "值班运维", "operator", "运维保障组", "ops@example.edu.cn"),
        ("viewer", "viewer123", "访客", "viewer", "教学观摩", ""),
    ]
    created = []
    for username, password, real_name, role, dept, email in users:
        if User.query.filter_by(username=username).first():
            continue
        user = User(username=username, password_hash=generate_password_hash(password),
                    real_name=real_name, role=role, department=dept, email=email,
                    is_active=True)
        db.session.add(user)
        created.append(username)
    db.session.commit()
    return created


def seed_metrics():
    created = 0
    for key, name, data_type, unit, category, low, high, precision in METRIC_SEEDS:
        if MetricDef.query.filter_by(metric_key=key).first():
            continue
        db.session.add(MetricDef(
            metric_key=key, name=name, data_type=data_type, unit=unit,
            category=category, min_value=low, max_value=high, precision=precision,
            is_system=category == "system",
            description="平台内置指标" if category == "system" else "",
        ))
        created += 1
    db.session.commit()
    return created


def seed_groups():
    groups: list[NodeGroup] = []
    for index, (name, code, desc) in enumerate(GROUP_SEEDS):
        group = NodeGroup.query.filter_by(name=name).first()
        if group is None:
            group = NodeGroup(name=name, code=code, description=desc, sort_order=index)
            db.session.add(group)
        groups.append(group)
    db.session.commit()
    return groups


def seed_nodes(groups: list[NodeGroup]):
    created: list[tuple[str, str]] = []
    for uid, name, node_type, group_index, model, location, caps in NODE_SEEDS:
        if Node.query.filter_by(node_uid=uid).first():
            continue
        group = groups[group_index] if group_index < len(groups) else None
        node = Node(
            node_uid=uid, name=name, node_type=node_type, model=model,
            serial_no=f"SN{uid.replace('-', '')}", group_id=group.id if group else 0,
            location=location, capabilities=caps, report_interval=60,
            os_version="Raspberry Pi OS 12 (bookworm)" if node_type == "raspberrypi"
            else "Ubuntu 22.04 LTS", agent_version="1.0.0", enabled=True,
        )
        db.session.add(node)
        db.session.flush()

        access_key = NodeCredential.new_access_key(uid)
        secret = NodeCredential.new_secret()
        db.session.add(NodeCredential(
            node_id=node.id, access_key=access_key,
            secret_hash=generate_password_hash(secret),
            mqtt_username=access_key, mqtt_password=secret, is_active=True,
        ))
        created.append((uid, access_key, secret))
    db.session.commit()
    return created


def seed_rules():
    created = 0
    for name, metric_key, operator, threshold, threshold2, duration, severity, silence in RULE_SEEDS:
        if AlertRule.query.filter_by(name=name).first():
            continue
        db.session.add(AlertRule(
            name=name, node_id=0, group_id=0, metric_key=metric_key, operator=operator,
            threshold=threshold, threshold2=threshold2, duration_sec=duration,
            severity=severity, silence_sec=silence, enabled=True,
            notify_channels=["console"],
            description=f"{metric_key} {'超过' if operator == 'gt' else '低于'} {threshold}",
        ))
        created += 1
    db.session.commit()
    return created


def seed_configs():
    from app.api.system import DEFAULT_CONFIGS
    for key, value, category, description in DEFAULT_CONFIGS:
        if SysConfig.query.filter_by(cfg_key=key).first() is None:
            db.session.add(SysConfig(cfg_key=key, cfg_value=value, category=category,
                                     description=description))
    db.session.commit()


def main():
    parser = argparse.ArgumentParser(description="NovaEdge 数据库初始化")
    parser.add_argument("--seed", action="store_true", help="写入演示数据")
    parser.add_argument("--reset", action="store_true", help="删表重建（开发环境）")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.reset:
            print("[1/2] 正在删除全部数据表 ...")
            db.drop_all()
        print("[1/2] 正在创建数据表 ...")
        db.create_all()
        print(f"       共 {len(db.metadata.tables)} 张表：")
        for table in sorted(db.metadata.tables):
            print(f"         - {table}")

        if args.seed or args.reset:
            print("[2/2] 正在写入演示数据 ...")
            users = seed_users()
            metrics = seed_metrics()
            groups = seed_groups()
            nodes = seed_nodes(groups)
            rules = seed_rules()
            seed_configs()
            print(f"       用户 {len(users)} 个 / 指标 {metrics} 个 / 分组 {len(groups)} 个 "
                  f"/ 节点 {len(nodes) - 0} 个 / 告警规则 {rules} 条")
            if nodes:
                import json
                from pathlib import Path
                cred_path = Path(app.config["STORAGE_ROOT"]).parent / "data" / "device_credentials.json"
                cred_path.parent.mkdir(parents=True, exist_ok=True)
                cred_path.write_text(json.dumps(
                    [{"node_uid": uid, "access_key": key, "secret": secret}
                     for uid, key, secret in nodes], ensure_ascii=False, indent=2),
                    encoding="utf-8")
                print("\n       已签发的设备凭证（secret 仅此一次显示，请妥善保存）：")
                for uid, key, secret in nodes:
                    print(f"         {uid:16s}  X-Node-Key={key}  X-Node-Secret={secret}")
                print(f"\n       凭证已写入：{cred_path}（供 node_agent 读取）")
            print("\n       控制台账号：admin / admin123（管理员）")
            print("                   operator / operator123（运维）")
            print("                   viewer / viewer123（只读）")
        print("\n完成。启动服务：python run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
