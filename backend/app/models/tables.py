"""ORM 模型。

拾取表设计体现"原始拾取与人工修订分开"：
  raw_time_epoch / raw_status 由自动拾取（此处为合成发生器）写入，**永不修改**；
  manual_time_epoch / manual_note / manual_author 由用户修订单独保存。
定位输入采用 COALESCE(manual, raw)，并在 runs.input_snapshot 中留痕。

PickRevision 是人工修订/撤销的**只增不改**操作记录（教学审计日志）：
每次修订或撤销追加一行，保存 manual 字段的前后值、作者、备注与时间。
定位与候选解快照都不读取它——它只用于授课复盘"某个到时是怎样被改过的"。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    lon: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    elevation_m: Mapped[float] = mapped_column(Float, default=0.0)
    network: Mapped[str] = mapped_column(String(8), default="TS")

    picks: Mapped[list["Pick"]] = relationship(back_populates="station")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    teaching_note: Mapped[str] = mapped_column(Text, default="")
    true_lon: Mapped[float] = mapped_column(Float)
    true_lat: Mapped[float] = mapped_column(Float)
    true_depth_km: Mapped[float] = mapped_column(Float)
    true_origin_epoch: Mapped[float] = mapped_column(Float)
    data_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    picks: Mapped[list["Pick"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")
    runs: Mapped[list["LocationRun"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class Pick(Base):
    __tablename__ = "picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    phase: Mapped[str] = mapped_column(String(2), index=True)          # P / S

    # —— 自动（原始）拾取：种子后只读 ——
    raw_time_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_status: Mapped[str] = mapped_column(String(16), default="ok")  # ok/missing/shifted_outlier
    true_time_epoch: Mapped[float] = mapped_column(Float)              # 合成真值（教学用）
    picker_seed: Mapped[int] = mapped_column(Integer, default=0)

    # —— 人工修订：与原始分开，保留修订痕迹 ——
    manual_time_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_note: Mapped[str] = mapped_column(Text, default="")
    manual_author: Mapped[str] = mapped_column(String(64), default="")
    manual_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    station: Mapped[Station] = relationship(back_populates="picks")
    scenario: Mapped[Scenario] = relationship(back_populates="picks")
    revisions: Mapped[list["PickRevision"]] = relationship(
        back_populates="pick", cascade="all, delete-orphan",
        order_by="PickRevision.id",
    )


class PickRevision(Base):
    """一次人工修订/撤销的操作记录（只追加、不修改、不删除）。

    old/new_time_epoch 记录的是 manual 字段的前后值：
      revise：old 为修订前 manual（None 表示此前一直用 raw），new 为新 manual；
      clear ：old 为被撤销的 manual，new 恒为 None（有效到时回到 raw）。
    raw_* 从不出现在这里——原始拾取只读，不存在"改前改后"。
    """
    __tablename__ = "pick_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id"), index=True)
    action: Mapped[str] = mapped_column(String(8))  # revise | clear
    old_time_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_time_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    author: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pick: Mapped[Pick] = relationship(back_populates="revisions")


class LocationRun(Base):
    """一次定位尝试：与速度模型、数据版本和所用输入快照绑定。"""
    __tablename__ = "location_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    phase: Mapped[str] = mapped_column(String(2))
    model_id: Mapped[str] = mapped_column(String(64), index=True)
    robust: Mapped[bool] = mapped_column(Boolean, default=False)

    locatable: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_time_epoch: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_abs_residual_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    residuals: Mapped[list] = mapped_column(JSON, default=list)
    uncertainty: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    truth: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    # —— 可解释/可复算绑定 ——
    data_version: Mapped[str] = mapped_column(String(32))
    pick_schema_version: Mapped[str] = mapped_column(String(32))
    app_version: Mapped[str] = mapped_column(String(32))
    pick_data_version: Mapped[str] = mapped_column(String(64))  # 由拾取状态派生
    input_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    excludes: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="runs")
