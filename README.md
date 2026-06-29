# 视频号团购商家 AI 获客客户端

这个仓库现在包含两部分：

- `videohao-client-ui-preview-v0.5.0/`：客户确认用的静态 UI 原型。
- `frontend/` + `backend/`：后续真正开发功能的前后端源码骨架。

协同开发规则见：

- `AGENTS.md`：给 Codex 代理读取的强制规则。
- `docs/COLLABORATION.md`：给团队成员阅读的协同流程。

## 技术栈

- 前端：TypeScript + React + Vite
- 后端：Python + FastAPI
- 数据库：PostgreSQL
- 可视化数据后台：SQLAdmin
- 数据库迁移：Alembic
- 队列/缓存：Redis
- Docker：暂时不用，等功能稳定后再补

## 本机 PostgreSQL

当前本机已安装 Homebrew PostgreSQL：

```bash
/opt/homebrew/opt/postgresql@18/bin/psql --version
```

启动或检查服务：

```bash
brew services start postgresql@18
brew services list | grep postgresql
```

项目数据库：

```text
ai_acq_qian
```

后端连接配置在 `backend/.env`：

```env
DATABASE_URL=postgresql+psycopg:///ai_acq_qian
```

## 本地启动

### 1. 启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

后端接口文档：

```text
http://localhost:8000/docs
```

可视化后台：

```text
http://localhost:8000/admin
```

默认本地后台账号：

```text
用户名：admin
密码：admin123456
```

后台密码配置在 `backend/.env`，正式部署前必须改掉：

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123456
ADMIN_SECRET_KEY=ai-acq-qian-local-admin-session-key-20260628
```

如果 `8000` 被占用，可以换成：

```bash
uvicorn app.main:app --reload --port 8001
```

对应后台地址就是：

```text
http://localhost:8001/admin
```

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：

```text
http://localhost:5173
```

如果后端用了 `8001`，启动前端时这样写：

```bash
VITE_API_BASE_URL=http://localhost:8001/api npm run dev
```

当前这台机器上 `8000` 已被其他 Python 服务占用，所以本项目的本地前端配置 `frontend/.env` 已指向：

```env
VITE_API_BASE_URL=http://localhost:8001/api
```

## 下一步开发顺序

1. 先用 SQLAdmin 管理基础数据表，快速验证业务字段。
2. 把 UI 原型里的 10 个模块拆成真实路由和页面组件。
3. 先实现线索库、导入/采集、外呼任务这 3 条主流程。
4. 再接平台私信、意向客户池、AI 学习中心。
5. 最后补声音档案、报表、系统设置、权限和审计。

## UC100 实体卡外呼准备

UC100 未到货前，后端默认使用模拟电话网关，可以先开发任务、队列、记录、重拨和人工接管前置流程。到货后再按 `docs/UC100_OUTBOUND_SETUP.md` 接入 Asterisk/UC100。

模拟模式：

```env
TELEPHONY_GATEWAY_MODE=simulator
OUTBOUND_QUEUE_ENABLED=false
```

Redis worker 测试：

```bash
cd backend
source .venv/bin/activate
python -m app.workers.outbound_worker --once
```

查看当前电话网关配置：

```text
GET /api/outbound/telephony/config
```

## 数据库迁移

新增或修改 SQLAlchemy model 后，生成迁移：

```bash
cd backend
source .venv/bin/activate
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

当前数据库迁移版本：

```bash
alembic current
```
