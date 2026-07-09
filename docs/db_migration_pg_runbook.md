# 云端 PostgreSQL 数据库（2026-07-09 重建）

> 架构决策（用户拍板）：**云服务器只当数据库**，后端/语音等程序全部在本地跑，远程连库。
> 服务器 101.132.63.159 于 2026-07-09 18:00 重装系统（原 SQLite 数据弃用），现为宝塔面板 + PostgreSQL。

## 服务器现状

- 宝塔面板：`https://101.132.63.159:22283/9f338277`（CentOS 7，面板 v11.8.1 企业版）
- PostgreSQL 16.10（宝塔 PostgreSQL 管理器编译安装）
  - 安装目录 `/www/server/pgsql`，数据目录 `/www/server/pgsql/data`，日志 `/www/server/pgsql/logs/`
  - `listen_addresses='*'`，端口 5432，firewalld 已放行，开机自启（`chkconfig pgsql on`）
  - 服务管理：`/etc/init.d/pgsql start|stop|restart`（无 systemd unit）
- 数据库 `ai_acq`，用户 `ai_acq`，密码见宝塔 数据库→PgSQL 页（点密码列可见/复制）
- pg_hba 白名单（只放行 ai_acq 库/用户）：
  - `127.0.0.1/32`（本机）
  - `183.216.25.116/32`（办公室出口 IP，2026-07-09 确认）

## 本地接入

`backend/.env` 或环境变量：

```
DATABASE_URL=postgresql+psycopg://ai_acq:<密码>@101.132.63.159:5432/ai_acq
```

首次建 schema（本地 backend 目录、venv 内）：

```bash
export DATABASE_URL='postgresql+psycopg://ai_acq:<密码>@101.132.63.159:5432/ai_acq'
alembic upgrade head    # 迁移链 0001→0ea9dfe9e60d 全新建表
```

## 办公室 IP 变了怎么办

宝塔终端执行（把 <新IP> 换掉）：

```bash
sed -i 's|183.216.25.116/32|<新IP>/32|' /www/server/pgsql/data/pg_hba.conf
su - postgres -c "/www/server/pgsql/bin/pg_ctl -D /www/server/pgsql/data reload"
```

## 已知坑（这次踩过的）

1. 宝塔面板建库后 pg_hba.conf 末行**没有换行符**，直接 `echo >>` 追加会把两行拼一起导致 PG 起不来
   （报 `invalid authentication method "md5host"`）。追加前先 `echo >> ` 空行或检查末行。
2. 连不上先查三层：pg_hba 白名单 IP → 服务器 firewalld（5432 已开）→ **阿里云安全组**
   （控制台 ECS→安全组，若入方向没放行 5432 需手动加）。
3. 服务器重装后 SSH 免密没了；服务器操作现走宝塔面板终端。

## 备份

建议在宝塔 数据库→PgSQL 页对 `ai_acq` 开自动备份（上线后）。

## 备用脚本

`backend/scripts/sqlite_to_postgres.py`：SQLite→PG 全量数据迁移（按外键序复制+序列重置+行数核对）。
本次因数据弃用未使用；若以后要把本地 SQLite 数据搬上云端 PG 可直接用。
