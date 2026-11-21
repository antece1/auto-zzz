# 更新记录

版本号按 [语义化版本](https://semver.org/lang/zh-CN/)：`主版本.次版本.修订号`。1.0 之前次版本号变化可能包含不兼容的改动。

## v0.2.0 — 2026-11-21

- 资源调度员网页移到 `docs/index.html`，用 GitHub Pages 发布：https://antece1.github.io/auto-zzz/
- 网页新增「加载作者账号示例」，显示版本号。
- 新增 `data/account/`：作者账号的真实快照、规划状态、确认过的升级清单和第一次升级结果（不含 UID）。
- 新增 `reference/agents/`：24 个代理人各自的升级消耗表；技能升级材料不够时，刷取队列能写出准确的芯片名。
- 附带简的头像模板 `upgrade/templates/jane_doe_card.png`。
- 名称和版本统一：仓库根目录 `VERSION`；所有脚本有 `__version__` 和 `--version`；后端连接标识为 `auto-zzz`。

## v0.1.0 — 2026-11-21

- 第一个公开版本：资源分配 `upgrade/allocate.py`、自动升级 `upgrade/upgrade.py`（技能升级已实测）、每日推送 `daily/push_plan.py`、刷取队列、星标优先培养、规划网页、参考数据。
