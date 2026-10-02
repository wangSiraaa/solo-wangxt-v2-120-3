"""幂等种子：生成合成 MiniSEED，并把台站、案例、原始拾取写入数据库。"""
from __future__ import annotations

from sqlalchemy import select

from .core.config import DATA_VERSION
from .data import (
    ALL_STATIONS, MODEL, ORIGIN_ISO, SCENARIO_META, TRUE_SOURCE, build_scenario,
)
from .database import SessionLocal, init_db
from .models.tables import Pick, Scenario, Station
from obspy import UTCDateTime


def seed() -> dict:
    init_db()
    origin_epoch = float(UTCDateTime(ORIGIN_ISO))
    summary = {"stations": 0, "scenarios": {}, "model_id": MODEL.model_id}

    with SessionLocal() as db:
        station_ids = {}
        for code, lon, lat in ALL_STATIONS:
            st = db.scalar(select(Station).where(Station.code == code))
            if st is None:
                st = Station(code=code, name=f"教学台 {code}", lon=lon, lat=lat,
                             elevation_m=0.0, network="TS")
                db.add(st)
                db.flush()
            station_ids[code] = st.id
        summary["stations"] = len(station_ids)

        for key, meta in SCENARIO_META.items():
            built = build_scenario(key)  # （重新）写 MiniSEED，内容由种子决定
            sc = db.scalar(select(Scenario).where(Scenario.key == key))
            if sc is None:
                sc = Scenario(
                    key=key, title=meta["title"], description=meta["description"],
                    teaching_note=meta["teaching_note"],
                    true_lon=TRUE_SOURCE["lon"], true_lat=TRUE_SOURCE["lat"],
                    true_depth_km=TRUE_SOURCE["depth_km"],
                    true_origin_epoch=origin_epoch, data_version=DATA_VERSION,
                )
                db.add(sc)
                db.flush()
            else:
                sc.data_version = DATA_VERSION

            # 以 (station, phase) 为键同步：案例台站集可能随合成数据更新而变化
            old_picks = {(p.station_id, p.phase): p
                         for p in db.scalars(select(Pick).where(Pick.scenario_id == sc.id))}
            n_picks = 0
            for sp in built["picks"]:
                sid = station_ids[sp.station_code]
                p = old_picks.pop((sid, sp.phase), None)
                if p is None:
                    db.add(Pick(
                        scenario_id=sc.id, station_id=sid, phase=sp.phase,
                        raw_time_epoch=sp.raw_time_epoch, raw_status=sp.raw_status,
                        true_time_epoch=sp.true_arrival_epoch, picker_seed=sp.seed,
                    ))
                else:
                    # 合成数据更新：覆盖 raw/真值，人工修订予以保留（raw 与修订
                    # 分离，且拾取版本哈希会随之变化，旧 run 自动标为过期）
                    p.raw_time_epoch = sp.raw_time_epoch
                    p.raw_status = sp.raw_status
                    p.true_time_epoch = sp.true_arrival_epoch
                    p.picker_seed = sp.seed
                n_picks += 1
            for p in old_picks.values():  # 本案例已移除的台站拾取
                db.delete(p)
            summary["scenarios"][key] = {"stations": len(built["stations"]), "synced_picks": n_picks}

        db.commit()
    return summary


if __name__ == "__main__":
    import json
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
