"""ZZZ 资源调度员：把现有背包分配给最划算的升级步骤，生成 plan.json。

用法:
  python allocate.py --state <db 导出目录> --prio <priorities.json> --out plan.json [--reserve 0]

输入:
  <state>/plan/current.json    {"data": {"cur": {...}}} 或 {"cur": {...}}   当前等级（技能为去掉影画的基础等级）
  <state>/plan/inventory.json  背包 {"own": {名字: 数量}}
  <state>/meta/agents.json     代理人元数据（职业/芯片/核心技材料/影画）
  priorities.json              {"agents": {"中文名": {priority_tier, skill_order, skill_targets, core_target, level60, wengine_note}}}

规则（和 SPEC.md 一致）:
  - 不合成材料：每一步只用背包里正好那一档的材料。
  - 技能 12 级要代理人 60 级和 1 个「仓鼠笼」访问器。核心技每级有代理人等级门槛。
  - 每次选"价值 / 丁尼"最高、且现在付得起的下一步，直到付不起为止。
"""
import argparse, json, os, sys

__version__ = "0.3.0"  # auto-zzz 版本，见仓库根目录 VERSION
SKILLS = ["普攻", "闪避", "支援", "特殊技", "连携技"]
SKILL_LV = {2: ("C", 2, 2000), 3: ("C", 3, 3000), 4: ("B", 2, 6000), 5: ("B", 3, 9000), 6: ("B", 4, 12000),
            7: ("B", 6, 18000), 8: ("A", 5, 45000), 9: ("A", 8, 67500), 10: ("A", 10, 90000),
            11: ("A", 12, 112500), 12: ("A", 15, 135000)}
CORE_ST = {1: (0, 0, 5000, 15), 2: (2, 0, 12000, 25), 3: (4, 0, 28000, 35), 4: (9, 2, 60000, 45),
           5: (15, 3, 100000, 55), 6: (30, 4, 200000, 60)}
LV_BANDS = [(1, 10, 6000), (10, 20, 24000), (20, 30, 60000), (30, 40, 135000), (40, 50, 225000), (50, 60, 450000)]
PROMO = {10: ("C", 4, 24000), 20: ("B", 12, 56000), 30: ("B", 20, 120000), 40: ("A", 10, 200000), 50: ("A", 20, 400000)}
W_BANDS = {"S": [(1, 10, 4000), (10, 20, 16000), (20, 30, 40000), (30, 40, 90000), (40, 50, 150000), (50, 60, 300000)],
           "A": [(1, 10, 3200), (10, 20, 12800), (20, 30, 32000), (30, 40, 72000), (40, 50, 120000), (50, 60, 240000)],
           "B": [(1, 10, 2400), (10, 20, 9600), (20, 30, 24000), (30, 40, 54000), (40, 50, 90000), (50, 60, 180000)]}
W_PROMO = {"S": {10: ("C", 4, 12000), 20: ("B", 12, 28000), 30: ("B", 20, 60000), 40: ("A", 10, 100000), 50: ("A", 20, 200000)},
           "A": {10: ("C", 3, 9600), 20: ("B", 10, 22400), 30: ("B", 16, 48000), 40: ("A", 8, 80000), 50: ("A", 16, 160000)},
           "B": {10: ("C", 2, 7200), 20: ("B", 7, 16800), 30: ("B", 12, 36000), 40: ("A", 6, 60000), 50: ("A", 12, 120000)}}
A_SEAL = {"强攻": "先行者", "击破": "破阵者", "异常": "掌控者", "支援": "统御者", "防护": "捍卫者", "命破": "裁决者"}
EXP_A = {"见习调查员记录": 100, "正式调查员记录": 600, "资深调查员记录": 3000}
EXP_W = {"音擎蓄电池": 100, "变频音擎电源": 600, "音擎能源模块": 3000}
TIER_W = {"high": 3.0, "mid": 1.6, "low": 0.6}


def seal(sp, t): return {"C": f"初阶{sp}认证章", "B": f"高阶{sp}认证章", "A": f"{A_SEAL.get(sp, sp)}认证章"}[t]
def chip(c, t): return {"C": f"基础{c}芯片", "B": f"进阶{c}芯片", "A": f"特化{c}芯片"}[t]
def comp(sp, t): return {"C": f"{sp}组件", "B": f"增强型{sp}组件", "A": f"特化型{sp}组件"}[t]


