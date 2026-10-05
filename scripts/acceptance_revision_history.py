"""验收脚本：人工修订/撤销操作记录（对应题目验收点）。

在临时 SQLite 库上跑完整流程：
  1) 连续两次修订 -> 两条有序记录，各自带前后值
  2) 撤销 manual -> 有效到时回到 raw，并留下一条撤销记录
  3) 记录持久化（独立 sqlite3 连接直读库文件，等价于重新打开页面）
  4) 旧候选解 input_snapshot 不随历史记录变化；raw 始终只读
"""
import os
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="teachloc_accept_")
os.environ["SQLITE_PATH"] = os.path.join(TMP, "accept.db")
os.environ["SKIP_SEED"] = "1"  # 手动播种，便于断言

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

PASS, FAIL = "✅", "❌"
failures = []


def check(name, cond, detail=""):
    print(f"{PASS if cond else FAIL} {name}" + (f"  | {detail}" if detail else ""))
    if not cond:
        failures.append(name)


seed()
client = TestClient(app)

# ---- 准备：取 outlier 案例 S04 的 P 拾取（raw 为异常偏移值） ----
picks = client.get("/api/scenarios/outlier/picks").json()
pick = next(p for p in picks if p["station_code"] == "S04" and p["phase"] == "P")
pid = pick["id"]
raw0 = pick["raw_time_epoch"]
assert raw0 is not None
v1 = round(raw0 - 2.0, 3)   # 第一次修订：把异常到时改回真值附近
v2 = round(raw0 - 2.5, 3)   # 第二次修订：再微调
print(f"被测拾取 #{pid} S04·P  raw={raw0}")

# ---- 先跑一次定位，留一个「当时的」候选解快照 ----
run = client.post("/api/scenarios/locate", json={
    "scenario_key": "outlier", "phase": "P",
    "model_id": "homog-crust-6.0-3.46-v1", "label": "修订前基线",
}).json()
snap_before = next(s for s in run["input_snapshot"] if s["pick_id"] == pid)
check("基线候选解快照记录的是原始有效到时",
      snap_before["effective_time_epoch"] == raw0 and snap_before["time_source"] == "raw",
      f"snapshot t={snap_before['effective_time_epoch']} [{snap_before['time_source']}]")

# ---- 验收点 1：连续两次修订 -> 两条有序记录及每次前后值 ----
r = client.patch(f"/api/scenarios/picks/{pid}", json={
    "manual_time_epoch": v1, "note": "第一次修订：异常到时改回真值附近", "author": "student-a"})
assert r.status_code == 200, r.text
r = client.patch(f"/api/scenarios/picks/{pid}", json={
    "manual_time_epoch": v2, "note": "第二次修订：再微调 0.5s", "author": "student-b"})
assert r.status_code == 200, r.text

hist = client.get(f"/api/scenarios/picks/{pid}/history").json()
check("两次修订产生两条记录", len(hist) == 2, f"n={len(hist)}")
check("记录按时间有序（id 升序）", [h["id"] for h in hist] == sorted(h["id"] for h in hist))
h1, h2 = hist
check("记录#1 前后值 = raw -> v1",
      h1["action"] == "revise" and h1["old_time_epoch"] == raw0
      and h1["new_time_epoch"] == v1 and h1["old_source"] == "raw"
      and h1["new_source"] == "manual",
      f"{h1['old_source']} {h1['old_time_epoch']} -> {h1['new_source']} {h1['new_time_epoch']}")
check("记录#2 前后值 = v1 -> v2",
      h2["action"] == "revise" and h2["old_time_epoch"] == v1
      and h2["new_time_epoch"] == v2,
      f"{h2['old_time_epoch']} -> {h2['new_time_epoch']}")
check("记录含作者/备注/时间",
      h1["author"] == "student-a" and "第一次" in h1["note"] and bool(h1["created_at"])
      and h2["author"] == "student-b" and "第二次" in h2["note"],
      f"{h1['author']}「{h1['note']}」@{h1['created_at']}")

picks2 = client.get("/api/scenarios/outlier/picks").json()
p2 = next(p for p in picks2 if p["id"] == pid)
check("两次修订后有效到时 = v2（manual），raw 未变",
      p2["effective_time_epoch"] == v2 and p2["effective_source"] == "manual"
      and p2["raw_time_epoch"] == raw0)

# ---- 验收点 2：撤销 manual -> 有效到时回到 raw + 一条撤销记录 ----
r = client.delete(f"/api/scenarios/picks/{pid}/manual",
                  params={"author": "student-a", "note": "撤销，恢复原始拾取"})
