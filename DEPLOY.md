# 部署说明

这个项目是前后端分离：

- 后端：FastAPI，默认监听 `8010`
- 前端：Vite 构建后的静态文件，建议用 Nginx 托管

你现在的 MySQL、Redis、GitHub Token、DeepSeek 配置可以保持不变。部署到服务器时，主要只需要改域名相关配置。

## 1. 服务器环境

建议使用 Ubuntu 22.04 或更新版本。

```bash
sudo apt update
sudo apt install -y git curl nginx python3.11 python3.11-venv python3-pip
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

检查版本：

```bash
python3.11 --version
node -v
npm -v
nginx -v
```

## 2. 上传代码

如果代码在 Git 仓库：

```bash
cd /opt
sudo git clone <你的仓库地址> github-project-dataset
sudo chown -R $USER:$USER /opt/github-project-dataset
cd /opt/github-project-dataset
```

如果不用 Git，也可以直接把整个项目目录上传到：

```text
/opt/github-project-dataset
```

## 3. 后端配置

进入后端目录：

```bash
cd /opt/github-project-dataset/backend
cp .env.example .env
```

编辑 `.env`：

```bash
nano .env
```

数据库、Redis、GitHub、DeepSeek 这些配置保持你现在的值即可：

```env
DATABASE_URL=你的当前数据库连接
GITHUB_TOKEN=你的当前 GitHub Token
REDIS_URL=你的当前 Redis 地址
REDIS_PASSWORD=你的当前 Redis 密码
DEEPSEEK_API_KEY=你的当前 DeepSeek Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=你的当前模型
AI_ENABLED=false
```

`AI_ENABLED` 是 AI 分析总开关。

前期部署不想启用 AI，就保持：

```env
AI_ENABLED=false
```

这样不会影响榜单、搜索、评分、趋势图等基础功能，只是页面里的单仓库 AI 分析按钮会显示为未启用。

后期要启用 AI 时，改成：

```env
AI_ENABLED=true
```

然后重启后端即可：

```bash
sudo systemctl restart github-radar-backend
```

需要改的是 `CORS_ORIGINS`。

如果你有域名：

```env
CORS_ORIGINS=https://你的域名
```

如果暂时只用服务器 IP：

```env
CORS_ORIGINS=http://你的服务器IP
```

是否启用后端定时采集：

```env
SCHEDULER_ENABLED=true
```

当前代码里定时任务是每天北京时间：

- 08:00 采集一次
- 20:00 采集一次

如果你暂时不想自动采集，就保持：

```env
SCHEDULER_ENABLED=false
```

## 4. 安装后端依赖并初始化数据库

```bash
cd /opt/github-project-dataset/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
python -m app.db.init_db
```

测试后端能否启动：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

另开一个终端测试：

```bash
curl http://127.0.0.1:8010/api/health
```

正常应该返回：

```json
{"status":"ok"}
```

测试没问题后，按 `Ctrl+C` 停掉临时启动。

## 5. 用 systemd 托管后端

创建服务文件：

```bash
sudo tee /etc/systemd/system/github-radar-backend.service >/dev/null <<'EOF'
[Unit]
Description=GitHub Radar FastAPI Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/github-project-dataset/backend
Environment=PATH=/opt/github-project-dataset/backend/.venv/bin
ExecStart=/opt/github-project-dataset/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now github-radar-backend
sudo systemctl status github-radar-backend
```

检查后端：

```bash
curl http://127.0.0.1:8010/api/health
```

查看后端日志：

```bash
sudo journalctl -u github-radar-backend -f
```

## 6. 构建前端

推荐前端和后端使用同一个域名，通过 Nginx 把 `/api` 转发给后端。

这种方式下，前端的 API 地址留空即可：

```bash
cd /opt/github-project-dataset/frontend
cat > .env.production <<'EOF'
VITE_API_BASE_URL=
EOF
npm ci
npm run build
```

如果你的前端和后端不是同一个域名，比如：

```text
前端：https://你的域名
后端：https://api.你的域名
```

那 `.env.production` 写：

```env
VITE_API_BASE_URL=https://api.你的域名
```

然后再执行：

```bash
npm ci
npm run build
```

## 7. 配置 Nginx

推荐结构：

```text
https://你的域名
  ├─ /       前端页面
  └─ /api/   转发到后端 127.0.0.1:8010
```

创建 Nginx 配置：

```bash
sudo tee /etc/nginx/sites-available/github-radar >/dev/null <<'EOF'
server {
    listen 80;
    server_name 你的域名;

    root /opt/github-project-dataset/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8010/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF
```

如果你暂时没有域名，只用服务器 IP，把这一行：

```nginx
server_name 你的域名;
```

改成：

```nginx
server_name _;
```

启用 Nginx 配置：

```bash
sudo ln -s /etc/nginx/sites-available/github-radar /etc/nginx/sites-enabled/github-radar
sudo nginx -t
sudo systemctl reload nginx
```

现在访问：

```text
http://你的域名
```

或者：

```text
http://你的服务器IP
```

## 8. 配置 HTTPS

如果你有域名，建议配置 HTTPS：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

HTTPS 配好后，把后端 `.env` 的 `CORS_ORIGINS` 改成：

```env
CORS_ORIGINS=https://你的域名
```

然后重启后端：

```bash
sudo systemctl restart github-radar-backend
```

## 9. 常用维护命令

查看后端状态：

```bash
sudo systemctl status github-radar-backend
```

查看后端日志：

```bash
sudo journalctl -u github-radar-backend -f
```

重启后端：

```bash
sudo systemctl restart github-radar-backend
```

重新构建前端：

```bash
cd /opt/github-project-dataset/frontend
npm ci
npm run build
sudo systemctl reload nginx
```

手动执行一次每日采集：

```bash
cd /opt/github-project-dataset/backend
source .venv/bin/activate
python -m app.jobs.run_daily
```

手动检查后端健康状态：

```bash
curl http://127.0.0.1:8010/api/health
```

## 10. 部署前注意事项

不要把 `.env` 提交到公开仓库。

你的 `.env` 里有：

- 数据库密码
- Redis 密码
- GitHub Token
- DeepSeek API Key

如果这些信息已经传到公开仓库，建议立即重新生成 GitHub Token 和 DeepSeek Key。

生产环境推荐：

- 后端只监听 `127.0.0.1:8010`
- 不直接暴露后端端口到公网
- 只开放 Nginx 的 `80` 和 `443`
- 前端和后端同域部署，避免 CORS 问题
