"""地震定位求解（教学版 Geiger 最小二乘）。

模型（见 velocity.py）：均匀半空间、直射线
    t_i = t0 + sqrt((x-xi)^2 + (y-yi)^2 + z^2) / v_phase
未知量 4 个：经度、纬度、深度 z(km)、发震时刻 t0。
    —— 因此同一震相至少需要 **4 个到时**；不足则明确返回"不可定位"，
       绝不输出单点坐标冒充结果。

输出不止一个坐标：每个候选解都带
  * 逐台站残差（观测到时 - 理论到时），大残差显式标红；
  * 由雅可比矩阵估计的参数协方差、水平误差椭圆、深度/发震时刻误差；
  * RMS、方位空隙角、设计矩阵条件数、自由度与警告信息。

P、S 严格分离：phase="P" 时只接受 P 拾取，混用直接拒绝。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import least_squares

from .geo import geometry_diagnostics, project_km, unproject_km
from .velocity import VelocityModel

MIN_ARRIVALS = 4  # 4 个未知量 (lon, lat, depth, t0)
SUSPECT_RESIDUAL_S = 0.6  # |残差|超过该值（秒）标记为可疑，供课堂讨论
PICKER_SIGMA_PRIOR = {"P": 0.15, "S": 0.30}  # 自由度为 0 时的先验拾取误差


@dataclass
class Arrival:
    station_code: str
    lon: float
    lat: float
    time_epoch: float          # 观测到时（UTC 秒）
    pick_id: int
    time_source: str           # "raw" | "manual"


@dataclass
class LocateResult:
    locatable: bool
    status: str                # located | insufficient_data | degenerate | failed
    reason: Optional[str]
    phase: str
    model_id: str
    robust: bool
    n_used: int
    dof: int
    lon: Optional[float]
    lat: Optional[float]
    depth_km: Optional[float]
    origin_time_epoch: Optional[float]
    rms_s: Optional[float]
    max_abs_residual_s: Optional[float]
    residuals: List[dict]
    uncertainty: Optional[dict]
    geometry: Optional[dict]
    truth: Optional[dict]
    warnings: List[str]

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def locate(
    arrivals: Sequence[Arrival],
    phase: str,
    model: VelocityModel,
    robust: bool = False,
    ref_lonlat: Optional[Tuple[float, float]] = None,
    truth: Optional[dict] = None,
) -> LocateResult:
    phase = phase.upper()
    v = model.velocity(phase)
    n = len(arrivals)

    base = _not_locatable(phase, model, robust, arrivals)
    if n < MIN_ARRIVALS:
        base.reason = (
            f"仅 {n} 个有效 {phase} 到时，而均匀半空间定位有 4 个未知量"
            f"（经度、纬度、深度、发震时刻），至少需要 {MIN_ARRIVALS} 个。"
        )
        base.truth = _truth_block(None, None, None, None, truth)
        return base

    lons = [a.lon for a in arrivals]
    lats = [a.lat for a in arrivals]
    lon0 = ref_lonlat[0] if ref_lonlat else float(np.mean(lons))
    lat0 = ref_lonlat[1] if ref_lonlat else float(np.mean(lats))

    sta = [project_km(a.lon, a.lat, lon0, lat0) for a in arrivals]
    xi = np.array([p[0] for p in sta])
    yi = np.array([p[1] for p in sta])
    # 以最早到时为时间零点求解：绝对历元(~1.8e9)会让有限差分步长
    # （trf 默认相对步长 ~|x|^0.5）完全失真，必须在相对时间下反演。
    t_ref = float(np.min([a.time_epoch for a in arrivals]))
    ti = np.array([a.time_epoch for a in arrivals]) - t_ref

    # 初始值：台网中心、深度 8 km，t0 由最近台站反推
    d0 = np.sqrt(xi**2 + yi**2 + 8.0**2)
    t0_init = float(np.min(ti) - np.min(d0) / v)
    p0 = np.array([0.0, 0.0, 8.0, t0_init])

    def residuals(p: np.ndarray) -> np.ndarray:
        x, y, z, t0 = p
        dist = np.sqrt((x - xi) ** 2 + (y - yi) ** 2 + z**2)
        return ti - (t0 + dist / v)

    loss = "soft_l1" if robust else "linear"

    def _solve(z_init: float):
        d0i = np.sqrt(xi**2 + yi**2 + z_init**2)
        p0i = np.array([0.0, 0.0, z_init, float(np.min(ti) - np.min(d0i) / v)])
        return least_squares(
            residuals, p0i,
            bounds=([-200.0, -200.0, 0.0, -120.0],
                    [200.0, 200.0, 60.0, 120.0]),
            method="trf", loss=loss, f_scale=0.35,
        )

    try:
        # 从多个初始深度择优：坏拾取可能把浅层初值拖到 z=0 边界并停住
        sol = min((_solve(z) for z in (8.0, 3.0, 20.0)), key=lambda s: float(s.cost))
    except Exception as exc:  # 数值失败也要如实报告
        base.status = "failed"
        base.reason = f"最小二乘求解失败：{exc}"
        return base

    x, y, z, t0 = (float(q) for q in sol.x)
    t0_abs = t_ref + t0
    res = residuals(sol.x)
    rms = float(np.sqrt(np.mean(res**2)))
    dof = n - 4

    lon, lat = unproject_km(x, y, lon0, lat0)

    # 雅可比（残差对参数的解析导数 = -理论走时导数；least_squares 给的是 -J_pred）
    J = sol.jac  # d(residual)/d(param)
    warnings: List[str] = []

    # 用 SVD 伪逆估协方差：当某个方向在数据中不可分辨（典型情形：深度
    # 撞到地表边界 z=0，此时 ∂r/∂z = z/D = 0，雅可比秩缺 1），直接求逆
    # 会给出天文数字的"误差"，教学上必须如实标为"不可分辨"而非假精确。
    param_names = ["x", "y", "depth", "origin_time"]
    uncertainty = None
    cov = None
    unconstrained: List[str] = []
    try:
        u, s, vt = np.linalg.svd(J, full_matrices=False)
        s_tol = max(J.shape) * s[0] * np.finfo(float).eps
        sinv = np.array([1.0 / si if si > s_tol else 0.0 for si in s])
        rank = int(np.sum(s > s_tol))
        null_dirs = vt[rank:]
        for nd in null_dirs:
            k = int(np.argmax(np.abs(nd)))
            if param_names[k] not in unconstrained:
                unconstrained.append(param_names[k])
        Jp = (vt.T * sinv) @ u.T          # (J^T J)^+ J^T
        cov_rel = Jp @ Jp.T               # (J^T J)^+
    except np.linalg.LinAlgError:
        cov_rel = None
        rank = 0
        warnings.append("雅可比 SVD 失败，无法估计参数不确定度。")

    if cov_rel is not None:
        if dof > 0:
            sigma2 = float(np.sum(res**2) / dof)
            variance_note = "由残差估计"
        else:
            sigma2 = PICKER_SIGMA_PRIOR.get(phase, 0.2) ** 2
            variance_note = "无冗余观测(n=4)，采用先验拾取误差，仅为数量级参考"
            warnings.append("恰好 4 个到时：解可求但无残差冗余，误差为经验先验值。")
        cov = cov_rel * sigma2
        sig_xy = np.sqrt(np.clip(np.diag(cov[:2, :2]), 0, None))  # km
        # 水平误差椭圆（协方差 2x2 特征分解）
        (l1, l2), rot = np.linalg.eigh(cov[:2, :2])
        angle = math.degrees(math.atan2(rot[1, 1], rot[0, 1]))
        uncertainty = {
            "sigma2_s2": round(sigma2, 5),
            "variance_note": variance_note,
            "jacobian_rank": rank,
            "unconstrained_parameters": unconstrained,
            "horizontal_sigma_km": [round(float(sig_xy[0]), 3), round(float(sig_xy[1]), 3)],
            "ellipse_semi_axes_km": [
                round(math.sqrt(max(float(l1), 0.0)), 3),
                round(math.sqrt(max(float(l2), 0.0)), 3),
            ],
            "ellipse_major_axis_azimuth_deg": round(angle, 1),
            "depth_sigma_km": (None if "depth" in unconstrained
                               else round(math.sqrt(max(float(cov[2, 2]), 0.0)), 3)),
            "origin_time_sigma_s": (None if "origin_time" in unconstrained
                                    else round(math.sqrt(max(float(cov[3, 3]), 0.0)), 3)),
        }
        if "depth" in unconstrained:
            warnings.append("深度方向不可分辨（雅可比秩缺，常见于深度被约束到地表 0 km）：不要解读深度值。")

    # 几何诊断在**先验参考点（投影原点 = 台网中心）**上评估，而不是在反演
    # 解上评估：病态几何会把解拽离台网，再以偏掉的解算方位角会"洗白"共线
    # 结构（解跑到所有台站一侧后，方向反而显得分散）。
    geom = geometry_diagnostics(sta, (0.0, 0.0))
    if geom["gap_deg"] > 270:
        warnings.append(f"方位空隙角 {geom['gap_deg']}°>270°，台站严重单侧分布。")
    elif geom["gap_deg"] > 180:
        warnings.append(f"方位空隙角 {geom['gap_deg']}°>180°，无台站方向的位置不确定度偏大。")
    if geom["collinear_warning"]:
        warnings.append(
            f"水平几何近共线：水平方向矩阵特征值比达 "
            f"{geom['eigenvalue_ratio']}（>1000 视为近共线），"
            "垂直于台站线方向的位置约束很弱，误差椭圆沿该方向显著拉长。"
        )
    if robust:
        warnings.append("稳健拟合(soft_l1)会压低大残差台站权重；请同时查看普通最小二乘解并对比。")

    residual_rows = []
    for a, r in zip(arrivals, res):
        rr = float(r)
        flag = "suspect" if abs(rr) > SUSPECT_RESIDUAL_S else "ok"
        if flag == "suspect":
            warnings.append(f"台站 {a.station_code} {phase} 残差 {rr:+.2f}s 超阈值，疑似错误拾取。")
        residual_rows.append({
            "pick_id": a.pick_id,
            "station_code": a.station_code,
            "phase": phase,
            "time_source": a.time_source,
            "observed_epoch": a.time_epoch,
            "residual_s": round(rr, 3),
            "flag": flag,
        })

    max_abs = float(np.max(np.abs(res))) if n else None
    if max_abs is not None and max_abs > SUSPECT_RESIDUAL_S and not robust:
        warnings.append("存在可疑拾取时，建议改用稳健拟合并人工复核后重算。")

    truth_block = _truth_block(lon, lat, z, t0_abs, truth) if truth else None
    if truth_block and (truth_block.get("horizontal_error_km") or 0) > 5.0:
        warnings.append(
            f"解偏离已知真值 {truth_block['horizontal_error_km']} km（教学对照）："
            "小残差不等于位置正确——几何退化或错误拾取会产生'拟合很好但位置很偏'的解。"
        )

    return LocateResult(
        locatable=True,
        status="located",
        reason=None,
        phase=phase,
        model_id=model.model_id,
        robust=robust,
        n_used=n,
        dof=dof,
        lon=round(lon, 6),
        lat=round(lat, 6),
        depth_km=round(z, 3),
        origin_time_epoch=round(t0_abs, 3),
        rms_s=round(rms, 3),
        max_abs_residual_s=(round(max_abs, 3) if max_abs is not None else None),
        residuals=sorted(residual_rows, key=lambda d: -abs(d["residual_s"])),
        uncertainty=uncertainty,
        geometry=geom,
        truth=truth_block,
        warnings=sorted(set(warnings)),
    )


def _truth_block(lon, lat, z, t0_abs, truth: Optional[dict]) -> Optional[dict]:
    """与已知合成真值的偏差（仅教学场景存在）。真实业务中没有真值可比。"""
    if not truth:
        return None
    tlon, tlat = truth["lon"], truth["lat"]
    if lon is None:
        return {"true_lon": tlon, "true_lat": tlat, "true_depth_km": truth["depth_km"],
                "horizontal_error_km": None, "depth_error_km": None,
                "origin_time_error_s": None}
    dx, dy = project_km(lon, lat, tlon, tlat)  # 以真值为原点投影解的偏差
    return {
        "true_lon": tlon, "true_lat": tlat, "true_depth_km": truth["depth_km"],
        "horizontal_error_km": round(math.hypot(dx, dy), 3),
        "depth_error_km": (round(z - truth["depth_km"], 3) if z is not None else None),
        "origin_time_error_s": (
            round(t0_abs - truth["origin_epoch"], 3)
            if t0_abs is not None and truth.get("origin_epoch") is not None else None),
    }


def _not_locatable(phase, model, robust, arrivals) -> LocateResult:
    return LocateResult(
        locatable=False,
        status="insufficient_data",
        reason=None,
        phase=phase,
        model_id=model.model_id,
        robust=robust,
        n_used=len(arrivals),
        dof=max(len(arrivals) - 4, 0),
        lon=None, lat=None, depth_km=None, origin_time_epoch=None,
        rms_s=None, max_abs_residual_s=None,
        residuals=[], uncertainty=None, geometry=None, truth=None, warnings=[],
    )