assert r.status_code == 200, r.text
p3 = r.json()
check("撤销后有效到时回到 raw",
      p3["effective_time_epoch"] == raw0 and p3["effective_source"] == "raw",
      f"eff={p3['effective_time_epoch']} [{p3['effective_source']}]")
hist = client.get(f"/api/scenarios/picks/{pid}/history").json()
check("撤销后共三条有序记录", len(hist) == 3
      and [h["id"] for h in hist] == sorted(h["id"] for h in hist))
h3 = hist[-1]
check("最后一条为撤销记录（manual v2 -> raw）",
      h3["action"] == "undo" and h3["old_time_epoch"] == v2
      and h3["new_time_epoch"] == raw0 and h3["old_source"] == "manual"
      and h3["new_source"] == "raw",
      f"{h3['action']}: {h3['old_source']} {h3['old_time_epoch']} -> {h3['new_source']} {h3['new_time_epoch']}")
check("撤销记录含作者/备注", h3["author"] == "student-a" and "撤销" in h3["note"])

# 案例级时间线接口（前端时间线面板用）
revs = client.get("/api/scenarios/outlier/revisions").json()
check("案例级时间线包含同一拾取的三条记录",
      [r_["id"] for r_ in revs if r_["pick_id"] == pid] == [h["id"] for h in hist]
      and all(r_["station_code"] == "S04" for r_ in revs if r_["pick_id"] == pid))

# ---- 验收点 3：记录持久化（重新打开页面 = 新连接重查库文件）----
conn = sqlite3.connect(os.environ["SQLITE_PATH"])
rows = conn.execute(
    "SELECT action, old_time_epoch, new_time_epoch, author, note FROM pick_revisions "
    "WHERE pick_id=? ORDER BY id", (pid,)).fetchall()
conn.close()
check("库文件中持久存在三条记录（重开页面仍可查）",
      [r_[0] for r_ in rows] == ["revise", "revise", "undo"]
      and rows[0][1] == raw0 and rows[0][2] == v1
      and rows[1][1] == v1 and rows[1][2] == v2
      and rows[2][1] == v2 and rows[2][2] == raw0,
      f"{len(rows)} rows in pick_revisions")

# ---- 验收点 4：旧候选解快照不随历史记录变化；raw 只读 ----
run_after = client.get(f"/api/scenarios/runs/{run['id']}").json()
snap_after = next(s for s in run_after["input_snapshot"] if s["pick_id"] == pid)
check("旧候选解仍显示当时输入（raw 值，未受后续修订/撤销影响）",
      snap_after["effective_time_epoch"] == raw0 and snap_after["time_source"] == "raw"
      and run_after["input_snapshot"] == run["input_snapshot"])
p4 = next(p for p in client.get("/api/scenarios/outlier/picks").json() if p["id"] == pid)
check("raw 到时始终只读", p4["raw_time_epoch"] == raw0)

# ---- 边界：PATCH null 等价撤销；无修订时撤销不留记录；定位只用当前有效到时 ----
client.patch(f"/api/scenarios/picks/{pid}", json={"manual_time_epoch": v1, "note": "再次修订"})
client.patch(f"/api/scenarios/picks/{pid}", json={"manual_time_epoch": None,
                                                  "note": "用 PATCH null 清除"})
hist = client.get(f"/api/scenarios/picks/{pid}/history").json()
check("PATCH null 清除也记为 undo（manual v1 -> raw）",
      hist[-1]["action"] == "undo" and hist[-1]["old_time_epoch"] == v1
      and hist[-1]["new_time_epoch"] == raw0)
n_before = len(hist)
client.delete(f"/api/scenarios/picks/{pid}/manual")  # 此时已无 manual
hist = client.get(f"/api/scenarios/picks/{pid}/history").json()
check("无修订时撤销为空操作，不留记录", len(hist) == n_before)

run2 = client.post("/api/scenarios/locate", json={
    "scenario_key": "outlier", "phase": "P",
    "model_id": "homog-crust-6.0-3.46-v1", "label": "撤销后复算"}).json()
snap2 = next(s for s in run2["input_snapshot"] if s["pick_id"] == pid)
check("定位仍只使用当前有效到时（撤销后 = raw）",
      snap2["effective_time_epoch"] == raw0 and snap2["time_source"] == "raw")

print()
if failures:
    print(f"失败 {len(failures)} 项: {failures}")
    sys.exit(1)
print("全部验收点通过。")
