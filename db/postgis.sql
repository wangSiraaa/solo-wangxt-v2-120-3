-- TeachLoc 教学系统 —— PostgreSQL/PostGIS 补充定义
-- SQLAlchemy 会先创建所有普通表（见 app/database.py:init_db），
-- 本文件提供：扩展、几何列、空间索引与一个邻近台站查询示例视图。
--
-- 用法（应用启动时也会自动执行其中的 CREATE EXTENSION / ADD COLUMN）：
--   psql "$DATABASE_URL" -f db/postgis.sql

CREATE EXTENSION IF NOT EXISTS postgis;

-- 台站点位（经纬度，EPSG:4326）
ALTER TABLE stations ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);
UPDATE stations
   SET geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
 WHERE geom IS NULL AND lon IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stations_geom ON stations USING GIST (geom);

-- 定位候选解点位（不可定位的记录为 NULL）
ALTER TABLE location_runs ADD COLUMN IF NOT EXISTS solution_geom geometry(Point, 4326);
UPDATE location_runs
   SET solution_geom = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
 WHERE lon IS NOT NULL AND lat IS NOT NULL AND solution_geom IS NULL;
CREATE INDEX IF NOT EXISTS idx_runs_solution_geom ON location_runs USING GIST (solution_geom);

-- 邻近台站示例：震中 50 km 内的台站，按球面距离排序（geography 类型，单位米）
CREATE OR REPLACE VIEW v_stations_near_example AS
SELECT s.code, s.lon, s.lat,
       ST_Distance(s.geom::geography,
                   ST_SetSRID(ST_MakePoint(103.85, 30.05), 4326)::geography) / 1000.0 AS dist_km
  FROM stations s
 WHERE ST_DWithin(s.geom::geography,
                  ST_SetSRID(ST_MakePoint(103.85, 30.05), 4326)::geography, 50000)
 ORDER BY dist_km;
