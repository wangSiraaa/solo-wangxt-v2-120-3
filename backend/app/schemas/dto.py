"""Pydantic API 模式。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StationOut(BaseModel):
    id: int
    code: str
    name: str
    lon: float
    lat: float
    elevation_m: float
    network: str

    class Config:
        from_attributes = True


class ScenarioOut(BaseModel):
    id: int
    key: str
    title: str
    description: str
    teaching_note: str
    true_lon: float
    true_lat: float
    true_depth_km: float
    true_origin_epoch: float
    data_version: str

    class Config:
        from_attributes = True


class PickOut(BaseModel):
    id: int
    station_code: str
    station_lon: float
    station_lat: float
    phase: str
    raw_time_epoch: Optional[float]
    raw_status: str
    true_time_epoch: float
    manual_time_epoch: Optional[float]
    manual_note: str
    manual_author: str
    manual_updated_at: Optional[datetime]

    # 供波形/表格使用的派生字段
    effective_time_epoch: Optional[float]  # COALESCE(manual, raw)
    effective_source: str                  # manual | raw | missing
    raw_minus_true_s: Optional[float]
    manual_minus_true_s: Optional[float]


class ManualPickIn(BaseModel):
    manual_time_epoch: Optional[float] = Field(
        default=None, description="人工修订到时；传 null 清除修订（不删除原始拾取）"
    )
    note: str = ""
    author: str = "student"


class LocateRequest(BaseModel):
    scenario_key: str
    phase: str = Field(pattern="^[PpSs]$", description="单次定位只允许单一震相")
    model_id: str
    robust: bool = False
    label: str = ""
    exclude_pick_ids: List[int] = Field(default_factory=list)


class RunSummary(BaseModel):
    id: int
    label: str
    phase: str
    model_id: str
    robust: bool
    locatable: bool
    status: str
    reason: Optional[str]
    n_used: int
    dof: int
    lon: Optional[float]
    lat: Optional[float]
    depth_km: Optional[float]
    origin_time_epoch: Optional[float]
    rms_s: Optional[float]
    max_abs_residual_s: Optional[float]
    data_version: str
    pick_data_version: str
    created_at: datetime

    class Config:
        from_attributes = True


class RunDetail(RunSummary):
    residuals: List[dict]
    uncertainty: Optional[dict]
    geometry: Optional[dict]
    truth: Optional[dict]
    warnings: List[str]
    pick_schema_version: str
    app_version: str
    input_snapshot: List[dict]
    excludes: List[int]


class WaveformOut(BaseModel):
    station_code: str
    channel: str
    starttime_epoch: float
    sampling_rate: float
    # 为绘图降采样后的数组
    times_s: List[float]
    counts: List[float]
    picks: List[dict]
