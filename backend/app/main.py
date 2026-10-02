"""FastAPI 入口。启动时幂等播种合成数据。"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import catalog, location_routes, waveforms
from .core.config import CORS_ORIGINS
from .seed import seed

app = FastAPI(
    title="地震定位教学系统 TeachLoc",
    version="1.0.0",
    description=(
        "基于几个台站波形到时恢复候选事件位置的教学工具。"
        "**非地震预警系统**：结果仅在标注的简化均匀半空间速度模型下成立。"
    ),
)
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
app.include_router(catalog.router)
app.include_router(waveforms.router)
app.include_router(location_routes.router)


@app.on_event("startup")
def _startup_seed():
    # 环境变量 SKIP_SEED=1 时跳过（如容器中只读卷）
    if os.environ.get("SKIP_SEED") != "1":
        seed()
