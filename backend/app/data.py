"""合成波形与教学案例生成（ObsPy）。

四个案例全部来自**已知源位置**的正演，便于学生把反演结果与真值比较：

  nominal     8 台环绕，拾取带小幅高斯噪声 —— 正常案例
  outlier     其中 1 个 P 到时人为偏移 +2.5 s，另 1 台 S 缺测 —— 错误/缺测拾取
  collinear   6 台近似排列在一条直线上 —— 几何退化，横向不可定位
  sparse      仅 3 台 —— 少于 4 个到时，明确不可定位

波形：BHZ 单分量，Ricker 子波叠加 P、S 到时，振幅按 1/D 衰减，
有色 + 白噪声。保存为 MiniSEED，由 API 经 ObsPy 读取（演示真实解析路径）。
所有随机量用固定种子，保证案例可复现。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from .core.velocity import MODEL_BASELINE, VelocityModel

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

# 真值震源（虚构教学位置，川滇菱形块体东缘一带）
TRUE_SOURCE = {"lon": 103.850, "lat": 30.050, "depth_km": 10.0}
# 所有案例共用一个发震时刻
ORIGIN_ISO = "2026-09-15T08:00:00.000000Z"
MODEL: VelocityModel = MODEL_BASELINE

# (code, lon, lat)
ALL_STATIONS: List[tuple] = [
    ("S01", 103.98, 30.12),
    ("S02", 103.70, 30.16),
    ("S03", 103.72, 29.92),
    ("S04", 104.02, 29.96),
    ("S05", 103.86, 30.22),
    ("S06", 103.60, 30.05),
    ("S07", 103.93, 30.04),
    ("S08", 103.78, 29.86),
    # 共线案例专用台站：L01–L05 沿约 41° 方位 NE-SW 走廊排列；
    # L06 只偏离该走廊约 1.4 km —— 几何高度近共线但不严格退化（仍可解）
    ("L01", 103.994, 30.194),
    ("L02", 103.946, 30.146),
    ("L03", 103.922, 30.122),
    ("L04", 103.758, 29.958),
    ("L05", 103.710, 29.910),
    ("L06", 103.702, 29.899),
]

# 案例 -> 使用的台站
SCENARIO_STATIONS = {
    "nominal": ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"],
    "outlier": ["S01", "S02", "S03", "S04", "S05", "S06"],
    "collinear": ["L01", "L02", "L03", "L04", "L05", "L06"],
    "sparse": ["S01", "S02", "S03"],
}

SCENARIO_META = {
    "nominal": {
        "title": "正常案例：8 台环绕",
        "description": "台站包围震中，自动拾取含 ±0.1~0.3s 高斯噪声。",
        "teaching_note": "观察空隙角、残差量级与误差椭圆；对比普通/稳健拟合。",
    },
    "outlier": {
        "title": "异常案例：错误到时 + S 缺测",
        "description": "S04 的 P 自动拾取被人为推后 2.5s；S06 的 S 拾取缺测。",
        "teaching_note": "错误拾取不会报错，但会留下大残差并拉偏解；看谁的残差最大。",
    },
    "collinear": {
        "title": "退化案例：台站近似共线",
        "description": "6 个 L 台几乎排成一条 NE-SW 直线（L06 仅偏离约 0.2 km），拾取噪声调到 0.03s。",
        "teaching_note": "条件数/特征值比极大、误差椭圆沿垂直走廊方向拉长：该方向几乎不可分辨。",
    },
    "sparse": {
        "title": "不足案例：仅 3 个台站",
        "description": "只有 3 个 P 到时，少于 4 个未知量的最低要求。",
        "teaching_note": "系统应明确报告不可定位，而不是给出一个看似精确的坐标。",
    },
}

# 拾取噪声标准差（秒）与个别异常
P_NOISE_S = 0.12
S_NOISE_S = 0.25
OUTLIER_STATION, OUTLIER_PHASE, OUTLIER_SHIFT = "S04", "P", 2.5
S_MISSING_STATION = "S06"

SAMPLING_RATE = 100.0
TRACE_LEN_S = 30.0
P_FREQ_HZ = 4.0
S_FREQ_HZ = 2.0


@dataclass
class SyntheticPick:
    station_code: str
    phase: str
    true_arrival_epoch: float
    raw_time_epoch: Optional[float]   # None 表示该道缺测
    raw_status: str                   # ok | missing | shifted_outlier
    seed: int


def _distance_km(lon: float, lat: float) -> float:
    # 与 geo.project_km 一致的平面近似 + 深度
    x = math.radians(lon - TRUE_SOURCE["lon"]) * 6371.0 * math.cos(math.radians(TRUE_SOURCE["lat"]))
    y = math.radians(lat - TRUE_SOURCE["lat"]) * 6371.0
    return math.sqrt(x * x + y * y + TRUE_SOURCE["depth_km"] ** 2)


def _ricker(t: np.ndarray, t0: float, f: float) -> np.ndarray:
    a = (math.pi * f * (t - t0)) ** 2
    return (1.0 - 2.0 * a) * np.exp(-a)


def _seed_for(scenario: str, code: str, phase: str) -> int:
    return abs(hash((scenario, code, phase))) % (2**31)


def build_scenario(scenario: str) -> Dict:
    """生成案例的波形文件与拾取表（幂等）。返回元数据。"""
    origin = UTCDateTime(ORIGIN_ISO)
    codes = SCENARIO_STATIONS[scenario]
    station_map = {c: (lo, la) for c, lo, la in ALL_STATIONS}
    out_dir = os.path.join(DATA_DIR, scenario)
    os.makedirs(out_dir, exist_ok=True)

    picks: List[SyntheticPick] = []
    stream_ids: List[str] = []

    n = int(TRACE_LEN_S * SAMPLING_RATE) + 1
    t = np.arange(n) / SAMPLING_RATE

    for idx, code in enumerate(codes):
        lon, lat = station_map[code]
        dist = _distance_km(lon, lat)
        tp_true = dist / MODEL.vp_km_s
        ts_true = dist / MODEL.vs_km_s

        rng = np.random.default_rng(_seed_for(scenario, code, "wave"))
        # 共线案例把拾取噪声调小（0.03s）：近乎理想的到时下，定位弥散
        # 几乎完全来自几何退化，避免噪声掩盖"横向不可分辨"这一教学点。
        p_sigma = 0.03 if scenario == "collinear" else P_NOISE_S
        s_sigma = 0.06 if scenario == "collinear" else S_NOISE_S
        p_noise = rng.normal(0.0, p_sigma)
        s_noise = rng.normal(0.0, s_sigma)
        p_status, s_status = "ok", "ok"
        p_raw, s_raw = tp_true + p_noise, ts_true + s_noise

        if scenario == "outlier":
            if code == OUTLIER_STATION:
                p_raw += OUTLIER_SHIFT
                p_status = "shifted_outlier"
            if code == S_MISSING_STATION:
                s_raw, s_status = None, "missing"

        for phase, raw, status in (("P", p_raw, p_status), ("S", s_raw, s_status)):
            picks.append(SyntheticPick(
                station_code=code, phase=phase,
                true_arrival_epoch=float(origin) + (tp_true if phase == "P" else ts_true),
                raw_time_epoch=(None if raw is None else float(origin) + raw),
                raw_status=status,
                seed=_seed_for(scenario, code, phase),
            ))

        # ---- 合成波形（真值到时上叠加子波，与有噪声的拾取相互独立）----
        amp = 200.0 / max(dist, 5.0)
        wave = amp * _ricker(t, tp_true, P_FREQ_HZ)
        wave += 0.6 * amp * _ricker(t, ts_true, S_FREQ_HZ)
        # 白噪声 + 慢漂移（低频有色噪声）
        wave += rng.normal(0.0, 0.05 * amp + 1.0, size=n)
        drift = np.cumsum(rng.normal(0.0, 1.0, size=n))
        wave += 0.02 * amp * drift / max(np.std(drift), 1e-9)
        wave = wave.astype(np.float32)

        tr = Trace(data=wave)
        tr.stats.sampling_rate = SAMPLING_RATE
        tr.stats.starttime = origin
        tr.stats.network = "TS"
        tr.stats.station = code
        tr.stats.location = "00"
        tr.stats.channel = "BHZ"
        mseed = os.path.join(out_dir, f"TS.{code}.00.BHZ.mseed")
        Stream([tr]).write(mseed, format="MSEED")
        stream_ids.append(mseed)

    return {
        "scenario": scenario,
        "origin_epoch": float(origin),
        "stations": codes,
        "picks": picks,
        "data_dir": out_dir,
    }


def all_scenarios() -> List[str]:
    return list(SCENARIO_STATIONS.keys())
