"""只读资源：台站、案例、速度模型。"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..core.config import IS_POSTGIS
from ..core.velocity import MODELS
from ..database import get_db
from ..models.tables import Scenario, Station
from ..schemas.dto import ScenarioOut, StationOut

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/health")
def health():
    return {"status": "ok", "backend": "teachloc", "postgis": IS_POSTGIS,
            "disclaimer": "教学演示系统，非地震预警，定位仅在标注的简化速度模型下成立。"}


@router.get("/models")
def list_models():
    return [m.as_dict() for m in MODELS.values()]


@router.get("/stations", response_model=list[StationOut])
def list_stations(db: Session = Depends(get_db)):
    return list(db.scalars(select(Station).order_by(Station.code)))


@router.get("/stations/near", response_model=list[StationOut])
def stations_near(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    radius_km: float = Query(50.0, gt=0, le=2000),
    db: Session = Depends(get_db),
):
    """邻近台站：PostGIS 用 ST_DWithin(geography)；SQLite 回退 Haversine。"""
    if IS_POSTGIS:
        sql = text("""
            SELECT * FROM stations
            WHERE ST_DWithin(geom::geography,
                             ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                             :r)
            ORDER BY ST_Distance(geom::geography,
                                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
        """)
        rows = db.execute(sql, {"lon": lon, "lat": lat, "r": radius_km * 1000.0}).mappings().all()
        return [StationOut(**dict(row)) for row in rows]

    stations = list(db.scalars(select(Station)))
    out = []
    for s in stations:
        d = _haversine_km(lon, lat, s.lon, s.lat)
        if d <= radius_km:
            out.append((d, s))
    return [s for _, s in sorted(out, key=lambda x: x[0])]


def _haversine_km(lon1, lat1, lon2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(db: Session = Depends(get_db)):
    return list(db.scalars(select(Scenario).order_by(Scenario.id)))


@router.get("/scenarios/{key}", response_model=ScenarioOut)
def get_scenario(key: str, db: Session = Depends(get_db)):
    sc = db.scalar(select(Scenario).where(Scenario.key == key))
    if sc is None:
        raise HTTPException(404, f"案例 {key!r} 不存在")
    return sc
