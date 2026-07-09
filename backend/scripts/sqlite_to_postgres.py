"""SQLite → PostgreSQL 数据迁移脚本.

前提: 目标 PG 库已通过 `alembic upgrade head` 建好 schema（含 alembic_version）。

用法（在 backend 目录、后端 venv 里执行）:
    python scripts/sqlite_to_postgres.py \
        --sqlite sqlite:////opt/ai_acq/shared/data/ai_acq.db \
        --postgres "postgresql+psycopg://ai_acq:<密码>@127.0.0.1:5432/ai_acq" \
        --truncate

说明:
- 按外键依赖顺序 (Base.metadata.sorted_tables) 逐表复制。
- 通过 app 模型的列类型读 SQLite（Boolean 0/1、DateTime 字符串、JSON 文本
  都会被正确反序列化），再写入 PG，避免手工类型转换。
- --truncate: 先清空目标表（逆序），便于重跑。
- 复制完成后重置所有整型自增主键的序列。
- alembic_version 不复制（由 alembic 自己管理）。
- 结束时逐表核对行数，任何不一致即退出码 1。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, select, text  # noqa: E402

import app.models  # noqa: F401,E402  (注册所有模型)
from app.db.session import Base  # noqa: E402

BATCH_SIZE = 1000
SKIP_TABLES = {"alembic_version"}


def copy_table(src_conn, dst_conn, table) -> tuple[int, int]:
    """把一张表从源连接复制到目标连接，返回 (源行数, 写入行数)."""
    src_count = src_conn.execute(
        select(func.count()).select_from(table)
    ).scalar_one()
    if src_count == 0:
        return 0, 0

    result = src_conn.execution_options(stream_results=True).execute(table.select())
    keys = result.keys()
    written = 0
    while True:
        rows = result.fetchmany(BATCH_SIZE)
        if not rows:
            break
        payload = [dict(zip(keys, row)) for row in rows]
        dst_conn.execute(table.insert(), payload)
        written += len(payload)
    return src_count, written


def reset_sequences(dst_conn, tables) -> None:
    for table in tables:
        pk_cols = list(table.primary_key.columns)
        if len(pk_cols) != 1:
            continue
        pk = pk_cols[0]
        if not pk.autoincrement or pk.type.python_type is not int:
            continue
        seq = dst_conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"),
            {"t": table.name, "c": pk.name},
        ).scalar()
        if not seq:
            continue
        dst_conn.execute(
            text(
                f"SELECT setval('{seq}', "
                f"COALESCE((SELECT MAX({pk.name}) FROM {table.name}), 0) + 1, false)"
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, help="源库 URL, 如 sqlite:////path/ai_acq.db")
    parser.add_argument("--postgres", required=True, help="目标库 URL, 如 postgresql+psycopg://u:p@h/db")
    parser.add_argument("--truncate", action="store_true", help="复制前清空目标表")
    parser.add_argument("--dry-run", action="store_true", help="只统计行数, 不写入")
    args = parser.parse_args()

    src_engine = create_engine(args.sqlite, connect_args={"check_same_thread": False})
    dst_engine = create_engine(args.postgres)

    tables = [t for t in Base.metadata.sorted_tables if t.name not in SKIP_TABLES]

    # 目标库必须已有 schema
    with dst_engine.connect() as c:
        missing = [
            t.name
            for t in tables
            if not c.execute(text("SELECT to_regclass(:n)"), {"n": t.name}).scalar()
        ]
    if missing:
        print(f"[错误] 目标库缺表(先跑 alembic upgrade head): {missing}")
        return 1

    summary: list[tuple[str, int, int]] = []
    with src_engine.connect() as src_conn:
        if args.dry_run:
            for table in tables:
                n = src_conn.execute(select(func.count()).select_from(table)).scalar_one()
                summary.append((table.name, n, 0))
            for name, n, _ in summary:
                print(f"  {name:<40} {n}")
            print("[dry-run] 未写入任何数据")
            return 0

        with dst_engine.begin() as dst_conn:
            if args.truncate:
                for table in reversed(tables):
                    dst_conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
            for table in tables:
                src_n, written = copy_table(src_conn, dst_conn, table)
                summary.append((table.name, src_n, written))
                print(f"  {table.name:<40} {src_n:>6} → {written}")
            reset_sequences(dst_conn, tables)

    # 独立连接核对行数
    failed = False
    with dst_engine.connect() as c:
        for name, src_n, _ in summary:
            dst_n = c.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            if dst_n != src_n:
                print(f"[不一致] {name}: 源 {src_n} vs 目标 {dst_n}")
                failed = True
    if failed:
        return 1
    print(f"[完成] {len(summary)} 张表全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
