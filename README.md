# GitHub Project Dataset

前后端分离的 GitHub 开源项目雷达：后端每天采集 GitHub 热门、新星和 star 增长加速项目，保存到 PostgreSQL，计算榜单；前端展示榜单、搜索筛选、趋势信息，并支持对单个仓库使用 DeepSeek 做 AI 趋势分析。

## 项目结构

```text
backend/     FastAPI + PostgreSQL + GitHub API + DeepSeek + APScheduler
front/       Vite + React + TypeScript
docker-compose.yml
```

## 当前功能

- GitHub Search API 候选项目采集
- 已入库仓库每日刷新快照
- 每天额外发现最多 1000 个热门候选项目
- 已有仓库按优先级刷新 star 快照，避免历史库越大 API 压力越线性增长
- 记录仓库发现来源，例如 topic、语言、新项目、热门项目查询
- 记录每次采集任务的开始/结束、刷新数量、新发现数量、失败数量
- PostgreSQL 保存仓库基础信息、每日快照、每日评分、AI 分析结果
- 热门榜、新星榜、加速榜评分
- 单仓库 DeepSeek AI 趋势分析
- 邮箱验证码登录
- 用户名/邮箱 + 密码登录
- FastAPI 查询接口
- APScheduler 定时任务

## 后端启动

1. 配置环境变量：

```bash
cd backend
cp .env.example .env
```

编辑 `backend/.env`，至少配置：

```env
DATABASE_URL=postgresql+psycopg://postgres:/github_project_dataset
GITHUB_TOKEN=你的 GitHub Token
GITHUB_DAILY_REPO_LIMIT=1000
GITHUB_DAILY_REFRESH_LIMIT=500
DEEPSEEK_API_KEY=你的 DeepSeek Key
AI_ENABLED=true
SCHEDULER_ENABLED=true
SCHEDULER_HOUR=3
SCHEDULER_MINUTE=0
CORS_ORIGINS=
```

邮箱验证码登录需要配置 SMTP：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_account
SMTP_PASSWORD=your_password
SMTP_FROM=your_account@example.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

2. 安装依赖并初始化数据库：

```bash
pip install -e .
python -m app.db.init_db
```

3. 启动后端：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

4. 手动跑一次采集：

```bash
python -m app.jobs.run_daily
```

## 前端启动

```bash
cd front
cp .env.example .env
npm install
npm run dev
```

开发环境默认前端运行在 `http://localhost:5173`，后端运行在 `http://127.0.0.1:8010`。

## 后端 API

认证接口：

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/email-code`
- `POST /api/auth/email-login`
- `GET /api/auth/me`
- `POST /api/auth/logout`

业务接口需要 `Authorization: Bearer <token>`：

- `GET /api/rankings/hot`
- `GET /api/rankings/rising`
- `GET /api/rankings/momentum`
- `GET /api/repos`
- `GET /api/repos/{owner}/{repo}`
- `POST /api/repos/{owner}/{repo}/ai`
- `GET /api/summary`
- `POST /api/jobs/daily`
- `POST /api/jobs/daily/async`
- `GET /api/jobs/daily/status`
- `POST /api/jobs/score`

## 定时采集

开启 `SCHEDULER_ENABLED=true` 后，后端会按北京时间每天 `SCHEDULER_HOUR:SCHEDULER_MINUTE` 自动采集，默认是凌晨 `03:00`。

采集稳定性设计：

- APScheduler 设置 `max_instances=1`，同一个后端进程不会并发跑多个定时采集。
- `run_daily` 内部还有进程内互斥锁，手动触发和定时触发撞车时会跳过后来的任务。
- PostgreSQL advisory lock 会阻止多进程/多实例同时跑同一轮采集。
- 每次采集都会写入 `github_collection_run`，记录成功/失败、刷新数量、发现数量、失败数量。
- 采集失败会记录错误，并更新 `/api/jobs/daily/status`。
- 单个 GitHub 查询或单个仓库失败会计入失败数并继续处理后续数据。
- 已有仓库和候选仓库都使用 upsert，重复执行不会重复创建仓库。

## 排名思路

项目每天写入一条快照，通过 `1d / 7d / 30d` star 增量和归一化增长率计算榜单。总 star 高的老项目会进入热门榜，但新星榜和加速榜会用项目年龄、增长率和 `sqrt(stars)` 归一化抑制大项目长期霸榜。
