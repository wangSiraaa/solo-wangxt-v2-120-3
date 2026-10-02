"""简化速度模型（教学用）。

明确声明的假设
--------------
* **均匀半空间、恒定速度、直射线**：走时 t = D / v，D 为震源到台站的
  三维直线距离（局部切平面笛卡尔坐标，单位 km）。
* 不包含地壳分层、莫霍面、速度梯度、高程校正、椭球与曲率效应（区域仅
  约 0.5° 见方，平面近似误差在教学可接受范围内）。
* P、S 走时方程独立：一次定位只允许使用**同一震相**的到时，严禁混用。
  原因：vP、vS 不同，混在一个残差向量里会同时偏置位置与发震时刻，
  且学生无法判断残差来自模型误差还是拾取误差。

模型是版本化的不可变对象：定位结果记录 model_id，重算时据此复现。
真实地震定位至少需要分层速度模型（如 IASP91），本系统绝不冒充。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class VelocityModel:
    model_id: str
    name: str
    description: str
    vp_km_s: float          # P 波速度 km/s
    vs_km_s: float          # S 波速度 km/s
    half_space: bool = True

    def velocity(self, phase: str) -> float:
        p = phase.upper()
        if p == "P":
            return self.vp_km_s
        if p == "S":
            return self.vs_km_s
        raise ValueError(f"不支持的震相 {phase!r}：教学模型仅含 P、S 两种震相")

    def as_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "description": self.description,
            "vp_km_s": self.vp_km_s,
            "vs_km_s": self.vs_km_s,
            "half_space": self.half_space,
            "assumptions": [
                "均匀半空间，速度恒定，射线路径为直线 t=D/v",
                "无分层、无莫霍面、无速度梯度、无台站高程校正",
                "经纬度按局部切平面投影为公里坐标（WGS84 球面距离近似）",
                "P/S 震相互不允许混合参与同一次定位",
            ],
        }


# 教学基线模型：大陆上地壳典型值，vP/vS ≈ 1.73
MODEL_BASELINE = VelocityModel(
    model_id="homog-crust-6.0-3.46-v1",
    name="均匀半空间 vP=6.0 / vS=3.46 km/s",
    description="上地壳典型 P、S 速度的均匀半空间模型，vP/vS≈1.73，教学基线",
    vp_km_s=6.0,
    vs_km_s=3.46,
)

# 慢速模型：用于"模型绑定/重算可解释"对比——同一批拾取换模型结果如何变
MODEL_SLOW = VelocityModel(
    model_id="homog-crust-5.5-3.18-v1",
    name="均匀半空间 vP=5.5 / vS=3.18 km/s",
    description="偏慢的均匀半空间模型，用于演示定位结果对速度模型的依赖",
    vp_km_s=5.5,
    vs_km_s=3.18,
)

MODELS: Dict[str, VelocityModel] = {m.model_id: m for m in (MODEL_BASELINE, MODEL_SLOW)}


def get_model(model_id: str) -> VelocityModel:
    try:
        return MODELS[model_id]
    except KeyError:
        raise ValueError(f"未知速度模型 {model_id!r}，可选：{sorted(MODELS)}")
