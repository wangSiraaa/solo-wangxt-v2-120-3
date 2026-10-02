# TeachLoc · 地震定位教学系统

从几个台站的**波形到时**恢复一个**候选事件位置**的课堂实验系统。
Vue 3 + Plotly.js 展示波形与到时，FastAPI + ObsPy 解析合成 MiniSEED、
SciPy 做 Geiger 最小二乘拟合，PostgreSQL/PostGIS（开发时可回退 SQLite）
保存台站、原始拾取、人工修订与定位记录。

> ⚠️ **这是教学演示，不是地震预警 / 速报产品。** 所有定位只在明确标注的
> **简化均匀半空间速度模型**下成立；台站不足时系统明确报告「不可定位」，
> 不输出一个看似精确的坐标。

## 教学设计要点（对应需求）

| 需求 | 实现 |
|---|---|
| 明确采用的简化速度模型 | `app/core/velocity.py`：均匀半空间、恒速、直射线 t=D/v；两个版本化模型（vP=6.0/vS=3.46 与 5.5/3.18），假设在 `/api/models` 和前端显式列出 |
| P 波与 S 波不能混用 | 每次定位 API 只接受单一 `phase`，查询就按该震相过滤，物理上无法混入 |
| 缺测/错误拾取要显示残差 | 逐台站残差表（观测−理论）、\|残差\|>0.6s 红色「可疑」标记；缺测台站标注并剔除 |
| 不能仅报一个精确坐标 | 每个解带 1σ 水平误差椭圆、深度/发震时刻误差、RMS、雅可比秩、逐站残差、诊断警告 |
| 比较候选解与几何覆盖 | 候选解列表 + 地图叠加对比；方位空隙角 gap、水平方向矩阵特征值比（共线诊断） |
| 台站不足报告不可定位 | 4 个未知量（经度/纬度/深度/发震时刻）需 ≥4 个同震相到时，sparse 案例（3 台）直接返回 `locatable=false` 与原因 |
| 已知源位置的合成波形 | ObsPy 生成 Ricker 子波 + 噪声的 BHZ MiniSEED，真值经纬度/深度/发震时刻入库 |
| 离群到时案例 | outlier：S04 的 P 自动拾取人为 +2.5s，S06 的 S 缺测 |
| 台站几乎共线案例 | collinear：6 台沿 NE-SW 走廊（L06 偏离仅 0.2 km），特征值比 >60000，误差椭圆沿弱方向拉长 |
| 原始拾取与人工修订分开 | `picks.raw_*` 只读、永不修改；`manual_*` 独立字段，可撤销；波形上点击放置修订 |
| 结果绑定模型与数据版本 | 每次运行记录 model_id、data_version、pick_schema_version、app_version，以及拾取内容哈希 `pick_data_version` 和完整输入快照 |
| 重算可解释 | 修订拾取后哈希变化，旧候选标记「过期」并保留对比；快照可逐拾取复盘 |

## 四个案例

1. **nominal** — 8 台环绕，自动拾取带小高斯噪声（正常反演，与真值相差 ~1–2 km）。
2. **outlier** — 6 台，一个错误 P 到时 + 一个 S 缺测。OLS 解被拉偏约 6 km 且深度
   退化到地表；稳健拟合（soft_l1）部分纠偏；**人工把错误拾取改到真值附近后 RMS
   从 0.64s 降到 0.05s**。错误拾取不会报错——它只会留下大残差。
3. **collinear** — 近乎共线的台网、低噪声拾取（0.03s）。RMS 仅 0.01s，但解沿
   垂直走廊方向偏离真值 **8 km**：「拟合很好 ≠ 位置正确」。
4. **sparse** — 仅 3 个到时，少于 4 个未知量 → **不可定位**。

## 快速开始（SQLite，零外部依赖）

```bash
# 后端
cd backend
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --port 8000
#   启动时自动生成 data/<scenario>/*.mseed 并幂等播种 app/teachloc.db

# 前端
cd frontend
npm install
npm run dev      # http://localhost:5173 ，/api 代理到 8000
```

## PostgreSQL + PostGIS 模式

```bash
export DATABASE_URL="postgresql+psycopg2://teachloc:teachloc@localhost:5432/teachloc"
psql "$DATABASE_URL" -f db/postgis.sql   # 扩展、geometry(Point,4326)、GIST 索引、邻近查询视图
cd backend && python3 -m uvicorn app.main:app --port 8000
```

或直接 `docker compose up --build`（PostGIS 16 + 后端 + 前端）。
PostGIS 下邻近台站接口走 `ST_DWithin(geography)`；SQLite 下自动回退 Haversine。

## API 概览

```
GET  /api/health /api/models /api/scenarios /api/stations
GET  /api/stations/near?lon=&lat=&radius_km=
GET  /api/scenarios/{key}/picks                 # raw 与 manual 分列 + 派生有效到时
GET  /api/scenarios/{key}/picks/version         # 拾取内容哈希（修订即变化）
PATCH /api/scenarios/picks/{id}                 # 写入人工修订（不动 raw）
DELETE /api/scenarios/picks/{id}/manual         # 撤销修订
GET  /api/scenarios/{key}/waveforms/{station}   # ObsPy 读 MiniSEED，降采样返回
POST /api/scenarios/locate                      # 单震相定位，保存候选解（含快照/版本）
GET  /api/scenarios/{key}/runs  /api/scenarios/runs/{id}
DELETE /api/scenarios/runs/{id}
```

## 定位方法说明

Geiger 线性化最小二乘（`scipy.optimize.least_squares`，trf，多初始深度择优）：

- 经纬度按局部切平面投影为公里坐标；走时 tᵢ = t₀ + √((x−xᵢ)²+(y−yᵢ)²+z²)/v。
- 时间在**相对最早到时的秒坐标**下反演（绝对历元 ~1.8e9 会破坏有限差分雅可比）。
- 不确定度由雅可比 SVD 伪逆给出：深度撞到地表边界时 ∂r/∂z=0、雅可比秩缺，
  深度误差显式标为「不可分辨」，而不是输出一个荒谬的巨大 σ。
- 共线诊断用台站水平单位方向矩阵的**特征值比**（在台网中心先验点评估，避免
  被偏掉的解「洗白」几何）；另给出 1/D 距离加权指标与方位空隙角。

## 目录

```
backend/app/core/velocity.py   # 速度模型（版本化、假设显式化）
backend/app/core/geo.py        # 投影、空隙角、共线/特征值诊断
backend/app/core/location.py   # Geiger 定位、残差、SVD 协方差
backend/app/data.py            # 合成波形与四个教学案例（固定随机种子）
backend/app/api/               # catalog / waveforms / location 路由
db/postgis.sql                 # PostGIS 几何列、索引、示例视图
frontend/src/components/       # WaveformViewer / PickTable / GeometryMap / LocationPanel
docker-compose.yml             # 一体化 PostGIS 部署
```
