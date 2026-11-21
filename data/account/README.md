# 作者账号的真实数据（示例）

2026-11-21 的账号快照：24 个代理人（等级、影画、技能、核心技、音擎、已装备的驱动盘）、仓库材料、丁尼、电量。
代理人数据来自 HoYoLAB 战绩接口，材料来自 OneDragon 截图 OCR。不含账号 UID，也不附截图（截图里有 UID）。

- `snapshot_2026-11-21.json`：完整快照
- `state/`：规划用的状态（格式同 `upgrade/state.example/`），复制成 `upgrade/state/` 就能直接跑 allocate.py 和 push_plan.py
- `plan.json`：按这份数据生成、作者确认过的 19 步升级清单
- `result_*.json`：第一次真升级（简 闪避 4→5）的结果
