"""应用配置。

教学项目默认使用本地 SQLite（零依赖即可运行）；设置 DATABASE_URL 指向
PostgreSQL/PostGIS 后自动切换（见 db/postgis.sql 中的建表与几何列定义）。

这是**教学演示系统**，不是地震预警产品：定位结果只在简化速度模型下成立。
"""
from __future__ import annotations

import os


def _default_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    path = os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(__file__), "..", "teachloc.db"))
    return "sqlite:///" + os.path.abspath(path)


DATABASE_URL: str = _default_db_url()
IS_POSTGIS: bool = DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg2://"))

# 数据/模型版本：定位结果与这些版本绑定，任何一个变化都应触发重算
DATA_VERSION: str = os.environ.get("DATA_VERSION", "synth-v1.0")
PICK_SCHEMA_VERSION: str = "pick-schema-v1"
APP_VERSION: str = "teachloc-v1.0"

# CORS（Vite 默认端口 5173）
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
