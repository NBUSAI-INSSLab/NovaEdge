# NovaEdge 架构设计

## 1. 需求与设计目标

边缘节点为 **树莓派 / 香橙派** 等边缘计算设备，常态下就地采集与处理 **图像** 与
**传感器数据**，周期性上传到平台。据此提炼出以下设计目标：

| 目标 | 具体要求 |
| --- | --- |
| 两类数据差异化管理 | 传感器数据「高频、小包、可批量」；图像/视频「低频、大包、需断点续传」 |
| 弱网可用 | 边缘节点常见 4G / 工业 WiFi 抖动，必须支持断网缓存与恢复补传 |
| 实时性 | 控制台需实时看到节点上线、遥测、告警、指令回执 |
| 可演进 | 从 5 个节点扩展到数百节点时，存储与接入层不能推倒重来 |
| 易部署 | 开发用 SQLite 零依赖启动，生产切 MySQL 不改代码 |

---

## 2. 主流平台调研结论

| 平台 | 协议 | 技术栈 | 结论 |
| --- | --- | --- | --- |
| **ThingsBoard** | MQTT / CoAP / HTTP | Java + Kafka + PostgreSQL | 功能全，但组件重、二次开发成本高 |
| **JetLinks** | MQTT / HTTP / TCP | Java + Vert.x | 国内生态好，仍属重型 Java 体系 |
| **阿里云 IoT / 华为 IoTDA** | MQTT | 云服务 | 托管省心，私有化与定制受限 |
| **Home Assistant** | MQTT | Python | 偏智能家居，缺少媒体归档与分片上传 |
| **EMQX** | MQTT Broker | Erlang | **只做消息底座，不做业务** —— 作为接入层被选型 |

**最终选型：`EMQX（MQTT 消息底座） + 自研业务层（Flask + Vue）`**。

理由：

1. 业务语义（设备模型、分片上传、告警持续判定、媒体归档）没有现成平台能零改造覆盖；
2. Flask / Vue 技术栈轻量、易读、易私有化部署，符合高校与中小规模工业场景；
3. MQTT 只作为**可选增强通道**——未部署 EMQX 时，HTTP 单通道即可完整跑通全部功能。

---

## 3. 总体架构

