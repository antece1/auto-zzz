"""ZZZ 自动升级脚本（按 SPEC.md）。

用法：
  python upgrade.py --plan plan.json            # 演练（默认）
  python upgrade.py --plan plan.json --apply    # 真的升级（plan 需 approved_by_user=true）
  python upgrade.py --agent 简 --skill 特殊技 --to 12                              # 单步（开发测试用）

状态：框架完成；四类升级（level / skill / core / engine）的游戏内操作还在开发，
未实现的步骤会记成 skipped（原因「未实现」），不会点任何按钮。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 也能用 python -I 运行
from zzzgame import Game, StopRun

__version__ = "0.3.0"  # auto-zzz 版本，见仓库根目录 VERSION
ROOT = Path(__file__).resolve().parent  # 仓库里的 upgrade 目录
SKILLS = ['普攻', '闪避', '支援', '特殊技', '连携技']


QUEUE = ROOT.parent / 'daily' / 'queue.json'
REF_AGENTS = ROOT.parent / 'reference' / 'agents'
TEMPLATES = ROOT / 'templates'


def skill_item_name(agent_id: str, frm: int) -> str | None:
    """从 reference/agents/<id>.json 查某级技能要的芯片名（二级界面只有图标没有名字）。"""
    f = REF_AGENTS / f'{agent_id}.json'
    if not f.exists():
        return None
    ref = json.loads(f.read_text(encoding='utf-8'))
    row = next((r for r in ref.get('skill_per_level', []) if r['from'] == frm), None)
    return row['item'] if row else None


def add_to_queue(what: str, needs: list[tuple[str, int]]) -> bool:
    """按 SPEC：把这一步要的每种材料（二级界面上的总消耗）追加进 daily/queue.json；同一个 for 已在就不加。"""
    q = json.loads(QUEUE.read_text(encoding='utf-8')) if QUEUE.exists() else {'items': []}
    if any(i.get('for') == what for i in q['items']):
        return False
    now = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    now = now[:-2] + ':' + now[-2:] if len(now) > 5 else now
    for item, need in needs:
        q['items'].append({'item': item, 'need': need, 'for': what, 'added_at': now})
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


def card_match(png: bytes, agent_id: str) -> float | None:
    """代理人列表第一张卡和头像模板的相似度（0–1）；没有模板返回 None。"""
    tpl_path = TEMPLATES / f'{agent_id}_card.png'
    if not tpl_path.exists():
        return None
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    tpl = cv2.imdecode(np.fromfile(str(tpl_path), np.uint8), cv2.IMREAD_COLOR)
    roi = img[0:280, 1000:1300]
    return float(cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED).max())


class Skip(Exception):
    """这一步跳过（材料不够、当前值和 from 对不上、未实现）。"""


class Upgrader:
    def __init__(self, game: Game, apply: bool) -> None:
        self.g = game
        self.apply = apply
        self.dennies_before: int | None = None
        self.dennies_after: int | None = None
        self.sim: dict[tuple[str, str], int] = {}

    # 每类升级：读当前值 -> 核对 from -> 演练时算花费 / apply 时点升级 -> 再读核对
    def do_level(self, step: dict) -> str:
        raise Skip('未实现（阶段 1 开发中）')

    # ---------- 技能（1920×1080 坐标，2026-11-21 在简的技能页实测） ----------
    SKILL_ICON = {'普攻': (1035, 665), '闪避': (1205, 665), '支援': (1378, 665), '特殊技': (1550, 665), '连携技': (1722, 665)}
    SKILL_LV_X = {'普攻': 957, '闪避': 1130, '支援': 1302, '特殊技': 1482, '连携技': 1650}
    TAB_SKILL = (1372, 979)
    DIALOG_CLOSE = (1462, 167)
    BACK = (110, 50)

    # 代理人列表页：左下角是选中代理人的名字，卡片左边也有 基础/技能/装备 按钮（y≈818/897/977）
    # 详情页：底部标签 基础/技能/装备 在 y≈979–995
    @staticmethod
    def _is_detail(texts: list) -> bool:
        return any(t.text.strip() == '基础' and t.cy > 960 for t in texts)

    @staticmethod
    def _list_name(texts: list) -> str | None:
        t = next((t for t in texts if 150 < t.cx < 460 and 900 < t.cy < 990
                  and any('一' <= c <= '鿿' for c in t.text) and t.text.strip() != '影画'), None)
        return t.text if t else None

    def goto_agent(self, name_cn: str, agent_id: str) -> None:
        """C 打开代理人列表 → 点第一张卡（用户给要练的代理人标了星，排第一）→ 核对左下角名字 → 点「技能」进技能页。"""
        texts = self.g.ocr()
        if not self.g.find(texts, '代理人攻略'):
            self.g.key('c', '打开代理人列表', wait=3)
            texts = self.g.expect(['代理人攻略'], '代理人列表')
        if self._is_detail(texts):
            self.g.click_xy(*self.BACK, '从详情页回代理人列表', ['代理人攻略'], wait=3)
            texts = self.g.expect(['代理人攻略'], '代理人列表')
            if self._is_detail(texts):
                raise StopRun('回不到代理人列表')
        self.g.click_xy(1160, 140, '点列表第一张卡（标星的代理人）', ['代理人攻略'], wait=2.5)
        texts = self.g.expect(['代理人攻略'], '代理人列表')
        name = self._list_name(texts)
        score = card_match(self.g._get('/game/capture'), agent_id)
        self.g.log(f'列表选中 {name}，头像匹配 {score if score is None else round(score, 3)}')
        if score is not None and score < 0.85:
            p = self.g.shot('card_mismatch')
            raise Skip(f'列表第一张卡的头像不是 {name_cn}（匹配 {score:.2f}），截图 {p.name}；请给 {name_cn} 标星让她排第一')
        if not (name and name_cn in name):
            raise Skip(f'列表第一张卡是 {name}，不是 {name_cn}；请在游戏里给 {name_cn} 标星让她排第一')
        self.g.click_text('技能', '从列表进入技能页', region=(1050, 860, 1320, 935), wait=3)
        texts = self.g.expect(['代理人攻略'], '技能页')
        if not self._is_detail(texts):
            raise StopRun('点了「技能」但没进到详情页')

    def read_skills(self) -> dict[str, int]:
        texts = self.g.expect(['代理人攻略'], '技能页')
        out: dict[str, int] = {}
        for sk, cx in self.SKILL_LV_X.items():
            parts = sorted((t for t in texts if abs(t.cx - cx) < 75 and 715 < t.cy < 765), key=lambda t: t.x)
            digits = ''.join(ch for t in parts for ch in t.text if ch.isdigit())
            if len(digits) >= 3:  # 形如 0512 = 当前 05 / 上限 12
                out[sk] = int(digits[:-2])
        if len(out) != 5:
            p = self.g.shot('skill_levels_unreadable')
            raise StopRun(f'技能等级没读全：{out}，截图 {p.name}')
        return out

    @staticmethod
    def _cost_pairs(texts: list) -> list[tuple[int, int, int]]:
        """弹窗里 '有/需' 形式的数字，返回 (有, 需, y)。"""
        res = []
        for t in texts:
            s = t.text.replace(' ', '')
            if '/' in s and 780 < t.cy < 940:
                a, _, b = s.partition('/')
                a = ''.join(c for c in a if c.isdigit())
                b = ''.join(c for c in b if c.isdigit())
                if a and b:
                    res.append((int(a), int(b), t.cy))
        return res

    def do_skill(self, step: dict) -> str:
        sk = step['skill']
        frm, to = step.get('display_from', step['from']), step.get('display_to', step['to'])
        if to != frm + 1:
            raise Skip('一步只升 1 级，请把清单拆开')
        self.goto_agent(step['name_cn'], step['agent'])
        lv = self.read_skills()
        self.g.log(f'{step["name_cn"]} 当前技能 {lv}')
        key = (step['agent'], sk)
        if lv[sk] != frm:
            if not self.apply and self.sim.get(key) == frm:
                self.sim[key] = to
                return f'演练：前一步升完后是 {frm}，这一步的花费要到那时才能读到'
            raise Skip(f'当前 {sk} 是 {lv[sk]}，清单写的是 {frm}，账号数据变了')
        self.sim[key] = to
        self.dennies_after = None
        # 打开技能详情
        self.g.click_xy(*self.SKILL_ICON[sk], f'打开{sk}详情', ['代理人攻略'], wait=2)
        texts = self.g.expect(['技能强化', f'等级{frm}'], f'{sk}详情')
        # 打开强化弹窗
        self.g.click_text('技能强化', '打开强化弹窗', region=(1450, 960, 1900, 1060), wait=2)
        texts = self.g.expect(['技能强化', f'等级{frm}', f'等级{frm + 1}', '确定'], '强化弹窗')
        self.g.shot(f'{step["name_cn"]}_{sk}_{frm}_dialog')
        pairs = self._cost_pairs(texts)
        if not pairs:
            raise StopRun('强化弹窗里读不到花费')
        dennies = max(pairs, key=lambda p: p[0])  # 丁尼的拥有量最大
        mats = [p for p in pairs if p is not dennies]
        short = [p for p in pairs if p[0] < p[1]]
        cost_txt = f'丁尼 {dennies[1]}（有 {dennies[0]}），材料 ' + '，'.join(f'{n}（有 {h}）' for h, n, _ in mats)
        if short:
            item = skill_item_name(step['agent'], frm) or '技能芯片（名字待查）'
            needs = [('丁尼' if p is dennies else item, p[1]) for p in pairs]
            added = add_to_queue(describe(step), needs)
            self.g.log(f"材料不足，{'已加入' if added else '已在'}刷取队列：{needs}")
            self.g.click_xy(*self.DIALOG_CLOSE, '关闭弹窗（材料不足）', ['技能强化'])
            self.g.click_xy(*self.BACK, '回技能页', [f'等级{frm}'])
            raise Skip(f'材料或丁尼不足：{cost_txt}')
        if self.dennies_before is None:
            self.dennies_before = dennies[0]
        if not self.apply:
            self.g.click_xy(*self.DIALOG_CLOSE, '关闭弹窗（演练）', ['技能强化'])
            self.g.click_xy(*self.BACK, '回技能页', [f'等级{frm}'])
            return f'演练：会花 {cost_txt}'
        # 真升级
        self.g.click_text('确定', f'确认强化 {sk} {frm}→{frm + 1}', region=(1040, 870, 1340, 950), wait=3)
        self.g.shot(f'{step["name_cn"]}_{sk}_{frm}_after_confirm')
        # 关掉可能还开着的弹窗，回技能页核对
        for _ in range(3):
            texts = self.g.ocr()
            if self.g.find(texts, '代理人攻略') and self._is_detail(texts):
                break
            if self.g.find(texts, '技能强化') and self.g.find(texts, '确定'):
                pairs2 = self._cost_pairs(texts)
                if pairs2:
                    self.dennies_after = max(pairs2, key=lambda p: p[0])[0]
                self.g.click_xy(*self.DIALOG_CLOSE, '关闭弹窗', ['技能强化'])
            elif self.g.find(texts, '技能强化'):
                self.g.click_xy(*self.BACK, '回技能页', ['技能强化'])
            else:
                self.g.key('esc', '关闭提示')
        lv2 = self.read_skills()
        if lv2[sk] != frm + 1:
            raise StopRun(f'强化后 {sk} 是 {lv2[sk]}，应该是 {frm + 1}，停下检查')
        if self.dennies_after is not None and self.dennies_after != dennies[0] - dennies[1]:
            raise StopRun(f'丁尼对不上：强化前 {dennies[0]}，花 {dennies[1]}，现在 {self.dennies_after}')
        return f'{sk} {frm}→{frm + 1} 完成，花 {cost_txt}'

    def do_core(self, step: dict) -> str:
        raise Skip('未实现（阶段 3）')

    def do_engine(self, step: dict) -> str:
        raise Skip('未实现（阶段 4）')

    def run_step(self, step: dict) -> str:
        fn = {'level': self.do_level, 'skill': self.do_skill, 'core': self.do_core, 'engine': self.do_engine}.get(step['what'])
        if fn is None:
            raise Skip(f"未知类型 {step['what']}")
        return fn(step)


def describe(step: dict) -> str:
    name = step.get('name_cn') or step['agent']
    if step['what'] == 'skill':
        return f"{name} 技能 {step['skill']} {step.get('display_from', step['from'])}→{step.get('display_to', step['to'])}"
    label = {'level': '等级', 'core': '核心技', 'engine': '音擎'}[step['what']]
    return f"{name} {label} {step['from']}→{step['to']}"


def load_steps(args: argparse.Namespace) -> tuple[list[dict], bool]:
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
        steps = sorted(plan['steps'], key=lambda s: s['order'])
        return steps, bool(plan.get('approved_by_user'))
    if not args.agent:
        sys.exit('需要 --plan 或 --agent')
    step = {'order': 1, 'agent': args.agent, 'name_cn': args.agent, 'from': args.frm, 'to': args.to}
    if args.skill:
        step.update(what='skill', skill=args.skill, display_from=args.frm, display_to=args.to)
    else:
        step['what'] = args.what
    return [step], True  # 单步模式：命令行直接给出，视为用户当面确认


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", action="version", version=f"auto-zzz %(prog)s {__version__}")
    ap.add_argument('--plan')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--agent')
    ap.add_argument('--what', choices=['level', 'core', 'engine'], default='level')
    ap.add_argument('--skill', choices=SKILLS)
    ap.add_argument('--from', dest='frm', type=int)
    ap.add_argument('--to', type=int)
    ap.add_argument('--only', help='只执行这些 order，逗号分隔，如 1,2,3,4')
    args = ap.parse_args()

    stamp = time.strftime('%Y-%m-%d_%H%M')
    (ROOT / 'logs').mkdir(exist_ok=True)
    (ROOT / 'results').mkdir(exist_ok=True)
    g = Game(ROOT / 'logs' / stamp, ROOT / 'logs' / f'{stamp}.log')

    steps, approved = load_steps(args)
    if args.only:
        keep = {int(x) for x in args.only.split(',')}
        steps = [s for s in steps if s['order'] in keep]
    apply = args.apply and approved
    if args.apply and not approved:
        g.log('plan.json 没有 approved_by_user=true，只演练')
    g.log(f"{'真的升级' if apply else '演练'}，共 {len(steps)} 步")

    result: dict = {'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'applied': apply,
                    'plan': args.plan, 'steps': [], 'stopped_reason': None,
                    'dennies_before': None, 'dennies_after': None}
    up = Upgrader(g, apply)
    fails: dict[str, int] = {}
    try:
        g.precheck()
        for step in steps:
            what = describe(step)
            if fails.get(step['agent'], 0) >= 2:
                result['steps'].append({'order': step['order'], 'what': what, 'status': 'skipped', 'reason': '该代理人连续失败两次'})
                continue
            try:
                note = up.run_step(step)
                result['steps'].append({'order': step['order'], 'what': what, 'status': 'ok', 'note': note})
                fails[step['agent']] = 0
                g.log(f'OK {what} {note}')
            except Skip as e:
                result['steps'].append({'order': step['order'], 'what': what, 'status': 'skipped', 'reason': str(e)})
                g.log(f'跳过 {what}：{e}')
            except StopRun:
                raise
            except Exception as e:  # noqa: BLE001
                fails[step['agent']] = fails.get(step['agent'], 0) + 1
                result['steps'].append({'order': step['order'], 'what': what, 'status': 'failed', 'reason': repr(e)})
                g.log(f'失败 {what}：{e!r}')
    except StopRun as e:
        result['stopped_reason'] = str(e)
        g.log(f'停止：{e}')
    result['dennies_before'] = up.dennies_before
    result['dennies_after'] = up.dennies_after
    result['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    out = ROOT / 'results' / f'{stamp}.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    g.log(f'结果写到 {out}')
    return 0 if result['stopped_reason'] is None else 1


if __name__ == '__main__':
    sys.exit(main())
