# 数据库设计

共 **17 张表**，分为六组。测试环境用 SQLite，生产用 MySQL 8 —— 模型层通过
`BigInteger().with_variant(Integer, "sqlite")` 实现主键类型双兼容，业务代码零改动。

| 分组 | 表 | 说明 |
| --- | --- | --- |
| 设备 | `node` · `node_group` · `node_credential` · `node_heartbeat` · `node_log` | 节点档案、分组、凭证、心跳、日志 |
| 时序 | `metric_def` · `telemetry` · `telemetry_latest` · `telemetry_hourly` | 物模型 + 三层时序存储 |
| 媒体 | `media_file` · `upload_session` | 媒体归档 + 分片上传会话 |
| 告警 | `alert_rule` · `alert_record` | 规则与触发记录 |
| 指令 | `command` | 下行指令与状态机 |
| 系统 | `user` · `audit_log` · `sys_config` | 用户、审计、配置 |

---

## 1. 设备组

### node — 节点档案（29 列）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `node_uid` | VARCHAR(64) 唯一 | 节点唯一编码，如 `RPI-LAB-A01` |
| `name` / `node_type` / `model` / `serial_no` | — | 名称 / 类型（树莓派、香橙派、Jetson…）/ 硬件型号 / 序列号 |
| `group_id` | FK → node_group | 分组归属 |
| `ip_address` / `mac_address` / `os_version` / `agent_version` | — | 注册时上报的网络与版本信息 |
| `location` / `longitude` / `latitude` | — | 部署位置（文本 + 经纬度） |
| `capabilities` | JSON | 能力声明，如 `["camera","ds18b20","dht22"]` |
| `status` | VARCHAR(16) | online / offline / disabled（由心跳超时判定，`HEARTBEAT_TIMEOUT=180s`） |
| `last_seen_at` / `uptime_seconds` | — | 最近在线时刻 / 运行时长 |
| `cpu_percent` / `mem_percent` / `disk_percent` / `cpu_temp` | FLOAT | 最近一次心跳的资源快照（冗余存储，列表页免查询明细） |
| `report_interval` | INTEGER | 上报周期（秒），节点按此调度 |
| `enabled` | BOOLEAN | 禁用后拒绝接入 |

### node_credential — 设备凭证（12 列）

| 字段 | 说明 |
| --- | --- |
| `access_key` | 明文存储（相当于用户名，`ak_` 前缀） |
| `secret_hash` | **PBKDF2 散列**存储，secret 明文仅在创建/重置时展示一次 |
| `mqtt_username` / `mqtt_password` | 预留 MQTT 接入凭证 |
| `is_active` / `expires_at` / `last_used_at` | 启用状态 / 过期时间 / 最近使用 |

### node_group / node_heartbeat / node_log

- `node_group`：分组（支持 `parent_id` 层级、`sort_order` 排序）。
- `node_heartbeat`：每次心跳一行（CPU/内存/磁盘/温度/网速/进程数/时长），用于资源趋势曲线。
- `node_log`：节点上报的运行日志（level / module / message）。

---

## 2. 时序组（三层存储）

### metric_def — 物模型（19 个预置指标）

`metric_key`（唯一）· `name` · `data_type`(number/string/boolean/enum) · `unit` ·
`category`(environment/system/electric/visual/security) · `min_value` / `max_value` /
`precision`（量程与精度）· `enum_options` · `applicable_type`（适用节点类型）· `is_system`。

预置指标：空气温度/湿度、光照、CO₂、PM2.5、噪声、人流、电压、电流、SoC 温度、
CPU/内存/磁盘使用率、网速、运行时长等。

### telemetry — 明细层

| 字段 | 说明 |
| --- | --- |
| `node_id` + `metric_key` + `ts` | 复合索引，全部明细查询走此索引 |
| `value_num` / `value_str` | 数值与字符串双列，兼容两类指标 |
| `ts` | **BIGINT 毫秒时间戳**（数据产生时刻，非入库时刻） |
| `quality` | 质量位（预留：0 正常 / 1 估算 / 2 异常） |

