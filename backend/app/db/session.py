from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
elif settings.database_url.startswith("postgresql"):
    # 2026-07-09：数据库在云端（101.132.63.159），本地程序走公网连接。
    # 阿里云链路会静默回收空闲 TCP，连接池里的死连接被复用时报
    # "consuming input failed: could not receive data from server: Operation timed out"
    # （高德采集 6 条全部入库失败即此因）。TCP keepalive + 定期回收连接根治。
    _engine_kwargs["connect_args"] = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
        "connect_timeout": 10,
    }
    _engine_kwargs["pool_recycle"] = 300

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
