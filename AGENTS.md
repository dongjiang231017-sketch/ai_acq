# Codex 协同开发规则

本文件适用于整个仓库。所有使用 Codex 参与本项目开发的人，在开始任何代码修改前必须先阅读本文件和 `README.md`。

## 基本原则

- 不要提交密钥、密码、`.env`、虚拟环境、`node_modules`、构建产物或本地数据库文件。
- 不要直接修改生产或共享数据库表结构。所有表结构变更必须通过 SQLAlchemy model + Alembic migration 完成。
- 不要在没有用户明确要求的情况下重置、回滚或删除他人的改动。
- 不要把 UI 原型目录 `videohao-client-ui-preview-v0.5.0/` 当作正式源码改造；正式前端源码在 `frontend/`。
- 后端 API、数据库 model、schema、admin view、迁移文件要保持同步。
- 提交前必须运行可用的检查命令，并在最终回复里说明运行结果。

## 分支规则

- `main`：稳定主分支，只接收已验证代码。
- `dev`：日常集成分支。
- `feature/<name>`：功能分支，例如 `feature/leads-import`。
- `fix/<name>`：修复分支，例如 `fix/admin-login`。

不要直接在 `main` 上开发复杂功能。不要 force push 到 `main` 或 `dev`。

## 数据库规则

新增或修改表字段时必须按顺序执行：

1. 修改 `backend/app/models/` 里的 SQLAlchemy model。
2. 同步修改 `backend/app/schemas/` 里的 Pydantic schema。
3. 如果需要后台可视化管理，同步修改 `backend/app/admin.py`。
4. 生成迁移：

```bash
cd backend
source .venv/bin/activate
alembic revision --autogenerate -m "describe change"
```

5. 检查迁移文件内容，确认没有误删表、误删字段。
6. 应用迁移：

```bash
alembic upgrade head
```

7. 提交 model、schema、admin view、migration。

禁止用 TablePlus、DBeaver、pgAdmin 直接改表结构后再补代码。

## 后端开发命令

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

提交前至少运行：

```bash
cd backend
source .venv/bin/activate
python -m compileall app migrations
alembic check
pip check
```

## 前端开发命令

```bash
cd frontend
npm install
npm run dev
```

提交前至少运行：

```bash
cd frontend
npm run build
```

## 后台管理

- SQLAdmin 地址：`http://localhost:8001/admin`
- 后台账号来自 `backend/.env`，不要提交真实密码。
- 新增业务表后，如果运营需要可视化管理，需要在 `backend/app/admin.py` 增加对应 `ModelView`。

## 提交规范

提交信息使用简短英文动词开头：

- `init fullstack project`
- `add lead import model`
- `fix admin auth`
- `update collaboration docs`

一个提交只做一类事情。不要把格式化、重构、功能、迁移混在一个大提交里。

## Codex 回复要求

Codex 完成任务后必须说明：

- 修改了哪些关键文件。
- 是否新增或修改了数据库迁移。
- 运行了哪些验证命令。
- 是否有未完成事项或需要人工配置的内容。