### telemetry_latest — 快照层（联合主键 node_id + metric_key）

每节点每指标仅一行，上报时 upsert。看板 / 列表 / 监控页的「最新值」直接查此表，
复杂度 O(1)，不扫明细。

### telemetry_hourly — 聚合层

`(node_id, metric_key, bucket_ts)` 每小时一行，记录 avg / min / max / 样本数。
由系统管理的定时任务 `rollup_hour()` 生成，长周期趋势图用聚合层降采样。

---

## 3. 媒体组

### media_file（21 列）

| 字段 | 说明 |
| --- | --- |
| `file_type` | image / video |
| `storage_path` / `thumb_path` | 归档路径（`storage/日期/节点/`）与缩略图路径 |
| `file_size` / `mime_type` / `sha256` | 大小 / 类型 / 哈希（**秒传**的判重依据） |
| `width` / `height` / `duration_sec` | 图片宽高 / 视频时长（ffprobe 探测） |
| `captured_at` | 采集时刻（由节点上报，可能是历史时间） |
| `source` | capture / record / manual |
| `tags` / `meta` / `remark` | 标签、扩展元数据、备注 |

### upload_session — 分片上传会话（18 列）

`upload_id` · `file_size` · `chunk_size` · `total_chunks` / `received_chunks`（断点续传进度）·
`sha256`（合并后校验）· `temp_dir`（分片临时目录）· `status`(uploading/merging/done/aborted/expired) ·
`media_file_id`（完成后回链）· `expires_at`（TTL 24h，过期清理）。

---

## 4. 告警组

### alert_rule（17 列）

| 字段 | 说明 |
| --- | --- |
| `node_id` / `group_id` | 二选一：作用于单节点或整组（都空 = 全局） |
| `metric_key` + `operator` + `threshold` (+ `threshold2`) | 比较表达式，支持区间类（between/outside） |
| `duration_sec` | **持续越限时长**（秒）—— 达标才触发，防瞬时抖动 |
| `severity` | info / warning / major / critical |
| `silence_sec` | 静默期，防重复告警 |
| `enabled` / `trigger_count` | 启用状态 / 历史触发次数 |

### alert_record（16 列）

`rule_id` · `node_id` · `metric_key` · `severity` · `title` / `content`（人可读的触发描述）·
`trigger_value` / `clear_value` · `status`(active/acked/cleared) · `count`（静默期内累加次数）·
`started_at`（**首次越限的数据时间戳**）· `acked_at`/`acked_by` · `cleared_at`。

---

## 5. 指令组

### command（15 列）

| 字段 | 说明 |
| --- | --- |
| `cmd_id` | 业务幂等 ID（UUID） |
| `command` | 指令码（capture / record / reboot / set_interval / upgrade_agent / exec_script / sync_time） |
| `params` | JSON 参数 |
| `status` | `pending → sent → acked / failed / timeout`，另有 `cancelled` |
| `channel` | 实际下发通道：`mqtt` / `http-poll` |
| `result` | 节点回执 JSON |
| `issued_by` / `timeout_sec` / `retry_count` | 下发人 / 超时 / 重试 |
| `issued_at` / `sent_at` / `ack_at` | 三阶段时刻 |

---

## 6. 系统组

- `user`：账号（PBKDF2 密码散列）· `role`(admin/operator/viewer) · 登录信息。
- `audit_log`：操作审计（who / action / target / detail / ip）。
- `sys_config`：键值配置（`cfg_value` 为 JSON），如数据保留天数、聚合开关。

---

## 设计要点回顾

1. **主键双兼容**：`BigInteger().with_variant(Integer, "sqlite")`，同一模型跑两种库。
2. **时间统一 naive UTC 落库**，序列化补 `Z`，前端转本地时区。
3. **读写分离的表结构**：写入只碰 `telemetry` + `telemetry_latest`（upsert），
   读路径按场景选层（快照 → 聚合 → 明细）。
4. **级联清理**：删除节点时同步清理遥测、媒体文件（含磁盘文件）、告警、指令。