def exp_between(bands, a, b):
    return sum(e * (min(b, t) - max(a, f)) / (t - f) for f, t, e in bands if min(b, t) > max(a, f))


def load(path):
    d = json.load(open(path, encoding="utf-8-sig"))
    return d.get("data", d)


class Bag:
    def __init__(self, own): self.own = {k: float(v or 0) for k, v in own.items()}
    def exp(self, table): return sum(self.own.get(n, 0) * v for n, v in table.items())
    def can(self, cost):
        for k, v in cost.items():
            if k == "_expA" and self.exp(EXP_A) < v: return False
            if k == "_expW" and self.exp(EXP_W) < v: return False
            if not k.startswith("_") and self.own.get(k, 0) < v: return False
        return True
    def take_exp(self, table, need):  # big items first, like the game's auto-fill
        for n, v in sorted(table.items(), key=lambda x: -x[1]):
            use = min(self.own.get(n, 0), need // v); self.own[n] = self.own.get(n, 0) - use; need -= use * v
        for n, v in sorted(table.items(), key=lambda x: x[1]):  # cover the remainder with the smallest item
            while need > 0 and self.own.get(n, 0) > 0: self.own[n] -= 1; need -= v
    def pay(self, cost):
        for k, v in cost.items():
            if k == "_expA": self.take_exp(EXP_A, v)
            elif k == "_expW": self.take_exp(EXP_W, v)
            else: self.own[k] = self.own.get(k, 0) - v


def tracks(aid, meta, cur, pr):
    """Yield generator functions; each returns the next step for one upgrade track, or None."""
    w = TIER_W.get(pr.get("priority_tier", "low"), 0.6)
    order = pr.get("skill_order") or ["特殊技", "连携技", "普攻", "支援", "闪避"]
    st = pr.get("skill_targets") or {}
    out = []
    for i, sk in enumerate(SKILLS):
        tgt = int(st.get(sk, 0) or 0)
        rank = order.index(sk) if sk in order else 4
        val = {0: 6, 1: 5, 2: 3, 3: 1, 4: 0.6}[min(rank, 4)]
        out.append(("skill", i, tgt, w * val))
    out.append(("core", None, int(pr.get("core_target", 6) or 0), w * 9))
    l60 = pr.get("level60", "nice")
    out.append(("level", None, 60 if l60 in ("important", "nice") else cur["lv"], w * (8 if l60 == "important" else 4)))
    out.append(("engine", None, 60 if cur.get("wr", "-") != "-" else 0, w * (3 if "high" in str(pr.get("wengine_note", "")).lower() or "高" in str(pr.get("wengine_note", "")) else 2)))
    return out


def next_step(kind, idx, tgt, cur, meta):
    m = meta.get("m", 0) or 0
    bonus = (2 if m >= 3 else 0) + (2 if m >= 5 else 0)
    if kind == "skill":
        lv = cur["sk"][idx]
        if lv >= tgt or lv >= 12: return None
        t, n, d = SKILL_LV[lv + 1]
        cost = {chip(meta["chip"], t): n, "丁尼": d}
        if lv + 1 == 12:
            if cur["lv"] < 60: return None
            cost["「仓鼠笼」访问器"] = 1
        return {"what": "skill", "skill": SKILLS[idx], "from": lv, "to": lv + 1,
                "display_from": lv + bonus, "display_to": lv + 1 + bonus, "cost": cost}
    if kind == "core":
        c = cur["core"]
        if c >= tgt or c >= 6: return None
        h, nb, d, gate = CORE_ST[c + 1]
        if cur["lv"] < gate: return None
        cost = {"丁尼": d}
        if h: cost[meta["hdd"]] = h
        if nb: cost[meta["nh"]] = nb
        return {"what": "core", "from": c, "to": c + 1, "cost": cost}
    if kind == "level":
        lv = cur["lv"]
        if lv >= tgt: return None
        nxt = min(60, (lv // 10 + 1) * 10) if lv % 10 else lv + 10
        cost = {"_expA": round(exp_between(LV_BANDS, lv, nxt))}
        if lv % 10 == 0 and lv in PROMO:  # at a cap: promotion first
            t, n, d = PROMO[lv]; cost[seal(meta["sp"], t)] = n; cost["丁尼"] = d
        return {"what": "level", "from": lv, "to": nxt, "cost": cost}
    if kind == "engine":
        wr, wl = cur.get("wr", "-"), cur.get("wl", 1)
        if wr == "-" or wl >= tgt: return None
        nxt = min(60, (wl // 10 + 1) * 10) if wl % 10 else wl + 10
        cost = {"_expW": round(exp_between(W_BANDS[wr], wl, nxt))}
        if wl % 10 == 0 and wl in W_PROMO[wr]:
            t, n, d = W_PROMO[wr][wl]; cost[comp(meta["sp"], t)] = n; cost["丁尼"] = d
        return {"what": "engine", "from": wl, "to": nxt, "cost": cost}


def apply_step(cur, s):
    if s["what"] == "skill": cur["sk"][SKILLS.index(s["skill"])] = s["to"]
    elif s["what"] == "core": cur["core"] = s["to"]
    elif s["what"] == "level": cur["lv"] = s["to"]
    elif s["what"] == "engine": cur["wl"] = s["to"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", action="version", version=f"auto-zzz %(prog)s {__version__}")
    ap.add_argument("--state", required=True); ap.add_argument("--prio", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--reserve", type=int, default=0, help="留着不花的丁尼")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    cur_all = load(os.path.join(a.state, "plan", "current.json"))["cur"]
    bag = Bag(load(os.path.join(a.state, "plan", "inventory.json"))["own"])
    bag.own["丁尼"] = bag.own.get("丁尼", 0) - a.reserve
    metas = {x["id"]: x for x in load(os.path.join(a.state, "meta", "agents.json"))["list"]}
    prio = json.load(open(a.prio, encoding="utf-8-sig"))["agents"]
    name2id = {m["name"]: i for i, m in metas.items()}
    name2id.update({"星见雅": "hoshimi_miyabi", "雅": "hoshimi_miyabi"})
    fp = os.path.join(a.state, "plan", "focus.json")
    stars = set(load(fp).get("starred", [])) if os.path.exists(fp) else set()
    live = []  # (agent id, kind, idx, target, weight)
    for name, pr in prio.items():
        aid = name2id.get(name)
        if not aid or aid not in cur_all: print("skip unknown agent", name, file=sys.stderr); continue
        boost = 4.0 if aid in stars else 1.0  # ★ 优先培养：权重 x4
        for kind, idx, tgt, wgt in tracks(aid, metas[aid], cur_all[aid], pr):
            live.append((aid, kind, idx, tgt, wgt * boost))
    steps, long_targets = [], {}
    while True:
        best = None
        for aid, kind, idx, tgt, wgt in live:
            s = next_step(kind, idx, tgt, cur_all[aid], metas[aid])
            if not s or not bag.can(s["cost"]): continue
            den = s["cost"].get("丁尼", 0) + 0.15 * (s["cost"].get("_expA", 0) + s["cost"].get("_expW", 0)) / 10
            score = wgt / max(den, 1000) ** 0.5  # 重要性优先，便宜只是次要因素
            if not best or score > best[0]: best = (score, aid, s)
        if not best: break
        _, aid, s = best
        bag.pay(s["cost"]); apply_step(cur_all[aid], s)
        s.update(order=len(steps) + 1, agent=aid, name_cn=metas[aid]["name"])
        steps.append(s)
    for name, pr in prio.items():
        aid = name2id.get(name)
        if aid: long_targets[aid] = {"skills": pr.get("skill_targets"), "core": pr.get("core_target"), "tier": pr.get("priority_tier")}
    plan = {"generated_at": None, "approved_by_user": False, "approved_note": None, "steps": steps,
            "budget_after": {k: round(v) for k, v in bag.own.items() if k == "丁尼" or v < 0},
            "reserve_dennies": a.reserve, "long_term_targets": long_targets}
    json.dump(plan, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.stdout.reconfigure(encoding="utf-8")
    for s in steps:
        print(f"{s['order']:>2}. {s['name_cn']} {s['what']} {s.get('skill','')} {s['from']}->{s['to']}  {s['cost']}")
    print("丁尼剩余", round(bag.own.get("丁尼", 0) + a.reserve))


if __name__ == "__main__":
    main()
