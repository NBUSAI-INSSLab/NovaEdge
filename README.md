# NovaEdge · 边缘智算管理平台

面向 **树莓派 / 香橙派 等边缘计算节点** 的数据接入与管理平台。节点侧周期性采集
**图像、视频与传感器数据**并上传；平台侧完成设备管理、时序存储、媒体归档、告警判定与
远程指令下发。

- **技术栈**：Flask 3 + SQLAlchemy 2 + Vue 3 + Vite + Pinia + ECharts
- **数据库**：测试用 SQLite（零依赖开箱即用），生产一键切换 **MySQL**
- **上行协议**：HTTP 分片上传（媒体） + MQTT 遥测订阅（可选增强）
- **下行协议**：MQTT 实时下发优先，HTTP 轮询兜底
- **控制台实时推送**：SSE（Server-Sent Events）

---

## 1. 目录结构

```
NovaEdge/
├── backend/                     # 平台服务端（Flask）
│   ├── app/
│   │   ├── models/              # 17 张表的 ORM 定义
│   │   ├── api/                 # 13 个蓝图 / 92 个接口
│   │   ├── services/            # 遥测入库、告警引擎、事件总线、文件存储
│   │   ├── protocols/           # MQTT 接入与下发、设备认证回调
│   │   └── utils/               # 设备认证、JWT、统一响应
│   ├── config.py                # 配置中心（SQLite / MySQL 切换）
│   ├── init_db.py               # 建表 + 演示数据 + 签发设备凭证
│   ├── run.py                   # 启动入口
│   ├── data/                    # SQLite 库文件、设备凭证
│   └── storage/                 # 图片 / 视频 / 缩略图 归档
├── frontend/                    # 控制台（Vue 3 + Vite）
│   └── src/
│       ├── views/               # 10 个页面（物模型并入「系统运维」选项卡）
│       ├── components/          # 表格、弹窗、图表、图标库等
│       ├── stores/              # Pinia：用户 / 实时通道 / 提示
│       └── styles/theme.css     # 海蓝主题
├── node_agent/                  # 边缘节点 Agent（树莓派/香橙派上运行）
│   ├── agent.py                 # 主循环：心跳 / 遥测 / 指令 / 抓拍 / 录像
│   ├── collectors/              # 传感器多后端 + 摄像头多后端
│   ├── uploader.py              # 小文件直传 + 大文件分片 + 断点续传 + 秒传
│   ├── spool.py                 # 断网本地缓存，恢复后自动补传
│   └── config.example.yaml      # 节点配置模板
├── scripts/
│   └── simulate_nodes.py        # 多节点数据模拟器（用于演示与验证）
└── docs/                        # 架构、协议、数据库、部署文档
```

---

## 2. 快速开始（本机验证，SQLite）

### 2.1 启动后端

```bash
cd backend

# 1) 安装依赖（建议使用独立虚拟环境）
pip install -r requirements.txt

# 2) 建表 + 写入演示数据 + 签发 5 个节点的设备凭证
python init_db.py --seed

# 3) 启动服务（默认 http://127.0.0.1:5000）
python run.py
```

启动后控制台账号：

| 账号 | 密码 | 角色 | 权限 |
| --- | --- | --- | --- |
| `admin` | `admin123` | 管理员 | 全部功能 |
| `operator` | `operator123` | 运维 | 设备/告警/指令操作 |
| `viewer` | `viewer123` | 只读 | 仅查看 |

`init_db.py --seed` 会把 5 个节点的 `access_key / secret` 写入
`backend/data/device_credentials.json`，供边缘 Agent 读取（secret 仅此一次明文显示）。

### 2.2 启动前端控制台

```bash
cd frontend
npm install
npm run dev          # 开发模式，默认 http://127.0.0.1:5173
```

生产构建（构建产物由 Flask 直接托管，单端口部署）：

```bash
npm run build        # 输出到 frontend/dist，访问 http://127.0.0.1:5000 即可
```

### 2.3 跑一个边缘节点 Agent

```bash
cd node_agent
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 把 backend/data/device_credentials.json 中对应节点的 access_key / secret 填入 config.yaml
python agent.py
```

