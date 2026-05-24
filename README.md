# GitHub Project Dataset

前后端分离的 GitHub 开源项目雷达：后端每天采集 GitHub 热门、新星和 star 增长加速项目，保存历史快照，计算榜单，并可使用 DeepSeek 做项目摘要、分类和质量分析；前端独立展示榜单和搜索筛选。

## 项目结构

```text
backend/     FastAPI + MySQL + GitHub API + DeepSeek
frontend/    Vite + React + TypeScript
docker-compose.yml
```

## 后端功能

- GitHub Search API 候选项目采集
- 已入库仓库每天都会刷新一次快照，即使当天不再热门
- 每天额外发现最多 1000 个热门候选项目
- MySQL 保存项目基础信息和每日快照
- 热门榜、新星榜、加速榜评分
- DeepSeek 分析入口，默认只分析榜单候选
- FastAPI 查询接口
- APScheduler 定时任务
- Redis 可选缓存

## 后端启动

1. 启动 MySQL 和 Redis：

```bash
docker compose up -d
```

2. 安装依赖：

```bash
cd backend
cp .env.example .env
pip install -e .
```

3. 修改 `backend/.env` 中的 MySQL、GitHub Token、DeepSeek Key。

4. 初始化数据库并启动后端：

```bash
python -m app.db.init_db
uvicorn app.main:app --reload
```

5. 手动跑一次采集：

```bash
python -m app.jobs.run_daily
```

## 前端启动

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

前端默认运行在 `http://localhost:5173`，后端默认运行在 `http://127.0.0.1:8000`。

## 后端 API

- `GET /api/rankings/hot`
- `GET /api/rankings/rising`
- `GET /api/rankings/momentum`
- `GET /api/repos/{owner}/{repo}`
- `POST /api/jobs/daily`

## 排名思路

项目每天写入一条快照，通过 `1d / 7d / 30d` star 增量和归一化增长率计算榜单。总 star 高的老项目会进入热门榜，但新星榜和加速榜会用项目年龄、增长率和 `sqrt(stars)` 归一化抑制大项目长期霸榜。
