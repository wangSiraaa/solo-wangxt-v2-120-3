"""数据库引擎与会话。

PostgreSQL + PostGIS：DATABASE_URL=postgresql+psycopg2://...，台站表额外含
geom geometry(Point,4326)（见 db/postgis.sql 与 init_db 中的建列逻辑），
邻近台站查询走 ST_DWithin；未配置时回退到本地 SQLite 文件，邻近查询用
Haversine，接口行为一致，便于课堂上无数据库环境也能运行。
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .core.config import DATABASE_URL, IS_POSTGIS

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    if IS_POSTGIS:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            # 若台站表尚无 geom 列则补上，并从经纬度填充
            conn.execute(text(
                "ALTER TABLE stations ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326)"
            ))
            conn.execute(text(
                "UPDATE stations SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326) "
                "WHERE geom IS NULL AND lon IS NOT NULL"
            ))
            # 定位结果中的候选解也以 GeoJSON 文本保存，同时支持几何列查询
            conn.execute(text(
                "ALTER TABLE location_runs ADD COLUMN IF NOT EXISTS solution_geom geometry(Point, 4326)"
            ))
