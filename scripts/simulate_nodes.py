#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多节点数据模拟器 —— 用于平台功能验证与演示。

它会读取 ``backend/data/device_credentials.json``（由 ``init_db.py --seed`` 生成），
为每个节点：

* 回填指定时长、指定间隔的传感器遥测（含跨告警阈值的波动段）
* 抓拍若干张图片并上传
* 录制并上传短视频（首个节点会生成大文件以验证**分片上传**通道）

用法::

    python scripts/simulate_nodes.py                        # 默认 24 小时 / 5 个节点
    python scripts/simulate_nodes.py --hours 6 --interval 300
    python scripts/simulate_nodes.py --images 8 --videos 1 --big-video
    python scripts/simulate_nodes.py --node RPI-LAB-A01      # 只模拟指定节点
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "node_agent"))

import requests  # noqa: E402

from collectors.camera import Camera  # noqa: E402
from uploader import Uploader  # noqa: E402
from spool import Spool  # noqa: E402

CRED_FILE = ROOT / "backend" / "data" / "device_credentials.json"
WORK_DIR = ROOT / "scripts" / ".simdata"

# 每个节点的指标画像：基准值 / 波动幅度 / 单位 / 告警穿越概率
PROFILES = {
    "RPI-LAB-A01": {
        "temperature": (25.5, 3.5, "℃", 0.10),
        "humidity": (55.0, 12.0, "%RH", 0.06),
        "light_lux": (430.0, 260.0, "lux", 0.0),
        "co2_ppm": (680.0, 260.0, "ppm", 0.05),
        "person_count": (4.0, 3.0, "人", 0.0),
    },
    "OPI-LAB-A02": {
        "temperature": (24.0, 2.5, "℃", 0.08),
        "humidity": (58.0, 10.0, "%RH", 0.04),
        "co2_ppm": (720.0, 320.0, "ppm", 0.07),
        "pm25": (32.0, 18.0, "μg/m³", 0.05),
        "noise_db": (48.0, 12.0, "dB", 0.0),
    },
    "OPI-LAB-B01": {
        "voltage": (220.0, 8.0, "V", 0.06),
        "current": (12.5, 4.0, "A", 0.05),
        "power_watt": (2750.0, 600.0, "W", 0.03),
    },
    "RPI-GATE-01": {
        "temperature": (22.0, 4.0, "℃", 0.05),
        "person_count": (6.0, 6.0, "人", 0.12),
        "motion_detected": (0.5, 0.5, "", 0.0),
        "light_lux": (620.0, 400.0, "lux", 0.0),
    },
    "JETSON-VIS-01": {
        "person_count": (8.0, 7.0, "人", 0.15),
        "object_count": (14.0, 8.0, "个", 0.0),
        "confidence": (91.5, 4.0, "%", 0.0),
        "temperature": (26.0, 3.0, "℃", 0.06),
    },
}


def load_credentials(only: str | None = None) -> list[dict]:
    if not CRED_FILE.exists():
        print(f"[错误] 未找到设备凭证文件：{CRED_FILE}")
        print("       请先运行：cd backend && python init_db.py --seed")
        sys.exit(1)
    data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    if only:
        data = [d for d in data if d["node_uid"] == only]
        if not data:
            print(f"[错误] 凭证文件中没有节点 {only}")
            sys.exit(1)
    return data


def generate_samples(profile: dict, start: datetime, hours: float, interval: int) -> list[dict]:
    """按时间轴生成遥测样本（带正弦日变化 + 噪声 + 阈值穿越）。"""
    samples: list[dict] = []
    steps = int(hours * 3600 / interval)
    for index in range(steps):
        moment = start + timedelta(seconds=index * interval)
        ts = int(moment.timestamp() * 1000)
        hour_angle = (moment.hour * 3600 + moment.minute * 60) / 86400 * 2 * math.pi
        for metric, (base, amplitude, unit, risk) in profile.items():
            daily = math.sin(hour_angle - math.pi / 2) * amplitude
            drift = math.sin(index / 37.0) * amplitude * 0.35
            noise = random.gauss(0, amplitude * 0.10)
            value = base + daily + drift + noise
            # 少量样本穿越告警阈值，用于验证告警引擎
            if risk and random.random() < risk:
                value = base + amplitude * random.uniform(1.6, 2.6)
            if metric in {"humidity"}:
                value = min(max(value, 18.0), 96.0)
            if metric in {"person_count", "object_count"}:
                value = max(int(round(value)), 0)
            elif metric == "motion_detected":
                value = int(value > base)
            else:
                value = round(value, 2)
            samples.append({"metric": metric, "value": value, "ts": ts, "unit": unit})
    return samples


def post_telemetry(base_url: str, headers: dict, samples: list[dict]) -> int:
    """分批上报（每 500 条一批，模拟真实节点的批量策略）。"""
    accepted = 0
    for start in range(0, len(samples), 500):
        chunk = samples[start:start + 500]
        try:
            resp = requests.post(f"{base_url}/api/v1/device/telemetry",
                                 headers=headers, json={"samples": chunk}, timeout=60)
            body = resp.json()
            if body.get("code") == 0:
                accepted += body["data"]["accepted"]
            else:
                print(f"    [警告] 上报被拒绝：{body.get('message')}")
        except requests.RequestException as exc:
            print(f"    [警告] 上报失败：{exc}")
    return accepted