开发机上无真实硬件时，`sensors.backends` 配 `["system", "mock"]`、
`camera.backend` 配 `mock`，即可产生真实格式的传感器数据与图片/视频。

### 2.4 一键灌入演示数据（推荐首次体验）

```bash
python scripts/simulate_nodes.py --hours 24 --interval 300 --images 5 --videos 1 --big-video
```

该脚本会为 5 个节点回填 24 小时遥测（含跨越告警阈值的波动段）、上传图片与视频，
其中首个节点会生成 **> 1MB 的视频以验证分片上传通道**。

---

## 3. 生产部署（MySQL）

```bash
# Windows
set DB_TYPE=mysql
set MYSQL_HOST=127.0.0.1
set MYSQL_USER=novaedge
set MYSQL_PASSWORD=******
set MYSQL_DB=novaedge

# Linux / macOS
export DB_TYPE=mysql MYSQL_HOST=127.0.0.1 MYSQL_USER=novaedge \
       MYSQL_PASSWORD=****** MYSQL_DB=novaedge
```

```bash
cd backend
python init_db.py --seed     # 建表（MySQL 下同样生效）
python run.py                # 生产环境建议用 gunicorn / waitress 承载
```

> 说明：数据库字段类型对 SQLite / MySQL 双兼容（自增主键使用
> `BigInteger().with_variant(Integer, "sqlite")`），业务代码零改动。

生产环境下开启 MQTT（可选，需先部署 EMQX）：

```bash
set MQTT_ENABLED=1
set MQTT_HOST=127.0.0.1
set MQTT_PORT=1883
set MQTT_USERNAME=novaedge
set MQTT_PASSWORD=******
```

未开启 MQTT 时，平台完全依赖 HTTP 通道，功能不受影响。

---

## 4. 核心约定

- **设备认证**：节点侧使用 `X-Node-Key` + `X-Node-Secret` 请求头，凭证以 PBKDF2
  散列存储；与 Web 用户的 JWT 体系完全隔离。
- **时间**：统一以 **naive UTC** 落库，序列化时补 `Z`，前端自动转北京时间展示。
- **告警判定**：按 **数据产生时间戳**（而非服务端处理时刻）计算「持续 N 秒越限」，
  因此断网补传的历史数据与实时数据结论一致。
- **媒体访问**：`<img>` / `<video>` 无法携带请求头，媒体预览接口支持
  `?token=` 查询参数鉴权。

---

## 5. 进一步阅读

| 文档 | 内容 |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | 整体架构、协议选型（含主流平台调研结论） |
| [`docs/protocol.md`](docs/protocol.md) | 平台 ↔ 节点 接口协议详细定义 |
| [`docs/database.md`](docs/database.md) | 17 张数据表设计与说明 |
| [`docs/api.md`](docs/api.md) | 92 个 HTTP 接口清单 |
| [`docs/deployment.md`](docs/deployment.md) | 生产部署（MySQL + Nginx + EMQX） |

## 智能管家（AI Agent）

「智能管家」页面内置平台专属智能体，具备三大能力：

- **查数据**：自然语言查询节点状态、遥测统计、告警、数据资产、指令记录、系统概况（12 个内置工具）
- **配系统**：通过对话修改/新建告警规则、向节点下发控制指令（operator/admin 专属，写审计日志，只读角色自动拦截）
- **出报告**：一键生成平台运行分析报告（Markdown，含概况/节点/采集/告警/资产/建议六章），可下载、可删除

引擎为双模：
- **大模型驱动**：在页面「设置」中配置任意 OpenAI 兼容接口（DeepSeek / 通义 / Kimi / 智谱 / 本地 Ollama 等），
  智能体通过 function calling 自主选择工具、多步推理
- **内置规则引擎**（默认，无需任何密钥）：关键词意图识别 + 直连工具查询，开箱即用

新增接口前缀 `/api/v1/butler`：`POST /chat`、`GET /messages`、`GET /sessions`、
`POST /reports/generate`、`GET /reports`、`GET /reports/:id`、`DELETE /reports/:id`、
`GET /reports/:id/download`、`GET|PUT /config`、`POST /config/test`、`GET /tools`。

数据表：`butler_message`（会话消息与工具轨迹）、`butler_report`（分析报告与数据快照）。
