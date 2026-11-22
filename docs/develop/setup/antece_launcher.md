# antece版 桌面启动器

绝区零一条龙 antece版（代码在 [antece1/auto-zzz](https://github.com/antece1/auto-zzz)）用自己的目录运行，不和官方安装共用代码，避免官方启动器自动更新时把 antece版的改动覆盖掉。

## 和官方版的区别

- `config/repository.yml`：代码源只有 `antece1/auto-zzz`，界面里「同步代码」也从这里拉，不回退到官方仓库。
- 窗口标题「绝区零一条龙 antece版」，图标 `assets/ui/antece_logo.ico`。

## 启动器

`deploy/antece_launcher.pyw`，桌面快捷方式用 `.venv\Scripts\pythonw.exe` 运行它（不弹黑框）：

1. 当前在 `main` 分支、没有未提交的改动时，从 antece1/auto-zzz 拉取并快进到最新代码；其他情况跳过更新，用本地代码启动。
2. 更新里 `pyproject.toml` / `uv.lock` 有变化时，运行 `uv sync --frozen --inexact` 同步依赖。
3. 启动 `src/zzz_od/gui/app.py`。

日志在 `.log/antece_launcher.log`。

## 安装一份运行目录

```powershell
git clone https://github.com/antece1/auto-zzz.git C:\ZZZ-OneDragon-antece
cd C:\ZZZ-OneDragon-antece
uv sync
```

账号和设置可以从官方安装目录复制 `config/` 里被 gitignore 的文件（`config/01/`、`env.yml` 等）和 `assets/models/`。

桌面快捷方式：目标 `C:\ZZZ-OneDragon-antece\.venv\Scripts\pythonw.exe`，参数 `deploy\antece_launcher.pyw`，起始位置 `C:\ZZZ-OneDragon-antece`，图标 `assets\ui\antece_logo.ico`。

开发用的仓库和运行目录分开：在开发仓库里切分支、改代码不会影响桌面启动的 antece版。

## 每晚 HoYoLAB 同步

`tools/planner/hoyolab_sync.py`：从 HoYoLAB 战绩接口读代理人、技能、核心技、音擎、驱动盘和电量，更新资源调度员 2.0 的数据并推到 GitHub Pages（`docs/data/`）。

- 凭证：`config/planner/hoyolab_config.json`（示例 `tools/planner/hoyolab_config.example.json`）；规划数据：`config/planner/state/`；日志：`.log/planner/hoyolab_sync.log`。
- 推送前先快进到 antece1/auto-zzz 最新的 main，再提交 `docs/data/`，main 被别处更新过也不会被拒绝；数据里出现 UID 就停止推送。
- 只在 `main` 分支、没有其他未提交改动时发布。
- 计划任务每天 23:00 运行：`C:\ZZZ-OneDragon-antece\.venv\Scripts\pythonw.exe C:\ZZZ-OneDragon-antece\tools\planner\hoyolab_sync.py`。
