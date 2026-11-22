# 更新记录

版本号按 [语义化版本](https://semver.org/lang/zh-CN/)：`主版本.次版本.修订号`。1.0 之前次版本号变化可能包含不兼容的改动。

## v0.3.0 — 2026-11-21

- 新增每晚同步 `daily/hoyolab_sync.py`：直接请求 HoYoLAB 战绩接口（不用浏览器），读 25 个代理人的等级、影画、技能、核心技、音擎、已装备驱动盘和电量，更新规划数据，并把数据推到 GitHub Pages。推送前检查数据里没有 UID；接口原始返回只留在本机。
- 网页在 GitHub Pages 上打开时自动载入最新账号数据（`docs/data/`），顶部显示同步时间和电量；网页上改的目标和星标保留在本机浏览器，不会被每晚数据覆盖。
- 每日推送：刷取记录只在重新读背包时清空，每晚同步等级不再把它清掉。
- 新代理人会自动加入（默认不计入）。

## v0.2.0 — 2026-11-21

- 资源调度员网页移到 `docs/index.html`，用 GitHub Pages 发布：https://antece1.github.io/auto-zzz/
- 网页新增「加载作者账号示例」，显示版本号。
- 新增 `data/account/`：作者账号的真实快照、规划状态、确认过的升级清单和第一次升级结果（不含 UID）。
- 新增 `reference/agents/`：24 个代理人各自的升级消耗表；技能升级材料不够时，刷取队列能写出准确的芯片名。
- 附带简的头像模板 `upgrade/templates/jane_doe_card.png`。
- 名称和版本统一：仓库根目录 `VERSION`；所有脚本有 `__version__` 和 `--version`；后端连接标识为 `auto-zzz`。

## v0.1.0 — 2026-11-21

- 第一个公开版本：资源分配 `upgrade/allocate.py`、自动升级 `upgrade/upgrade.py`（技能升级已实测）、每日推送 `daily/push_plan.py`、刷取队列、星标优先培养、规划网页、参考数据。
