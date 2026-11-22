# auto-zzz

**v0.3.0** · [在线打开资源调度员](https://antece1.github.io/auto-zzz/) · [更新记录](CHANGELOG.md)

绝区零（Zenless Zone Zero）培养自动化：算出该练谁、练到多少、缺什么材料，每天把刷取任务排进一条龙，并在游戏里自动点技能升级。

它建立在 [ZenlessZoneZero-OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)（绝区零一条龙）之上：截图、文字识别、点击都通过 OneDragon 的本机后端完成，本仓库不包含也不修改 OneDragon 的代码。

> 状态：早期版本。技能升级已在游戏里实测成功一次；等级、核心技、音擎升级还没实现（会被跳过，不会点任何按钮）。

*English summary: a resource planner and auto-upgrader for Zenless Zone Zero built on top of the OneDragon automation backend. It plans which agents to level and how far, pushes the daily farming list into OneDragon's charge plan, and clicks skill upgrades in game with screen checks before every click. Chinese (Simplified) client, 1920×1080 only.*

## 功能

| 模块 | 文件 | 做什么 |
|---|---|---|
| 资源分配 | `upgrade/allocate.py` | 按攻略优先级和你的背包，挑出"现在就付得起、最划算"的升级步骤，生成 `plan.json` |
| 自动升级 | `upgrade/upgrade.py` | 按 `plan.json` 在游戏里升级；默认只演练，确认过的清单加 `--apply` 才会花材料 |
| 每晚同步 | `daily/hoyolab_sync.py` | 每晚从 HoYoLAB 战绩接口读代理人、技能、核心技、音擎、驱动盘、电量，更新规划数据，并把数据（不含 UID）推到 GitHub Pages |
| 每日推送 | `daily/push_plan.py` | 每天把缺口换算成副本，写进 OneDragon 的体力计划（charge_plan.yml），然后一条龙照常跑 |
| 刷取队列 | `daily/queue.json` | 升级时材料不够，自动记下来，第二天优先刷 |
| 优先培养 | `upgrade/state/plan/focus.json` | 给角色打星：它的材料排最前，并每天刷它的驱动盘套装 |
| 资源调度员网页 | `docs/index.html` | 培养材料清单、缺口、每日排期、驱动盘检查、星标优先；[在线打开](https://antece1.github.io/auto-zzz/)，点「加载作者账号示例」可以看真实账号的效果 |
| 参考数据 | `reference/` | 升级消耗、掉落、各代理人核心技材料、培养优先级（附来源）；`reference/agents/` 是 24 个代理人各自的升级消耗表 |
| 真实账号示例 | `data/account/` | 作者 2026-11-21 的账号快照、规划状态、确认过的升级清单和第一次升级结果（不含 UID） |

## 自动升级的流程

技能升级按这五步走，每次点击前都先用 OCR 确认画面：

1. 按 `C` 键（代理人快捷键）。
2. 进入代理人列表后，识别角色头像图片，确认角色。
3. 点「技能」。
4. 点要强化的技能。
5. 进入二级界面点「确认」。如果材料不够，就把还缺的材料加入刷取队列，跳过这一步。

安全规则（详见 `upgrade/SPEC.md`）：

- 默认演练，不加 `--apply` 不会花任何东西；`plan.json` 必须 `approved_by_user: true` 才能真升级。
- 每一步先读游戏里的当前等级，和清单对不上就跳过。
- 升级前后都读丁尼和等级核对，对不上立刻停。
- 不合成、不分解、不花菲林、不碰驱动盘。Ctrl+C 随时停。

## 用到的识别技术

这些能力来自 OneDragon，本工具通过它的后端调用：

| 技术 | 用来做什么 | 实现 |
|---|---|---|
| OCR 文字识别 | 读按钮文字、副本名、剩余次数 | PaddleOCR 模型转成 ONNX，分三段：检测文字位置 → 判断方向 → 识别文字 |
| 模板匹配 | 找图标、按钮 | OpenCV matchTemplate |
| YOLO 目标检测 | ①战斗中敌人出招前的黄光/红光（判断闪避、招架）②零号空洞格子上的事件 ③迷失之地里的目标 | YOLOv8 模型转 ONNX（flash_classifier、hollow_zero_event、lost_void_det） |
| 声音识别 | 敌人出招的提示音 → 闪避，有时比看画面更快 | 录下游戏进程的声音，滤掉 1000Hz 以下的低频，再用 FFT 和预先录好的提示音比对 |

auto-zzz 自己用到的是前两项：OCR 读界面文字和数字（技能等级、材料"有/需"），模板匹配确认代理人头像（`upgrade/templates/`）。

## 准备

1. 安装并能正常运行 [OneDragon](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)。
2. 游戏设置为 **1920×1080**，简体中文。
3. 启动 OneDragon 后端（GUI「开发工具 → MCP 服务」，或命令行）：
   ```
   cd <OneDragon 目录>
   uv run python -m zzz_od.backend.entry.server --host 127.0.0.1 --port 23001
   ```
4. 如果 OneDragon 不在 `C:\ZZZ-OneDragon`，设置环境变量 `ONEDRAGON_DIR`；账号实例不是 `01` 时设置 `ONEDRAGON_INSTANCE`；后端不在默认地址时设置 `AUTOZZZ_BACKEND`。
5. 用 OneDragon 的 Python 运行脚本（自带 PyYAML、OpenCV）：`<OneDragon>\.venv\Scripts\python.exe`。

## 使用

1. **准备账号数据**：把 `upgrade/state.example/` 复制成 `upgrade/state/`，按你的账号改等级、技能、背包（字段说明见 `upgrade/SPEC.md`）。想先看一份真实账号的效果，可以复制 `data/account/state/`。`upgrade/state/` 不会被提交。
2. **生成升级清单**：
   ```
   python upgrade/allocate.py --state upgrade/state --prio reference/agent_investment.json --out upgrade/plan.json --reserve 100000
   ```
   看一遍清单，确认后把 `approved_by_user` 改成 `true`。
3. **演练，再真升级**：
   ```
   python upgrade/upgrade.py --plan upgrade/plan.json
   python upgrade/upgrade.py --plan upgrade/plan.json --apply --only 1
   ```
   第一次建议只跑第 1 步，在游戏里核对后再继续。
4. **每晚同步**：把 `daily/hoyolab_config.example.json` 复制成 `daily/hoyolab_config.json`，填上 HoYoLAB 的 `ltoken_v2`、`ltuid_v2`（浏览器 F12 → Application → Cookies → hoyolab.com）和游戏 UID。`python daily/hoyolab_sync.py --dry-run` 先试读。作者的安排是 Windows 计划任务 23:00 同步、23:05 跑一条龙。
5. **每日推送**：`python daily/push_plan.py --dry-run` 先看预览；`scripts/run_daily.ps1` 是一个"推送后启动一条龙"的示例，可以挂到 Windows 计划任务。每天的电量和是否启用在 `daily/config.json`。

## 免责声明

- 本项目是非官方的第三方工具，与 HoYoverse / 米哈游无关。自动化操作游戏可能违反游戏的用户协议，使用风险自负。
- 消耗和掉落数据整理自 B 站 wiki、Prydwen、Game8 等社区资料，标"估算"的数字没有可靠来源；游戏更新后可能变化。
- 仓库只附带一张代理人头像模板（`upgrade/templates/jane_doe_card.png`），用于确认角色；其他头像请自己截。

## 许可证

GPL-3.0，与 OneDragon 一致。