```
┌──────────────────────────────── 边缘侧 ────────────────────────────────┐
│  树莓派 / 香橙派 / Jetson                                            │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ node_agent.py                                                │    │
│  │  ├ SensorHub  ── system / mock / ds18b20 / dht22 / ads1115   │    │
│  │  ├ Camera     ── auto / mock / picamera2 / opencv / ffmpeg   │    │
│  │  ├ Uploader   ── 小文件直传 · 大文件分片 · 断点续传 · 秒传    │    │
│  │  └ Spool      ── 断网本地落盘，恢复后按序补传                │    │
│  └──────────────────────────────────────────────────────────────┘    │
└───────────────┬──────────────────────────────────┬───────────────────┘
                │ ① HTTP（主通道，始终可用）        │ ② MQTT（可选增强）
                │   X-Node-Key / X-Node-Secret     │   EMQX Broker
                ▼                                  ▼
┌──────────────────────────────── 平台侧 ────────────────────────────────┐
│  Flask 应用（create_app 应用工厂）                                     │
│  ├ api/        13 蓝图 · 92 接口（web 侧 JWT / 设备侧 Header 双认证）  │
│  ├ services/   telemetry_service · alert_engine · storage · events    │
│  ├ protocols/  MQTTIngest（订阅上行）· MQTTPublisher（实时下发）      │
│  └ models/     17 张表（设备 / 时序 / 媒体 / 告警 / 指令 / 审计）      │
│                                                                       │
│  存储：SQLite（开发） ──切换──▶ MySQL 8（生产）                        │
│        storage/ 目录：原图 · 视频 · 缩略图（按 日期/节点 分片）        │
└───────────────┬───────────────────────────────────────────────────────┘
                │ ③ SSE 单向推送（/api/v1/stream/events）
                ▼
┌──────────────────────────────── 控制台 ───────────────────────────────┐
│  Vue 3 + Vite + Pinia + Vue Router + ECharts                          │
│  11 个页面 · 海蓝主题 · 扁平化图标（自绘 SVG）· 纯中文 UI             │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 4. 协议设计

### 4.1 上行：节点 → 平台

采用 **HTTP 为主 + MQTT 为辅** 的双通道设计，两者写入同一套业务逻辑，互不冲突。

| 数据类型 | 通道 | 接口 | 说明 |
| --- | --- | --- | --- |
| 传感器遥测 | HTTP | `POST /api/v1/device/telemetry` | 支持批量数组，一次可提交多条 |
| 传感器遥测 | MQTT | `edge/{uid}/telemetry` | QoS 1，可选增强 |
| 资源心跳 | HTTP | `POST /api/v1/device/heartbeat` | CPU / 内存 / 磁盘 / 温度 |
| 运行日志 | HTTP | `POST /api/v1/device/logs` | 分级日志 |
| **图片 / 视频** | HTTP | `/api/v1/upload/init → chunk → complete` | 分片上传 + 断点续传 + 秒传 |
| 小文件（< 1MB） | HTTP | `/api/v1/upload/direct` | 单请求直传，省去三次握手 |

**为什么媒体走 HTTP 分片而不是 MQTT？**
MQTT 面向小消息（默认单包上限 256MB，但 broker 通常限制在 MB 级），且缺少
「偏移量续传」语义。媒体文件动辄数十 MB，用 HTTP 分片天然支持：
`init` 登记会话 → `chunk` 按序号上传 → `complete` 合并校验 sha256。
断线后只需查询 `GET /upload/status/{upload_id}` 得知已收到的分片，从断点继续。

**秒传**：`init` 阶段提交文件 sha256，若平台已存在同样 sha256 的媒体，直接返回
`instant=true`，不再传输字节。

### 4.2 下行：平台 → 节点

| 通道 | 机制 | 适用 |
| --- | --- | --- |
| MQTT（优先） | 发布 `edge/{uid}/cmd`，QoS 1 | 已部署 EMQX，期望毫秒级 |
| HTTP（兜底） | 节点轮询 `GET /api/v1/device/commands/pending` | 无 MQTT 环境，默认方案 |

两条通道 **共用同一张 `command` 表与同一套状态机**
（`pending → sent → acked / failed / timeout / cancelled`），
`command.channel` 字段记录实际下发通道，因此业务层无需感知差异。

指令执行后节点回调 `POST /api/v1/device/commands/{cmd_id}/ack` 上报回执，
平台写入结果并通过 SSE 广播给控制台。

### 4.3 控制台实时推送：SSE 而非 WebSocket

控制台只需 **服务端 → 浏览器** 的单向推送（节点上线、遥测到达、告警产生、指令回执），
不需要浏览器向服务端推消息。因此选择 SSE：

- 浏览器原生 `EventSource` **自动断线重连**，无需手写心跳与重连逻辑；
- 纯 HTTP，**无需 Nginx 升级协议 / 额外依赖**，部署零成本；
- Flask 侧只需一个生成器 + 进程内事件总线。

事件总线 `services/events.py` 为**进程内有界队列**，慢客户端会被丢弃最旧事件而非阻塞
生产者，保证高频遥测下不会拖垮服务。前端 `stores/realtime.js` 支持**多页面按 key 注册
处理器**，多个页面共用同一条 SSE 连接而互不覆盖。

> 注意：SSE 要求 Flask 以多线程模式运行（`run.py` 中 `threaded=True`）。

---

## 5. 认证与安全

平台存在**两类完全隔离的身份**：

| | Web 用户 | 边缘设备 |
| --- | --- | --- |
| 载体 | `Authorization: Bearer <JWT>` | `X-Node-Key` + `X-Node-Secret` |
| 校验 | Flask-JWT-Extended | `device_auth_required` 装饰器 |
| 存储 | 密码 PBKDF2 散列 | 凭证 secret PBKDF2 散列 |
| 权限 | admin / operator / viewer 三级 | 仅能操作自己的数据 |
| 生效范围 | `/api/v1/{nodes,media,alerts,...}` | `/api/v1/device/*`、`/api/v1/upload/*` |

**媒体访问的特殊处理**：`<img src>` 与 `<video src>` 无法携带自定义请求头，
因此媒体预览接口（`/media/{id}/raw`、`/thumb`）额外支持 `?token=<JWT>`
查询参数鉴权（`flexible_login_required`），既保证安全又让浏览器原生标签可用。

节点首次接入流程：控制台「新建节点」→ 平台生成凭证并**仅显示一次** →
运维把 `access_key / secret` 写入节点 `config.yaml` → 节点 `POST /device/register` 激活。
凭证泄露可通过「重置凭证」立即失效旧 secret。

---

## 6. 数据流：一条遥测的完整旅程

```
1. 节点采集      SensorHub 读到 {temperature: 25.6, humidity: 58.2}
2. 本地组包      POST /api/v1/device/telemetry  {samples:[{metric_key,value,ts}, ...]}
                 ├─ 断网 → 写入 Spool 本地缓存，恢复后按时间序补传
                 └─ 正常 → 继续
3. 设备鉴权      device_auth_required 校验 X-Node-Key/Secret
4. 入库（事务）  telemetry_service.ingest_telemetry()
                 ├─ telemetry            明细表，逐条插入
                 ├─ telemetry_latest     最新值快照 upsert（看板秒开）
                 └─ node.last_seen_at    刷新在线状态
5. 告警判定      alert_engine.evaluate_series(node, series)
                 └─ 以【数据时间戳】判定「持续 N 秒越限」，命中则写 alert_record
6. 实时广播      events.publish("telemetry" / "alert", payload)
                 └─ SSE 推送到所有已连接的控制台
7. 控制台渲染    stores/realtime.js 收到事件 → 页面局部刷新 / ECharts 追加数据点
```

关键点：**第 5 步使用数据时间戳而非服务端处理时刻**。否则节点断网 2 小时后补传，
历史数据会被当成「刚刚发生」，导致「持续越限 60 秒」判定完全失真。

---

## 7. 时序数据分层存储

传感器数据随时间线性增长，直接查明细表会迅速变慢。平台采用三层结构：

| 层 | 表 | 写入时机 | 用途 |
| --- | --- | --- | --- |
| 物模型层 | `metric_def` | 人工维护 | 指标定义：单位、类型、精度、分类、是否可告警 |
| 明细层 | `telemetry` | 每次上报 | 历史曲线、条件查询、导出 |
| 快照层 | `telemetry_latest` | 每次上报（upsert） | 看板/列表页取「每节点每指标最新值」，避免扫明细 |
| 聚合层 | `telemetry_hourly` | 定时任务 `rollup_hour()` | 查询长周期趋势时降采样，减少数据量 |

看板与监控页读快照层（O(1) 命中），详情页画曲线读明细层，趋势图读聚合层 ——
各页面按需要选择最省的层，避免「所有查询都扫明细表」。

---

## 8. 告警引擎

告警规则支持「比较符 + 阈值 + **持续时长**」三元组，例如：

```
temperature > 32.0℃ 且持续 60 秒  → major  「机房温度过高」
person_count > 20 人 且持续 10 秒 → warning 「人员聚集预警」
```

评估逻辑（`services/alert_engine.py`）：

1. 遥测入库时把**同一批次的完整样本序列**交给 `evaluate_series()`；
2. 引擎按数据时间戳升序遍历样本，记录「首次命中时刻」；
3. 当 `样本时间 - 首次命中时间 >= 规则持续时长` 时触发告警；
4. 条件不再满足且越过恢复阈值时，自动置为 `cleared` 并记录 `cleared_at`；
5. **静默期防抖**：同一规则同一节点在静默期内不重复产生告警记录，而是累加 `count`。

由于全程以数据时间戳为键，**回填 24 小时历史数据与实时上报得到完全一致的告警结论**。

---

## 9. 数据库设计要点

- **主键双兼容**：`BigInteger().with_variant(Integer, "sqlite")`
  —— MySQL 用 BIGINT，SQLite 用 INTEGER（SQLite 自增主键必须是 INTEGER），
  一份模型跑两种库。
- **时间统一**：全部以 naive UTC 落库（`utcnow()` 助手），序列化时补 `Z` 后缀，
  前端按浏览器时区自动转换，避免服务器与客户端时区不一致。
- **索引**：`telemetry` 在 `(node_id, metric_key, ts)` 上建复合索引，
  明细查询与聚合均走索引。
- **级联**：节点删除时级联清理遥测、媒体、告警、指令，避免孤儿数据。

详见 [`database.md`](database.md)。

---

## 10. 前端设计

| 维度 | 方案 |
| --- | --- |
| 框架 | Vue 3 `<script setup>` + Vite + Pinia + Vue Router |
| 图表 | ECharts **按需引入**（仅注册用到的图表与组件），gzip 后约 208KB |
| 图标 | **自绘 SVG 图标库**（`AppIcon.vue`，60+ 图标），零第三方图标依赖、风格统一 |
| 主题 | CSS 变量集中管理，海蓝主色 + 扁平化，纯中文 UI |
| 实时 | 单条 SSE 连接，多页面按 key 注册处理器 |
| 部署 | `npm run build` 产物由 Flask 直接托管，**单端口单进程**即可上线 |

页面清单：登录、总览看板、节点管理、节点详情、实时监控、媒体库、告警中心、
指令中心、指标管理、系统管理、用户管理（共 11 个）。
