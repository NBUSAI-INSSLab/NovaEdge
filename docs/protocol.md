# 平台 ↔ 节点 接口协议

节点 Agent 与平台之间共两条通道：**HTTP（主通道，始终可用）** 与
**MQTT（可选增强，需部署 EMQX）**。媒体一律走 HTTP 分片。

---

## 1. 通用约定

- Base URL：`http://<平台地址>:5000/api/v1`
- 数据格式：请求与响应均为 JSON（分片体除外）
- 统一响应结构：

```json
{ "code": 0, "message": "操作成功", "data": { } }
```

`code=0` 成功；`1001` 为分片未传完的业务中间态；`40x/50x` 见 HTTP 状态码。

- 时间：`ts` 一律为 **Unix 毫秒时间戳**；平台落库为 naive UTC。
- 编码：UTF-8。

## 2. 设备认证

所有 `/device/*` 与 `/upload/*` 接口要求请求头：

```
X-Node-Key: ak_rpi_lab_a01_xxxxxxxx
X-Node-Secret: <平台签发的 secret>
```

- 凭证由控制台「新建节点 / 重置凭证」生成，secret 仅显示一次。
- 平台侧以 **PBKDF2 散列** 存储比对。
- 认证失败返回 `401`，节点应停止上报并告警本地日志。

---

## 3. 节点注册

`POST /api/v1/device/register`

```json
{
  "node_uid": "RPI-LAB-A01",
  "model": "Raspberry Pi 4B 8GB",
  "serial_no": "SNRPILABA01",
  "ip_address": "192.168.0.41",
  "mac_address": "dc:a6:32:xx:xx:xx",
  "os_version": "Debian GNU/Linux 12 (bookworm)",
  "agent_version": "1.0.0",
  "capabilities": ["camera", "ds18b20", "dht22"]
}
```

响应 `data`：节点档案 + 当前服务器时间。节点首次启动、每次重启时调用；
重复注册幂等（更新档案字段）。

## 4. 遥测上报（批量）

`POST /api/v1/device/telemetry`

```json
{
  "samples": [
    { "metric_key": "temperature", "value_num": 25.6, "ts": 1728900000000 },
    { "metric_key": "humidity",    "value_num": 58.2, "ts": 1728900000000 },
    { "metric_key": "co2_ppm",     "value_num": 640,  "ts": 1728900000000 }
  ]
}
```

- `metric_key` 必须已在物模型中定义，否则该条被丢弃并计入日志。
- 支持一次提交多条（跨指标、跨时刻均可）。
- 平台行为：写明细 → upsert 最新值快照 → 交告警引擎按数据时间戳判定 → SSE 广播。

## 5. 心跳上报

`POST /api/v1/device/heartbeat`

```json
{
  "cpu_percent": 34.2, "mem_percent": 54.4, "disk_percent": 61.8,
  "cpu_temp": 52.0, "net_rx_kbps": 120.5, "net_tx_kbps": 88.3,
  "uptime_seconds": 86400, "process_count": 132
}
```

心跳同时刷新 `node.last_seen_at`；超过 `HEARTBEAT_TIMEOUT`（默认 180 秒）未收到则判离线。
建议周期为上报周期的 1/2（默认 15 秒）。

## 6. 运行日志上报

`POST /api/v1/device/logs`

```json
{ "logs": [ { "level": "info", "module": "camera", "message": "抓拍完成 IMG_xxx.jpg", "ts": 1728900000000 } ] }
```

## 7. 媒体上传

### 7.1 小文件直传（< 1MB）

`POST /api/v1/upload/direct`（`multipart/form-data`）

| 字段 | 说明 |
| --- | --- |
| `file` | 文件二进制 |
| `file_type` | image / video |
| `captured_at` | 采集时刻（毫秒时间戳，可选） |
| `meta` | JSON 字符串扩展信息（可选） |

### 7.2 大文件分片（≥ 1MB，支持断点续传与秒传）

```
① POST /api/v1/upload/init      → { file_name, file_type, file_size, chunk_size, sha256, captured_at }
                                  ← { upload_id, instant }   # instant=true 表示秒传，直接结束
② POST /api/v1/upload/chunk     → multipart: upload_id + chunk_index + chunk（二进制）
                                  ← { received_chunks }       # code=1001 表示未传完，继续
③ POST /api/v1/upload/complete  → { upload_id }
                                  ← 平台合并分片、sha256 校验、生成缩略图/探测视频时长
④ GET  /api/v1/upload/status/{upload_id}   # 断线后查询已收分片，从断点续传
⑤ POST /api/v1/upload/abort     → 放弃上传，清理临时分片
```

- 分片大小：常规 2MB，视频 8MB（服务端可配）。
- **断点续传**：`status` 接口返回已收分片号列表，Agent 跳过已有分片继续传。
- **秒传**：`init` 携带 sha256，平台已存在同哈希文件则直接登记，零字节传输。

## 8. 指令接收与回执

### HTTP 轮询（默认通道）

```
GET  /api/v1/device/commands/pending     → 待执行指令列表（服务端置为 sent）
POST /api/v1/device/commands/{cmd_id}/ack → 执行结果回执
```

回执格式：

```json
{ "status": "acked", "result": { "file": "IMG_xxx.jpg", "media_id": 12 } }
```

`status` 取值：`acked` 成功 / `failed` 失败（附 `error`）。轮询间隔建议 10~30 秒，
收到指令后立即执行并回执。

### MQTT 实时下发（可选增强）

订阅 `edge/{node_uid}/cmd`，payload 与 HTTP 下发的 `command` 表结构一致；
执行后向 `edge/{node_uid}/cmd/ack` 发布回执。两条通道共用同一状态机，业务无差异。

指令超时（默认 60 秒）由平台 `POST /commands/scan-timeout` 扫描置为 `timeout`。

---

## 9. MQTT 主题一览（可选增强）

| 方向 | 主题 | QoS | 载荷 |
| --- | --- | --- | --- |
| 上行 | `edge/{uid}/telemetry` | 1 | 同 §4（批量数组） |
| 上行 | `edge/{uid}/heartbeat` | 0 | 同 §5 |
| 上行 | `edge/{uid}/event` | 1 | 媒体完成、异常等事件通知 |
| 上行 | `edge/{uid}/cmd/ack` | 1 | 同 §8 回执 |
| 上行 | `edge/{uid}/log` | 1 | 同 §6 |
| 下行 | `edge/{uid}/cmd` | 1 | 指令 |
| 下行 | `edge/{uid}/config` | 1 | 配置推送（上报周期等） |

EMQX 部署后，在平台 `系统运维` 中启用 MQTT 并配置地址与账号即可；EMQX 的
HTTP 认证回调指向 `POST /api/v1/device/mqtt-auth`，实现设备级准入。

## 10. 辅助接口

| 接口 | 说明 |
| --- | --- |
| `GET /api/v1/device/config` | 拉取节点当前生效配置（上报周期等） |
| `GET /api/v1/device/time` | 服务器时间（Agent 校时，避免时钟漂移影响时间戳） |
