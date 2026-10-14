# API 接口清单

前缀：`/api/v1`。共 **13 个蓝图 / 93 个接口**。
Web 接口使用 `Authorization: Bearer <JWT>`；设备接口使用 `X-Node-Key / X-Node-Secret` 请求头。

统一响应：`{ "code": 0, "message": "…", "data": … }`，分页响应 `data` 内含
`items / total / page / page_size`。

## auth — 认证（4）

| 方法 | 路径 | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/auth/login` | 登录，返回 JWT 与用户信息 | 公开 |
| GET | `/auth/profile` | 当前用户信息 | 登录 |
| POST | `/auth/change-password` | 修改密码 | 登录 |
| POST | `/auth/logout` | 退出 | 登录 |

## users — 用户与审计（6，仅 admin）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/users` | 用户列表 |
| POST | `/users` | 新建用户 |
| PUT | `/users/{id}` | 修改用户（角色/状态/资料） |
| DELETE | `/users/{id}` | 删除用户 |
| GET | `/users/roles` | 角色字典 |
| GET | `/users/audit-logs` | 操作审计日志 |

## nodes — 节点管理（16）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/nodes` | 节点列表（分页、关键字、状态、分组、类型筛选） |
| POST | `/nodes` | 新建节点（签发设备凭证） |
| GET | `/nodes/specs` | 类型 / 状态 / 上报周期 字典 |
| GET / PUT / DELETE | `/nodes/{id}` | 详情 / 修改 / 删除（级联清理） |
| POST | `/nodes/{id}/toggle` | 启用 / 禁用 |
| POST | `/nodes/{id}/reset-credential` | 重置设备凭证 |
| GET | `/nodes/latest-all` | **全部节点最新值快照**（单次批量，监控页专用） |
| GET | `/nodes/{id}/latest` | 单节点最新值 |
| GET | `/nodes/{id}/telemetry` | 历史遥测（按 metric / hours / points 降采样） |
| GET | `/nodes/{id}/heartbeats` | 心跳历史（资源曲线） |
| GET | `/nodes/{id}/logs` | 节点日志 |
| GET | `/nodes/{id}/statistics` | 节点数据统计 |
| GET / POST | `/nodes/groups` | 分组列表 / 新建 |
| PUT / DELETE | `/nodes/groups/{id}` | 分组修改 / 删除 |

## metrics — 物模型（5）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/metrics` | 指标定义列表 |
| GET | `/metrics/categories` | 指标分类字典 |
| POST | `/metrics` | 新增指标 |
| GET / PUT / DELETE | `/metrics/{id}` | 详情 / 修改 / 删除（系统指标禁删） |

## media — 媒体资产（9）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/media` | 媒体列表（节点 / 类型 / 关键字 / 日期范围筛选） |
| GET | `/media/statistics` | 统计（总数、图/视频数、占用空间、近 7 天趋势、节点分布） |
| GET | `/media/uploads` | 上传会话列表（含进行中的分片） |
| GET | `/media/{id}` | 详情 |
| GET | `/media/{id}/raw` | 原始文件预览（**支持 `?token=`**） |
| GET | `/media/{id}/thumb` | 缩略图（**支持 `?token=`**） |
| GET | `/media/{id}/download` | 下载（attachment） |
| PUT | `/media/{id}` | 修改备注 / 标签 |
| DELETE / POST `/media/batch-delete` | 删除 / 批量删除（含磁盘文件） |

## alerts — 告警中心（10）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/alerts/dicts` | 级别 / 状态 字典 |
| GET / POST | `/alerts/rules` | 规则列表 / 新建 |
| PUT / DELETE | `/alerts/rules/{id}` | 规则修改 / 删除 |
| GET | `/alerts/records` | 告警记录（状态 / 级别 / 节点 / 时间筛选） |
| POST | `/alerts/records/{id}/ack` | 确认 |
| POST | `/alerts/records/{id}/clear` | 手动清除 |
| POST | `/alerts/records/batch-ack` | 批量确认 |
| GET | `/alerts/summary` | 汇总（活跃数、今日新增、规则数、级别分布） |

## commands — 指令中心（6）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/commands/catalog` | 指令目录（7 条内置指令及参数说明） |
| GET | `/commands` | 指令列表（状态 / 节点筛选） |
| POST | `/commands` | 下发指令 |
| GET | `/commands/{id}` | 指令详情（含回执） |
| POST | `/commands/{id}/cancel` | 取消 |
| POST | `/commands/scan-timeout` | 扫描超时指令 |
| GET | `/commands/pending/count` | 待处理计数 |

## dashboard — 总览（7）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/dashboard/overview` | 核心指标卡（节点数、今日数据量、媒体数、活跃告警、均值资源） |
| GET | `/dashboard/node-distribution` | 节点状态 / 类型分布 |
| GET | `/dashboard/trend` | 上报趋势（支持 6/24/72 小时） |
| GET | `/dashboard/top-nodes` | 数据量 TOP 节点 |
| GET | `/dashboard/recent` | 最近事件流 |
| GET | `/dashboard/metric-ranking` | 指标样本量排行 |
| GET | `/dashboard/offline-nodes` | 离线节点列表 |

## system — 系统运维（7）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/system/health` | 健康检查（含数据库连通性） |
| GET | `/system/info` | 系统信息（版本、运行环境、数据库类型） |
| GET / PUT | `/system/configs` `/system/configs/{key}` | 系统配置读取 / 修改 |
| POST | `/system/maintenance/rollup` | 手动触发小时聚合 |
| POST | `/system/maintenance/cleanup` | 数据清理（按保留天数） |
| GET | `/system/storage-usage` | 存储占用分析 |

## stream — 实时推送（2，SSE）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/stream/events` | SSE 事件流（`?token=` 鉴权；事件：connected / telemetry / node / alert / media / command / system） |
| GET | `/stream/status` | 当前订阅数 |

## device — 设备侧（9，`X-Node-Key/Secret` 认证）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/device/register` | 节点注册（幂等） |
| POST | `/device/telemetry` | 批量遥测上报 |
| POST | `/device/heartbeat` | 心跳上报 |
| POST | `/device/logs` | 日志上报 |
| GET | `/device/config` | 拉取配置 |
| GET | `/device/time` | 服务器时间（校时） |
| GET | `/device/commands/pending` | 拉取待执行指令（HTTP 轮询下行通道） |
| POST | `/device/commands/{cmd_id}/ack` | 指令回执 |
| POST | `/device/mqtt-auth` | EMQX HTTP 认证回调 |

## upload — 设备侧上传（7，设备认证）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/upload/direct` | 小文件直传 |
| POST | `/upload/init` | 分片初始化（含 sha256 秒传判定） |
| POST | `/upload/chunk` | 上传分片 |
| POST | `/upload/complete` | 完成合并 |
| POST | `/upload/abort` | 放弃上传 |
| GET | `/upload/status/{upload_id}` | 断点续传进度查询 |
| GET | `/upload/sessions` | 会话列表 |
