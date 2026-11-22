from __future__ import annotations

import json
import time
from pathlib import Path

from one_dragon.utils import cv2_utils, os_utils
from one_dragon.utils.log_utils import log
from zzz_od.application.agent_upgrade.agent_upgrade_game import (
    StopRun,
    Text,
    UpgradeGame,
)

SKILLS: list[str] = ['普攻', '闪避', '支援', '特殊技', '连携技']


def assets_dir() -> Path:
    """随代码提交的资源：头像模板 templates/、各代理人升级消耗表 agents/、清单示例"""
    return Path(os_utils.get_path_under_work_dir('assets', 'agent_upgrade'))


def queue_path() -> Path:
    """
    刷取队列：升级时材料不够，把这一步要的材料记下来，给以后的每日刷取用。
    放在 config/agent_upgrade/queue.json（已 gitignore）
    """
    return Path(os_utils.get_path_under_work_dir('config', 'agent_upgrade')) / 'queue.json'


class Skip(Exception):
    """这一步跳过：材料不够、当前值和清单的 from 对不上、还没实现"""


def skill_item_name(agent_id: str, frm: int) -> str | None:
    """从 assets/agent_upgrade/agents/<id>.json 查某级技能要的芯片名（强化弹窗里只有图标没有名字）"""
    path = assets_dir() / 'agents' / f'{agent_id}.json'
    if not path.exists():
        return None
    ref = json.loads(path.read_text(encoding='utf-8'))
    row = next((r for r in ref.get('skill_per_level', []) if r['from'] == frm), None)
    return row['item'] if row else None


def add_to_queue(what: str, needs: list[tuple[str, int]]) -> bool:
    """
    把这一步要的每种材料（强化弹窗上的总消耗，不是差额）追加进刷取队列
    :param what: 这一步的描述，同一个描述已在队列里就不重复加
    :param needs: (材料名, 需要数量)
    :return: 是否新加入
    """
    path = queue_path()
    q = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'items': []}
    if any(i.get('for') == what for i in q['items']):
        return False
    now = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    now = now[:-2] + ':' + now[-2:] if len(now) > 5 else now
    for item, need in needs:
        q['items'].append({'item': item, 'need': need, 'for': what, 'added_at': now})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding='utf-8')
    return True


def card_match(game: UpgradeGame, agent_id: str) -> float | None:
    """代理人列表第一张卡和头像模板的相似度（0–1）；没有模板返回 None"""
    import cv2

    tpl_path = assets_dir() / 'templates' / f'{agent_id}_card.png'
    if not tpl_path.exists():
        return None
    tpl = cv2_utils.read_image(str(tpl_path))
    image = game.screenshot()
    if tpl is None:
        return None
    roi = image[0:280, 1000:1300]
    return float(cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED).max())


def describe(step: dict) -> str:
    """一步的中文描述，如「简 技能 闪避 4→5」"""
    name = step.get('name_cn') or step['agent']
    if step['what'] == 'skill':
        frm = step.get('display_from', step['from'])
        to = step.get('display_to', step['to'])
        return f"{name} 技能 {step['skill']} {frm}→{to}"
    label = {'level': '等级', 'core': '核心技', 'engine': '音擎'}.get(step['what'], step['what'])
    return f"{name} {label} {step['from']}→{step['to']}"


def load_plan(plan_path: Path) -> tuple[list[dict], bool]:
    """
    读升级清单
    :return: (按 order 排好的步骤, approved_by_user)
    """
    if not plan_path.exists():
        raise StopRun(f'找不到升级清单 {plan_path}，示例见 assets/agent_upgrade/plan.example.json')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    steps = sorted(plan.get('steps', []), key=lambda s: s['order'])
    return steps, bool(plan.get('approved_by_user'))


