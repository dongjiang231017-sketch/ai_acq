# 协同开发规则

这份文档给团队成员阅读，`AGENTS.md` 给 Codex 代理优先读取。两份规则保持一致：代码用 Git 协作，表结构用 Alembic 协作，数据本身不要靠本地数据库互相拷贝。

## 推荐工作流

1. 从远程仓库拉代码。
2. 从 `dev` 新建功能分支。
3. 本地开发和验证。
4. 提交代码。
5. 发 Pull Request / Merge Request。
6. 至少一位同事 review 后合并。

```bash
git checkout dev
git pull
git checkout -b feature/leads-import
```

## 本地环境

每个同事本机都应该有自己的 PostgreSQL 数据库：

```text
Database: ai_acq_qian
User: 当前 macOS 用户或本机 PostgreSQL 用户
```

复制配置：

```bash
cd backend
cp .env.example .env
```

根据本机情况修改：

```env
DATABASE_URL=postgresql+psycopg:///ai_acq_qian
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123456
ADMIN_SECRET_KEY=replace-this-with-a-long-random-string
```

`.env` 不提交 Git。

## 数据库表结构协作

所有表结构变化必须通过 migration：

```bash
cd backend
source .venv/bin/activate
alembic revision --autogenerate -m "add lead address"
alembic upgrade head
```

其他同事拉代码后执行：

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

禁止直接在数据库客户端里改表结构。数据库客户端只用于查看数据、编辑测试数据、排查问题。

## 共享测试库

本地开发使用各自数据库。需要联调时可以单独建共享测试库，例如：

```text
ai_acq_qian_dev
```

共享测试库只用于联调，不保存重要数据。任何人执行 migration 前都要先在群里同步。

## 代码目录

```text
backend/                         FastAPI 后端
backend/app/models/              SQLAlchemy 数据模型
backend/app/schemas/             API 入参/出参 schema
backend/app/api/                 API 路由
backend/app/admin.py             SQLAdmin 后台配置
backend/migrations/versions/     Alembic 迁移文件
frontend/                        React/Vite 前端
videohao-client-ui-preview-v0.5.0/ 客户确认 UI 原型
```

## 提交前检查

后端：

```bash
cd backend
source .venv/bin/activate
python -m compileall app migrations
alembic check
pip check
```

前端：

```bash
cd frontend
npm run build
```

## 代码评审重点

- 是否提交了 `.env`、密码、本地数据库、虚拟环境或构建产物。
- 是否遗漏 Alembic 迁移。
- migration 是否会误删表或字段。
- API schema 是否和 model 匹配。
- SQLAdmin 是否需要同步增加管理入口。
- 前端是否能连接正确后端地址。

## Codex 使用规则

团队成员用 Codex 开发时，开头先要求 Codex：

```text
请先阅读 AGENTS.md、README.md 和 docs/COLLABORATION.md，然后按规则完成本次任务。
```

如果任务涉及数据库，必须要求 Codex：

```text
所有表结构变更必须生成 Alembic migration，并运行 alembic check。
```

如果任务涉及提交，必须要求 Codex：

```text
提交前运行后端/前端检查，不要提交 .env、node_modules、.venv、dist、本地数据库。
```
