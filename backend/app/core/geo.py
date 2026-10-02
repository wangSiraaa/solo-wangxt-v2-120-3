"""局部切平面投影与几何覆盖诊断。

经纬度 -> 以参考点为原点的公里坐标（等距近似，equirectangular）：
    x = R * dlon * cos(lat0)
    y = R * dlat
教学区域约 0.5° 见方，该投影引入的尺度误差 < 0.1 ppm 量级，远小于
速度模型与拾取误差，可忽略。
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

R_EARTH_KM = 6371.0


def project_km(lon: float, lat: float, lon0: float, lat0: float) -> Tuple[float, float]:
    x = math.radians(lon - lon0) * R_EARTH_KM * math.cos(math.radians(lat0))
    y = math.radians(lat - lat0) * R_EARTH_KM
    return x, y


def unproject_km(x: float, y: float, lon0: float, lat0: float) -> Tuple[float, float]:
    lon = lon0 + math.degrees(x / (R_EARTH_KM * math.cos(math.radians(lat0))))
    lat = lat0 + math.degrees(y / R_EARTH_KM)
    return lon, lat


def azimuthal_gap(azimuths: Sequence[float]) -> float:
    """最大空隙角（度）：相邻台站方位角之差的最大值。

    经验判据（教学）：
      gap < 180°  包围较好，位置约束较可靠；
      180~270°    单侧覆盖，沿无台站方向的位置不确定度大；
      > 270°      严重单侧，定位仅供参考。
    """
    if not azimuths:
        return 360.0
    a = sorted((z % 360.0 for z in azimuths))
    gaps = [a[i + 1] - a[i] for i in range(len(a) - 1)]
    gaps.append(a[0] + 360.0 - a[-1])
    return max(gaps)


def geometry_diagnostics(
    sta_xy: Sequence[Tuple[float, float]],
    src_xy: Tuple[float, float],
) -> dict:
    """台站几何覆盖诊断。

    - gap：最大方位空隙角；
    - condition_number：水平位置设计矩阵 G 的 2-范数条件数
      （列取各台站水平方向余弦），数值越大说明台站越接近共线，
      垂直于台站线方向的定位误差被放大的倍数；
    - collinear：条件数超过阈值的教学化判定。
    """
    n = len(sta_xy)
    # 投影后的笛卡尔方位角（此尺度与球面方位角差异可忽略）
    azims = []
    for sx, sy in sta_xy:
        azims.append((math.degrees(math.atan2(sx - src_xy[0], sy - src_xy[1])) + 360.0) % 360.0)
    gap = azimuthal_gap(azims)

    # 水平可观测性。
    # Gu 的行是到各台站的水平单位方向余弦 (dx/D, dy/D)；Gu^T·Gu 的两个
    # 特征值就是沿最强/最弱水平方向的"台站能量"，其比值 eigenvalue_ratio
    # 直接度量几何退化程度：
    #   ≈1     各方向覆盖均衡；
    #   >10    明显各向异性，误差椭圆沿弱方向拉长；
    #   >1000  台站几乎共线，弱方向基本不可分辨。
    # 另给 1/D 距离加权版本与最小奇异值，反映远台的信息被距离稀释。
    eig_ratio = None
    cond_unit = None
    smin_weighted = None
    if n >= 2:
        rows_w: List[List[float]] = []
        rows_u: List[List[float]] = []
        for sx, sy in sta_xy:
            dx, dy = sx - src_xy[0], sy - src_xy[1]
            d = math.hypot(dx, dy)
            if d > 1e-9:
                rows_u.append([dx / d, dy / d])
                rows_w.append([dx / (d * d), dy / (d * d)])
        if len(rows_u) >= 2:
            su = _svd_singular_values(rows_u)
            sw = _svd_singular_values(rows_w)
            cond_unit = max(su) / min(su) if min(su) > 1e-12 else float("inf")
            smin_weighted = min(sw) if min(sw) > 1e-12 else 0.0
            eig_ratio = cond_unit ** 2 if cond_unit != float("inf") else float("inf")

    collinear = eig_ratio is not None and eig_ratio > 1000.0
    return {
        "n_stations": n,
        "azimuths_deg": [round(a, 1) for a in azims],
        "gap_deg": round(gap, 1),
        "eigenvalue_ratio": (None if eig_ratio is None or math.isinf(eig_ratio)
                             else round(eig_ratio, 1)),
        "condition_number_unit_dirs": (
            None if cond_unit is None or math.isinf(cond_unit) else round(cond_unit, 2)),
        "min_horizontal_sensitivity_per_km": (
            None if smin_weighted is None else round(smin_weighted, 4)),
        "collinear_warning": collinear,
        "gap_verdict": _gap_verdict(gap),
    }


def _gap_verdict(gap: float) -> str:
    if gap < 180.0:
        return "good"
    if gap <= 270.0:
        return "one_sided"
    return "poor"


def _svd_singular_values(g: List[List[float]]) -> List[float]:
    """小矩阵 SVD 奇异值（2 列），避免对 numpy 的硬依赖顺序。"""
    import numpy as np

    a = np.asarray(g, dtype=float)
    if a.ndim != 2 or a.shape[1] != 2:
        return [1.0, 1.0]
    _, s, _ = np.linalg.svd(a, full_matrices=False)
    return list(map(float, s))