class Upgrader:
    """
    按清单一步步升级。每类升级：读当前值 → 核对 from → 演练时只读花费 / 真升级时点确认 → 再读核对。
    当前只实现了技能；等级、核心技、音擎会记成跳过，不点任何按钮。
    """

    # 技能页（1920×1080 坐标，2026-11-21 在简的技能页实测）
    SKILL_ICON: dict[str, tuple[int, int]] = {
        '普攻': (1035, 665), '闪避': (1205, 665), '支援': (1378, 665), '特殊技': (1550, 665), '连携技': (1722, 665),
    }
    SKILL_LV_X: dict[str, int] = {'普攻': 957, '闪避': 1130, '支援': 1302, '特殊技': 1482, '连携技': 1650}
    DIALOG_CLOSE: tuple[int, int] = (1462, 167)
    BACK: tuple[int, int] = (110, 50)

    def __init__(self, game: UpgradeGame, apply: bool) -> None:
        self.g: UpgradeGame = game
        self.apply: bool = apply
        self.dennies_before: int | None = None
        self.dennies_after: int | None = None
        self.sim: dict[tuple[str, str], int] = {}  # 演练时记下「前一步升完后」的等级

    def run_step(self, step: dict) -> str:
        fn = {'level': self.do_level, 'skill': self.do_skill,
              'core': self.do_core, 'engine': self.do_engine}.get(step['what'])
        if fn is None:
            raise Skip(f"未知类型 {step['what']}")
        return fn(step)

    def do_level(self, step: dict) -> str:
        raise Skip('未实现（等级和突破）')

    def do_core(self, step: dict) -> str:
        raise Skip('未实现（核心技）')

    def do_engine(self, step: dict) -> str:
        raise Skip('未实现（音擎）')

    # ---------- 进入代理人技能页 ----------
    @staticmethod
    def _is_detail(texts: list[Text]) -> bool:
        """详情页底部有 基础/技能/装备 标签（y≈979–995）"""
        return any(t.text.strip() == '基础' and t.cy > 960 for t in texts)

    @staticmethod
    def _list_name(texts: list[Text]) -> str | None:
        """代理人列表页左下角是选中代理人的名字"""
        t = next((t for t in texts if 150 < t.cx < 460 and 900 < t.cy < 990
                  and any('一' <= c <= '鿿' for c in t.text) and t.text.strip() != '影画'), None)
        return t.text if t else None

    def goto_agent(self, name_cn: str, agent_id: str) -> None:
        """按 C 打开代理人列表 → 点第一张卡（要练的代理人在游戏里标星，排第一）→ 核对头像和名字 → 点「技能」"""
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
        score = card_match(self.g, agent_id)
        log.info(f'列表选中 {name}，头像匹配 {score if score is None else round(score, 3)}')
        if score is not None and score < 0.85:
            path = self.g.shot('card_mismatch')
            raise Skip(f'列表第一张卡的头像不是 {name_cn}（匹配 {score:.2f}），截图 {path.name}；'
                       f'请在游戏里给 {name_cn} 标星让其排第一')
        if not (name and name_cn in name):
            raise Skip(f'列表第一张卡是 {name}，不是 {name_cn}；请在游戏里给 {name_cn} 标星让其排第一')
        self.g.click_text('技能', '从列表进入技能页', region=(1050, 860, 1320, 935), wait=3)
        texts = self.g.expect(['代理人攻略'], '技能页')
        if not self._is_detail(texts):
            raise StopRun('点了「技能」但没进到详情页')

    def read_skills(self) -> dict[str, int]:
        """读技能页 5 个技能的当前等级（游戏里显示的数字，含影画加成）"""
        texts = self.g.expect(['代理人攻略'], '技能页')
        out: dict[str, int] = {}
        for sk, cx in self.SKILL_LV_X.items():
            parts = sorted((t for t in texts if abs(t.cx - cx) < 75 and 715 < t.cy < 765), key=lambda t: t.x)
            digits = ''.join(ch for t in parts for ch in t.text if ch.isdigit())
            if len(digits) >= 3:  # 形如 0512 = 当前 05 / 上限 12
                out[sk] = int(digits[:-2])
        if len(out) != 5:
            path = self.g.shot('skill_levels_unreadable')
            raise StopRun(f'技能等级没读全：{out}，截图 {path.name}')
        return out

    @staticmethod
    def _cost_pairs(texts: list[Text]) -> list[tuple[int, int, int]]:
        """强化弹窗里「有/需」形式的数字，返回 (有, 需, y)"""
        res: list[tuple[int, int, int]] = []
        for t in texts:
            s = t.text.replace(' ', '')
            if '/' in s and 780 < t.cy < 940:
                a, _, b = s.partition('/')
                a = ''.join(c for c in a if c.isdigit())
                b = ''.join(c for c in b if c.isdigit())
                if a and b:
                    res.append((int(a), int(b), t.cy))
        return res

    # ---------- 技能 ----------
    def do_skill(self, step: dict) -> str:
        sk = step['skill']
        frm = step.get('display_from', step['from'])
        to = step.get('display_to', step['to'])
        if to != frm + 1:
            raise Skip('一步只升 1 级，请把清单拆开')
        self.goto_agent(step['name_cn'], step['agent'])
        lv = self.read_skills()
        log.info(f"{step['name_cn']} 当前技能 {lv}")
        key = (step['agent'], sk)
        if lv[sk] != frm:
            if not self.apply and self.sim.get(key) == frm:
                self.sim[key] = to
                return f'演练：前一步升完后是 {frm}，这一步的花费要到那时才能读到'
            raise Skip(f'当前 {sk} 是 {lv[sk]}，清单写的是 {frm}，账号数据变了')
        self.sim[key] = to
        self.dennies_after = None

        self.g.click_xy(*self.SKILL_ICON[sk], f'打开{sk}详情', ['代理人攻略'], wait=2)
        self.g.expect(['技能强化', f'等级{frm}'], f'{sk}详情')
        self.g.click_text('技能强化', '打开强化弹窗', region=(1450, 960, 1900, 1060), wait=2)
        texts = self.g.expect(['技能强化', f'等级{frm}', f'等级{frm + 1}', '确定'], '强化弹窗')
        self.g.shot(f"{step['agent']}_{sk}_{frm}_dialog")
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
            log.info(f"材料不足，{'已加入' if added else '已在'}刷取队列：{needs}")
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
        self.g.shot(f"{step['agent']}_{sk}_{frm}_after_confirm")
        for _ in range(3):  # 关掉可能还开着的弹窗，回技能页核对
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
