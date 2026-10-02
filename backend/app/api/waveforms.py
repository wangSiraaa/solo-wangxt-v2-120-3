"""波形（ObsPy 解析 MiniSEED）与拾取查询、人工修订。"""
from __future__ import annotations

import hashlib
import os
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from obspy import read
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data import DATA_DIR
from ..database import get_db
from ..models.tables import Pick, Scenario, Station
from ..schemas.dto import ManualPickIn, PickOut

router = APIRouter(prefix="/api/scenarios", tags=["waveforms-picks"])

# 30s × 100Hz 共 3001 点；降到 ~1000 点绘图足够，且保留子波形状
MAX_PLOT_POINTS = 1200


def _pick_out(p: Pick) -> PickOut:
    raw, man = p.raw_time_epoch, p.manual_time_epoch
    if man is not None:
        eff, src = man, "manual"
    elif raw is not None:
        eff, src = raw, "raw"
    else:
        eff, src = None, "missing"
    return PickOut(
        id=p.id, station_code=p.station.code, station_lon=p.station.lon,
        station_lat=p.station.lat, phase=p.phase,
        raw_time_epoch=raw, raw_status=p.raw_status, true_time_epoch=p.true_time_epoch,
        manual_time_epoch=man, manual_note=p.manual_note, manual_author=p.manual_author,
        manual_updated_at=p.manual_updated_at,
        effective_time_epoch=eff, effective_source=src,
        raw_minus_true_s=(round(raw - p.true_time_epoch, 3) if raw is not None else None),
        manual_minus_true_s=(round(man - p.true_time_epoch, 3) if man is not None else None),
    )


@router.get("/{key}/picks", response_model=List[PickOut])
def list_picks(key: str, db: Session = Depends(get_db)):
    sc = _get_scenario(db, key)
    rows = db.scalars(
        select(Pick).where(Pick.scenario_id == sc.id).join(Station)
        .order_by(Station.code, Pick.phase)
    )
    return [_pick_out(p) for p in rows]


class PickDataVersion(BaseModel):
    pick_data_version: str
    n_picks: int
    n_manual: int
    n_missing: int


@router.get("/{key}/picks/version", response_model=PickDataVersion)
def picks_version(key: str, db: Session = Depends(get_db)):
    """拾取数据版本：任何人工修订/状态变化都会改变该哈希，定位与之绑定。"""
    sc = _get_scenario(db, key)
    rows = list(db.scalars(select(Pick).where(Pick.scenario_id == sc.id).order_by(Pick.id)))
    digest = hashlib.sha256()
    for p in rows:
        eff = p.manual_time_epoch if p.manual_time_epoch is not None else p.raw_time_epoch
        digest.update(f"{p.id}:{p.phase}:{p.raw_status}:{eff}:".encode())
    n_manual = sum(1 for p in rows if p.manual_time_epoch is not None)
    n_missing = sum(1 for p in rows if p.raw_time_epoch is None and p.manual_time_epoch is None)
    return PickDataVersion(
        pick_data_version=digest.hexdigest()[:16], n_picks=len(rows),
        n_manual=n_manual, n_missing=n_missing,
    )


@router.patch("/picks/{pick_id}", response_model=PickOut)
def revise_pick(pick_id: int, body: ManualPickIn, db: Session = Depends(get_db)):
    """人工修订：只写 manual_* 字段，raw_* 永不改动。"""
    from datetime import datetime, timezone

    p = db.get(Pick, pick_id)
    if p is None:
        raise HTTPException(404, "拾取不存在")
    p.manual_time_epoch = body.manual_time_epoch
    p.manual_note = body.note
    p.manual_author = body.author or "student"
    p.manual_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)
    return _pick_out(p)


@router.delete("/picks/{pick_id}/manual", response_model=PickOut)
def clear_manual_pick(pick_id: int, db: Session = Depends(get_db)):
    """撤销人工修订，恢复使用原始拾取。"""
    p = db.get(Pick, pick_id)
    if p is None:
        raise HTTPException(404, "拾取不存在")
    p.manual_time_epoch = None
    p.manual_note = ""
    p.manual_author = ""
    p.manual_updated_at = None
    db.commit()
    db.refresh(p)
    return _pick_out(p)


@router.get("/{key}/waveforms/{station_code}")
def get_waveform(key: str, station_code: str, db: Session = Depends(get_db)):
    sc = _get_scenario(db, key)
    station = db.scalar(select(Station).where(Station.code == station_code))
    if station is None:
        raise HTTPException(404, f"台站 {station_code} 不存在")

    mseed = os.path.join(DATA_DIR, key, f"TS.{station_code}.00.BHZ.mseed")
    if not os.path.exists(mseed):
        raise HTTPException(404, f"案例 {key} 不含台站 {station_code} 的波形")

    st = read(mseed, format="MSEED")  # ObsPy 真实解析路径
    tr = st.select(channel="BHZ")[0]
    start = float(tr.stats.starttime)

    # 降采样（简单抽取；合成数据频带远低于奈奎斯特，不会显著混叠）
    step = max(1, int(tr.stats.npts // MAX_PLOT_POINTS))
    data = tr.data.astype(np.float64)[::step]
    times = (np.arange(tr.stats.npts)[::step] / tr.stats.sampling_rate).tolist()

    picks = db.scalars(select(Pick).where(
        Pick.scenario_id == sc.id, Pick.station_id == station.id)).all()
    pick_payload = []
    for p in picks:
        eff = p.manual_time_epoch if p.manual_time_epoch is not None else p.raw_time_epoch
        pick_payload.append({
            "pick_id": p.id, "phase": p.phase,
            "offset_s": (round(eff - start, 3) if eff is not None else None),
            "true_offset_s": round(p.true_time_epoch - start, 3),
            "source": "manual" if p.manual_time_epoch is not None else
                      ("missing" if p.raw_time_epoch is None else "raw"),
            "raw_status": p.raw_status,
        })

    return {
        "station_code": station_code,
        "channel": tr.stats.channel,
        "starttime_epoch": start,
        "sampling_rate": tr.stats.sampling_rate / step,
        "times_s": [round(x, 3) for x in times],
        "counts": [round(float(x), 2) for x in data],
        "picks": pick_payload,
    }


def _get_scenario(db: Session, key: str) -> Scenario:
    sc = db.scalar(select(Scenario).where(Scenario.key == key))
    if sc is None:
        raise HTTPException(404, f"案例 {key!r} 不存在")
    return sc
