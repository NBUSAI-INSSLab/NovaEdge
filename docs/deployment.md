# 生产部署指南

## 1. 环境要求

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Linux（Ubuntu 22.04 / Debian 12 推荐）或 Windows Server |
| Python | ≥ 3.10 |
| Node.js | ≥ 18（仅构建前端需要；构建产物可直接由 Flask 托管） |
| MySQL | ≥ 8.0（utf8mb4） |
| EMQX（可选） | ≥ 5.0，启用 MQTT 增强通道时需要 |
| ffprobe（可选） | 探测视频时长；未安装时视频时长字段为空，不影响其他功能 |

## 2. 数据库初始化（MySQL）

```sql
CREATE DATABASE novaedge DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'novaedge'@'%' IDENTIFIED BY '强密码';
GRANT ALL PRIVILEGES ON novaedge.* TO 'novaedge'@'%';
FLUSH PRIVILEGES;
```

## 3. 后端部署

```bash
# 目录约定：/opt/novaedge
cd /opt/novaedge/backend

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 环境变量（写入 systemd 或 .env）
export DB_TYPE=mysql
export MYSQL_HOST=127.0.0.1
export MYSQL_USER=novaedge
export MYSQL_PASSWORD=强密码
export MYSQL_DB=novaedge
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export JWT_SECRET_KEY=$SECRET_KEY

# 建表 + 初始数据（已部署过的库不会重复写演示数据）
python init_db.py --seed
```

### WSGI 服务（生产必读）

Flask 自带开发服务器（`run.py`）**不适合生产**。推荐两种方式：

**方式一：Waitress（Windows / Linux 通用，纯 Python）**

```bash
pip install waitress
waitress-serve --host=0.0.0.0 --port=5000 --threads=16 run:app
```

**方式二：Gunicorn + gevent（Linux，SSE 场景更省资源）**

```bash
pip install gunicorn
gunicorn -k gevent -w 2 -b 0.0.0.0:5000 --timeout 0 run:app
```

> SSE 是长连接：`--timeout 0` 关闭 worker 超时；gevent 协程模型下少量线程即可承载
> 大量空闲 SSE 连接。若用多进程（`-w > 1`），事件总线为进程内实现，SSE 客户端只会
> 收到自己所在进程产生的事件 —— 生产如需多进程，建议 SSE 请求按会话粘性或改用
> Redis Pub/Sub 广播（预留扩展点：`app/services/events.py` 的 `bus`）。

### systemd 服务示例

```ini
# /etc/systemd/system/novaedge.service
[Unit]
Description=NovaEdge IoT Platform
After=network.target mysql.service

[Service]
WorkingDirectory=/opt/novaedge/backend
Environment=DB_TYPE=mysql
Environment=MYSQL_HOST=127.0.0.1
Environment=MYSQL_USER=novaedge
Environment=MYSQL_PASSWORD=强密码
Environment=MYSQL_DB=novaedge
ExecStart=/opt/novaedge/backend/.venv/bin/waitress-serve \
          --host=0.0.0.0 --port=5000 --threads=16 run:app
Restart=always

[Install]
WantedBy=multi-user.target
```

## 4. 前端构建与托管

```bash
cd /opt/novaedge/frontend
npm install && npm run build     # 产物 dist/
```

两种托管方式任选：

- **单端口（简单）**：Flask 已内置 SPA 托管（`app/__init__.py` 指向 `frontend/dist`），
  构建后直接由后端服务，无需 Nginx 静态配置。
- **Nginx 托管（推荐）**：静态资源走 Nginx，动态请求反代后端。

## 5. Nginx 配置示例

```nginx
server {
    listen 80;
    server_name iot.example.com;
    client_max_body_size 64m;          # 分片大小上限之上留余量

    # 前端静态资源
    root /opt/novaedge/frontend/dist;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # SSE 必须关闭缓冲与超时
    location /api/v1/stream/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;           # 关键：否则事件被缓冲，前端收不到实时推送
        proxy_read_timeout 3600s;
    }
}
```

## 6. MQTT（EMQX，可选增强）

1. 部署 EMQX（Docker 一行：`docker run -d -p 1883:1883 -p 18083:18083 emqx/emqx:5`）。
2. 平台环境变量开启：

```bash
export MQTT_ENABLED=1
export MQTT_HOST=127.0.0.1
export MQTT_PORT=1883
export MQTT_USERNAME=novaedge
export MQTT_PASSWORD=强密码
```

3. EMQX Dashboard → Authentication → 添加 **HTTP Server** 认证，
   请求地址 `http://127.0.0.1:5000/api/v1/device/mqtt-auth`（POST，JSON body 含
   `username / password`），实现「MQTT 接入凭证 = 设备凭证」的统一准入。
4. 未启用 MQTT 时平台完全走 HTTP 通道，功能不受影响。

## 7. 边缘节点（树莓派 / 香橙派）部署

```bash
# 建议 Python 3.9+（系统自带或 pyenv）
cd ~/edge_agent
pip install -r node_agent/requirements.txt

cp node_agent/config.example.yaml node_agent/config.yaml
vi config.yaml     # 填入 node_uid / access_key / secret / server.base_url

# 开机自启（systemd）
sudo tee /etc/systemd/system/edge-agent.service <<'EOF'
[Unit]
Description=NovaEdge Node Agent
After=network-online.target

[Service]
WorkingDirectory=/home/pi/edge_agent
ExecStart=/usr/bin/python3 agent.py --config config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now edge-agent
```

## 8. 上线检查清单

- [ ] `SECRET_KEY` / `JWT_SECRET_KEY` 已改为随机值
- [ ] 默认账号 `admin/admin123`、`operator/operator123`、`viewer/viewer123` 已改密或禁用
- [ ] MySQL 使用独立账号最小权限，库已 utf8mb4
- [ ] Nginx `proxy_buffering off` 已生效（SSE 实时性）
- [ ] `client_max_body_size` ≥ 分片大小
- [ ] 存储 `backend/storage/` 目录磁盘容量与备份策略已规划
- [ ] 首个节点注册成功并完成一次「抓拍 → 上传 → 媒体库可见」闭环
- [ ] 遥测到达后告警规则触发 / 恢复验证一遍
