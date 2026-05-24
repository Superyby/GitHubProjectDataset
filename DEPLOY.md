# 部署说明

本项目暂不使用 Nginx，部署结构为：

- 后端：FastAPI + uvicorn，监听 `8010`
- 前端：Vite 构建后用 `vite preview` 托管，默认监听 `15000`
- 数据库：远程 PostgreSQL，`8.160.161.184:35672`
- Redis：已移除

## 1. 服务器环境

建议使用 Ubuntu 22.04 或更新版本。

```bash
sudo apt update
sudo apt install -y git curl python3.11 python3.11-venv python3-pip
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## 2. 上传代码

```bash
cd /opt
git clone <你的仓库地址> github-project-dataset
cd /opt/github-project-dataset
```

## 3. 后端配置

```bash
cd /opt/github-project-dataset/backend
cp .env.example .env
nano .env
```

核心配置示例：

```env
DATABASE_URL=postgresql+psycopg://postgres:你的数据库密码@8.160.161.184:35672/github_project_dataset
GITHUB_TOKEN=你的 GitHub Token
GITHUB_DAILY_REPO_LIMIT=1000
GITHUB_DAILY_REFRESH_LIMIT=500
DEEPSEEK_API_KEY=你的 DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
AI_ENABLED=true
SCHEDULER_ENABLED=true
SCHEDULER_HOUR=3
SCHEDULER_MINUTE=0
CORS_ORIGINS=http://你的服务器IP:15000
```

邮箱验证码登录需要 SMTP：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_account
SMTP_PASSWORD=your_password
SMTP_FROM=your_account@example.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

## 4. 安装后端依赖并初始化数据库

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
python -m app.db.init_db
```

测试启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

健康检查：

```bash
curl http://127.0.0.1:8010/api/health
```

正常返回：

```json
{"status":"ok"}
```

## 5. 用 systemd 托管后端

```bash
sudo tee /etc/systemd/system/github-radar-backend.service >/dev/null <<'EOF'
[Unit]
Description=GitHub Radar FastAPI Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/github-project-dataset/backend
Environment=PATH=/opt/github-project-dataset/backend/.venv/bin
ExecStart=/opt/github-project-dataset/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now github-radar-backend
sudo systemctl status github-radar-backend
```

## 6. 构建并托管前端

```bash
cd /opt/github-project-dataset/front
cat > .env.production <<'EOF'
VITE_API_BASE_URL=http://你的服务器IP:8010
EOF
npm ci
npm run build
```

用 systemd 托管 Vite preview：

```bash
sudo tee /etc/systemd/system/github-radar-front.service >/dev/null <<'EOF'
[Unit]
Description=GitHub Radar Frontend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/github-project-dataset/front
ExecStart=/usr/bin/npm run preview -- --host 0.0.0.0 --port 15000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now github-radar-front
sudo systemctl status github-radar-front
```

访问：

```text
http://你的服务器IP:15000
```

## 7. 定时采集

`SCHEDULER_ENABLED=true` 后，后端会每天北京时间 `03:00` 采集一次。也可以通过下面两个配置调整：

```env
SCHEDULER_HOUR=3
SCHEDULER_MINUTE=0
```

服务器部署在新加坡也没关系，代码显式使用 `Asia/Shanghai` 时区。

稳定性策略：

- APScheduler 设置 `max_instances=1` 和 `coalesce=true`，避免同一进程内定时任务堆积。
- `run_daily` 内部有互斥锁，手动触发和定时触发撞车时只跑一个。
- PostgreSQL advisory lock 会阻止多进程/多实例同时跑同一轮采集。
- 每次采集写入 `github_collection_run`，可追踪成功/失败和数量。
- 单个 GitHub 查询或单个仓库失败会计入失败数并继续处理后续数据。
- 仓库主表、每日快照、每日评分均按唯一约束 upsert，重复执行不会重复插入仓库。

手动执行一次每日采集：

```bash
cd /opt/github-project-dataset/backend
source .venv/bin/activate
python -m app.jobs.run_daily
```

## 8. 常用维护命令

```bash
sudo systemctl status github-radar-backend
sudo journalctl -u github-radar-backend -f
sudo systemctl restart github-radar-backend
```

```bash
sudo systemctl status github-radar-front
sudo journalctl -u github-radar-front -f
sudo systemctl restart github-radar-front
```

## 9. 安全注意事项

不要提交 `.env`。其中包含：

- PostgreSQL 密码
- GitHub Token
- DeepSeek API Key
- SMTP 密码

如果暂不使用 Nginx，请在服务器防火墙或云安全组中只开放需要访问的端口，例如 `15000` 和 `8010`。