def main() -> int:
    parser = argparse.ArgumentParser(description="NovaEdge 多节点数据模拟器")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--hours", type=float, default=24.0, help="回填历史数据的时长")
    parser.add_argument("--interval", type=int, default=300, help="采样间隔（秒）")
    parser.add_argument("--images", type=int, default=6, help="每节点生成的图片数量")
    parser.add_argument("--videos", type=int, default=1, help="每节点生成的视频数量")
    parser.add_argument("--video-duration", type=int, default=6, help="视频时长（秒）")
    parser.add_argument("--big-video", action="store_true",
                        help="生成一个大视频（>1MB）以验证分片上传通道")
    parser.add_argument("--node", default=None, help="只模拟指定节点编码")
    parser.add_argument("--skip-media", action="store_true", help="只上报遥测数据")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    credentials = load_credentials(args.node)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    start = datetime.now() - timedelta(hours=args.hours)

    print("=" * 74)
    print("NovaEdge 数据模拟器")
    print(f"  平台地址   : {base_url}")
    print(f"  节点数量   : {len(credentials)}")
    print(f"  历史时长   : {args.hours} 小时 / 采样间隔 {args.interval} 秒")
    print(f"  媒体生成   : 图片 {args.images} 张 / 视频 {args.videos} 个"
          f"{'（含大文件分片测试）' if args.big_video else ''}")
    print("=" * 74)

    grand = {"telemetry": 0, "images": 0, "videos": 0, "failed": 0}
    for position, cred in enumerate(credentials, 1):
        uid = cred["node_uid"]
        headers = {"X-Node-Key": cred["access_key"], "X-Node-Secret": cred["secret"]}
        profile = PROFILES.get(uid)
        if not profile:
            print(f"\n[{position}/{len(credentials)}] {uid} 未配置指标画像，跳过")
            continue

        print(f"\n[{position}/{len(credentials)}] 节点 {uid}")
        # ---- 注册 ----
        try:
            resp = requests.post(f"{base_url}/api/v1/device/register", headers=headers,
                                 json={"agent_version": "1.0.0",
                                       "ip_address": f"192.168.1.{20 + position}",
                                       "report_interval": args.interval}, timeout=30)
            if resp.json().get("code") != 0:
                print(f"    [警告] 注册失败：{resp.json().get('message')}")
        except requests.RequestException as exc:
            print(f"    [跳过] 平台不可达：{exc}")
            return 1

        # ---- 遥测 ----
        samples = generate_samples(profile, start, args.hours, args.interval)
        accepted = post_telemetry(base_url, headers, samples)
        grand["telemetry"] += accepted
        print(f"    遥测数据 : 生成 {len(samples)} 条，平台接收 {accepted} 条"
              f"（{len(profile)} 个指标 × {int(args.hours * 3600 / args.interval)} 个时刻）")

        # ---- 心跳 ----
        for offset in range(0, 4):
            requests.post(f"{base_url}/api/v1/device/heartbeat", headers=headers, json={
                "cpu_percent": round(random.uniform(8, 62), 1),
                "mem_percent": round(random.uniform(30, 74), 1),
                "disk_percent": round(random.uniform(24, 68), 1),
                "cpu_temp": round(random.uniform(41, 63), 1),
                "net_rx_kbps": round(random.uniform(20, 480), 1),
                "net_tx_kbps": round(random.uniform(10, 260), 1),
                "uptime_seconds": 3600 * (offset + 1),
                "process_count": random.randint(60, 140),
                "agent_version": "1.0.0",
            }, timeout=30)

        if args.skip_media:
            continue

        # ---- 媒体 ----
        node_dir = WORK_DIR / uid
        node_dir.mkdir(parents=True, exist_ok=True)
        camera = Camera({"backend": "mock", "mock_enabled": True,
                         "image_resolution": [1280, 720], "video_resolution": [1280, 720],
                         "mock_objects": random.randint(1, 4)},
                        uid)
        uploader = Uploader(base_url, headers, timeout=60)

        for index in range(args.images):
            path = camera.capture_image(node_dir)
            if path is None:
                continue
            result = uploader.upload_file(path, file_type="image", source="scheduled",
                                          captured_at=start + timedelta(
                                              seconds=random.randint(0, int(args.hours * 3600))),
                                          tags=["模拟采集", uid])
            if result:
                grand["images"] += 1
            else:
                grand["failed"] += 1
            path.unlink(missing_ok=True)

        for index in range(args.videos):
            duration = args.video_duration
            if args.big_video and position == 1:
                duration = max(duration, 36)     # 生成 >1MB 视频走分片上传
            path = camera.record_video(node_dir, duration)
            if path is None:
                continue
            size_mb = path.stat().st_size / 1048576
            result = uploader.upload_file(path, file_type="video", source="scheduled",
                                          captured_at=start + timedelta(
                                              seconds=random.randint(0, int(args.hours * 3600))),
                                          tags=["模拟录像"],
                                          extra={"duration_sec": duration})
            if result:
                grand["videos"] += 1
                print(f"    视频上传 : {path.name}（{size_mb:.2f} MB，{duration}s）"
                      f"{'  → 走分片通道' if size_mb > 1 else '  → 走直传通道'}")
            else:
                grand["failed"] += 1
            path.unlink(missing_ok=True)

        print(f"    媒体数据 : 图片 {args.images} 张 / 视频 {args.videos} 个")

    print("\n" + "=" * 74)
    print(f"模拟完成：遥测 {grand['telemetry']} 条 / 图片 {grand['images']} 张 / "
          f"视频 {grand['videos']} 个 / 失败 {grand['failed']}")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
