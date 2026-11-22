"""每日推送：把"每日电量排期"的第 1 天写进 OneDragon 体力计划（charge_plan.yml）。

由 scripts\\run_daily.ps1 在启动一条龙之前调用（计划任务每天 23:00）。
用 OneDragon 的 venv 运行（需要 PyYAML）:
  <OneDragon>\\.venv\\Scripts\\python.exe push_plan.py [--dry-run]

数据来源:
  upgrade\\state\\   网页数据库的导出（main 每次同步数据后更新）
  daily\\ledger.json  这份导出之后，每天实际刷了多少（从 OneDragon 的 run_times 读回）
规则:
  - 排期算法和网页一致：核心技 > 突破 > 代理人经验 > 技能 > 音擎 > 丁尼，按每天可用电量装满为止。
  - 恶名狩猎不排（每周 3 次免费由"恶名狩猎"应用自己打）。
  - 写入前备份原文件到 daily\\backups\\。只替换 plan_list，其余设置保留；loop 设为 false，避免刷完清单后从头重复。
"""
import argparse, datetime as dt, json, math, os, shutil, sys, uuid

__version__ = "0.3.0"  # auto-zzz 版本，见仓库根目录 VERSION
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "upgrade"))
from allocate import (SKILLS, SKILL_LV, CORE_ST, LV_BANDS, PROMO, W_BANDS, W_PROMO, EXP_A, EXP_W,  # noqa: E402
                      seal, chip, comp, exp_between, load)

ONEDRAGON_DIR = os.environ.get("ONEDRAGON_DIR", r"C:\ZZZ-OneDragon")  # OneDragon 安装目录
ONEDRAGON_INSTANCE = os.environ.get("ONEDRAGON_INSTANCE", "01")  # 账号实例编号
CHARGE = os.path.join(ONEDRAGON_DIR, "config", ONEDRAGON_INSTANCE, "one_dragon", "charge_plan.yml")
STATE = os.path.join(ROOT, "upgrade", "state")
LEDGER = os.path.join(HERE, "ledger.json")
CONFIG = os.path.join(HERE, "config.json")
EST = {"expA": 12500, "expW": 15800, "den": 21000, "A_per_card": 1.0, "B_per_card": 1.5, "hdd": 5}
CHIP_STAGE = {"物理": "刚性测试", "引燃": "升温测试", "冰结": "冰结测试", "电击": "电流测试", "风蚀": "风切测试", "以太": "共鸣测试", "流明": "琢光测试"}
ENGINE_STAGE = {"锋御": "锋御耦合试验", "命破": "命破共鸣试验", "强攻": "强攻极片试验", "击破": "击破振膜试验",
                "异常": "异常磁体试验", "支援": "支援分频试验", "防护": "防护音圈试验"}
EC_NAME = {"阿瓦鲁斯": "秽息蚀者·阿瓦鲁斯", "秽蚀·多佩冈亚·狛野真斗": "秽蚀·狛野真斗"}
PRIO = {"core": 1, "seal": 2, "expA": 3, "chip": 4, "expW": 5, "comp": 6, "den": 7}


def ceq(o): return o["C"] + 3 * o["B"] + 9 * o["A"]


def read_json(p, default):
    try: return json.load(open(p, encoding="utf-8-sig"))
    except FileNotFoundError: return default


def state_stamp():
    # 只看背包：ledger 记的是"上次读背包之后刷到的东西"。每晚 HoYoLAB 同步只改等级，不该清掉这些记录。
    return os.path.getmtime(os.path.join(STATE, "plan", "inventory.json"))


def apply_ledger(own, ledger):
    """Add the estimated drops of runs finished since the state export."""
    for e in ledger.get("done", []):
        k, n, key = e["kind"], e["cards"], e.get("key")
        if k == "expA": own["资深调查员记录"] = own.get("资深调查员记录", 0) + n * EST["expA"] / 3000
        elif k == "expW": own["音擎能源模块"] = own.get("音擎能源模块", 0) + n * EST["expW"] / 3000
        elif k == "den": own["丁尼"] = own.get("丁尼", 0) + n * EST["den"]
        elif k in ("seal", "chip", "comp"):
            f = {"seal": seal, "chip": chip, "comp": comp}[k]
            own[f(key, "A")] = own.get(f(key, "A"), 0) + n * EST["A_per_card"]
            own[f(key, "B")] = own.get(f(key, "B"), 0) + n * EST["B_per_card"]
        elif k == "core": own[key] = own.get(key, 0) + n * EST["hdd"]


SET_AREA = {"怪兽与怪客": ["摇摆爵士", "混沌重金属"], "恶拳与凶枪": ["激素朋克", "獠牙重金属"], "猎人与忠犬": ["震星迪斯科", "雷暴重金属"],
            "高塔与巨炮": ["啄木鸟电音", "灵魂摇滚"], "疯子与追随者": ["河豚电音", "炎狱重金属"], "锐牙与钝斧": ["自由蓝调", "极地重金属"],
            "猎手与凶兽": ["混沌爵士", "原始朋克"], "怪兽二重奏": ["折枝剑歌", "静听嘉音"], "游侠与守卫": ["如影相随", "法厄同之歌"],
            "口舌与刀兵": ["云岿如我", "山大王"], "铁律与狂徒": ["拂晓生花", "月光骑士颂"], "诡步与重壁": ["沧浪行歌", "流光咏叹"],
            "伏龙与战车": ["雪兔梦游仙境", "囚徒手记"], "机师与叛甲": ["呼啸沙龙", "拂晓行纪"], "迅脊与裂爪": ["谶羽之誓", "荆棘玫瑰"]}


def area_of(s): return next((k for k, v in SET_AREA.items() if s in v), None)


def gaps(cur_all, tgt_all, on, metas, own, only=None):
    need = {"expA": 0, "expW": 0, "den": 0, "seal": {}, "chip": {}, "comp": {}, "hdd": {}}
    def add(d, k, t, n): d.setdefault(k, {"C": 0, "B": 0, "A": 0})[t] += n
    for aid, m in metas.items():
        if not on.get(aid) or aid not in cur_all or aid not in tgt_all: continue
        if only is not None and aid not in only: continue
        c, g = cur_all[aid], tgt_all[aid]
        lv0, lv1 = c["lv"], max(c["lv"], g["lv"])
        need["expA"] += exp_between(LV_BANDS, lv0, lv1)
        for at, (t, n, d) in PROMO.items():
            if lv0 <= at < lv1: add(need["seal"], m["sp"], t, n); need["den"] += d
        for i in range(5):
            for lv in range(c["sk"][i] + 1, max(c["sk"][i], g["sk"][i]) + 1):
                t, n, d = SKILL_LV[lv]; add(need["chip"], m["chip"], t, n); need["den"] += d
        for s in range(c["core"] + 1, max(c["core"], g["core"]) + 1):
            h, _, d, _ = CORE_ST[s]; need["hdd"][m["hdd"]] = need["hdd"].get(m["hdd"], 0) + h; need["den"] += d
        wr = c.get("wr", "-")
        if wr and wr != "-":
            wl0, wl1 = c["wl"], max(c["wl"], g["wl"])
            need["expW"] += exp_between(W_BANDS[wr], wl0, wl1)
            for at, (t, n, d) in W_PROMO[wr].items():
                if wl0 <= at < wl1: add(need["comp"], m["sp"], t, n); need["den"] += d
    rows = []
    have = lambda tbl: sum(own.get(n, 0) * v for n, v in tbl.items())
    s = need["expA"] - have(EXP_A)
    if s > 0: rows.append(dict(kind="expA", cat="实战模拟室", typ="基础材料", mis="调查专项", cost=20, n=math.ceil(s / EST["expA"]), why="代理人经验"))
    s = need["expW"] - have(EXP_W)
    if s > 0: rows.append(dict(kind="expW", cat="实战模拟室", typ="基础材料", mis="音擎专项", cost=20, n=math.ceil(s / EST["expW"]), why="音擎经验"))
    for kind, f, typ, stage in (("seal", seal, "代理人晋升", lambda k: k + "演练"),
                                ("chip", chip, "代理人技能", lambda k: CHIP_STAGE.get(k)),
                                ("comp", comp, "音擎改装", lambda k: ENGINE_STAGE.get(k))):
        for k, nd in need[kind].items():
            h = {t: own.get(f(k, t), 0) for t in "CBA"}
            short = ceq(nd) - ceq(h)
            if short > 0 and stage(k):
                rows.append(dict(kind=kind, key=k, cat="实战模拟室", typ=typ, mis=stage(k), cost=20,
                                 n=math.ceil(short / (9 * EST["A_per_card"] + 3 * EST["B_per_card"])), why=f"{typ}：{k}"))
    boss = {m["hdd"]: EC_NAME.get(m.get("ecBoss"), m.get("ecBoss")) for m in metas.values() if m.get("hdd")}
    for name, n in need["hdd"].items():
        s = n - own.get(name, 0)
        if s > 0 and boss.get(name):
            rows.append(dict(kind="core", key=name, cat="专业挑战室", typ=boss[name], mis=None, cost=40, n=math.ceil(s / EST["hdd"]), why="核心技：" + name))
    s = need["den"] - own.get("丁尼", 0)
    if s > 0: rows.append(dict(kind="den", cat="实战模拟室", typ="基础材料", mis="赏金专项", cost=20, n=math.ceil(s / EST["den"]), why="丁尼"))
    rows.sort(key=lambda r: PRIO[r["kind"]])  # stable: ★ rows are put in front by the caller afterwards
    return rows


def day_one(rows, budget):
    picked = []
    for r in rows:
        if budget < r["cost"]: continue
        n = min(r["n"], budget // r["cost"])
        if n: picked.append({**r, "n": n}); budget -= n * r["cost"]
    return picked, budget


def to_plan_items(picked, team_idx, tags):
    """OneDragon builds ChargePlanItem(**item), so items carry only its own fields; our tags go to the ledger by plan_id."""
    items = []
    def item(r, plan_times, card):
        pid = str(uuid.uuid4())
        tags[pid] = {"kind": r["kind"], "key": r.get("key"), "cards_per_run": 1 if r["cost"] != 20 else int(card)}
        return {"tab_name": "训练", "category_name": r["cat"], "mission_type_name": r["typ"], "mission_name": r["mis"],
                "level": "默认等级", "auto_battle_config": "全配队通用", "run_times": 0, "plan_times": plan_times,
                "card_num": card, "predefined_team_idx": team_idx, "notorious_hunt_buff_num": 1, "plan_id": pid}
    for r in picked:
        if r["cost"] != 20:  # 专业挑战室 / 区域巡防：一次一场
            items.append(item(r, r["n"], "默认数量"))
        else:  # 实战模拟室：一次最多 5 张卡
            full, rest = divmod(r["n"], 5)
            if full: items.append(item(r, full, "5"))
            if rest: items.append(item(r, 1, str(rest)))
    return items


QUEUE = os.path.join(HERE, "queue.json")
FARM_QUEUE = os.path.join(ROOT, "upgrade", "farm_queue.json")
SEAL_A = {"先行者": "强攻", "破阵者": "击破", "掌控者": "异常", "统御者": "支援", "捍卫者": "防护", "裁决者": "命破", "执锋者": "锋御"}


def queue_rows(queue, own, metas):
    """Turn queued materials (written by upgrade.py when a step lacks materials) into farming rows.
    Returns (rows, notes, remaining_items)."""
    import re
    rows, notes, keep, ceq_need = [], [], [], {}
    boss = {m["hdd"]: EC_NAME.get(m.get("ecBoss"), m.get("ecBoss")) for m in metas.values() if m.get("hdd")}
    tierv = {"C": 1, "B": 3, "A": 9}
    for it in queue.get("items", []):
        name, need = it.get("item", ""), float(it.get("need") or 0)
        if own.get(name, 0) >= need: continue  # covered now: drop from the queue
        keep.append(it)
        m = re.fullmatch(r"(基础|进阶|特化)(.+)芯片", name)
        if m and CHIP_STAGE.get(m.group(2)):
            t = {"基础": "C", "进阶": "B", "特化": "A"}[m.group(1)]
            k = ("实战模拟室", "代理人技能", CHIP_STAGE[m.group(2)], "chip", m.group(2))
            ceq_need[k] = ceq_need.get(k, 0) + (need - own.get(name, 0)) * tierv[t]; continue
        m = re.fullmatch(r"(初阶|高阶)(.+)认证章", name) or re.fullmatch(r"(先行者|破阵者|掌控者|统御者|捍卫者|裁决者|执锋者)认证章", name)
        if m:
            sp = m.group(2) if m.lastindex == 2 else SEAL_A[m.group(1)]
            t = {"初阶": "C", "高阶": "B"}.get(m.group(1), "A")
            k = ("实战模拟室", "代理人晋升", sp + "演练", "seal", sp)
            ceq_need[k] = ceq_need.get(k, 0) + (need - own.get(name, 0)) * tierv[t]; continue
        m = re.fullmatch(r"(增强型|特化型)?(.+)组件", name)
        if m and ENGINE_STAGE.get(m.group(2)):
            t = {"增强型": "B", "特化型": "A"}.get(m.group(1) or "", "C")
            k = ("实战模拟室", "音擎改装", ENGINE_STAGE[m.group(2)], "comp", m.group(2))
            ceq_need[k] = ceq_need.get(k, 0) + (need - own.get(name, 0)) * tierv[t]; continue
        short = need - own.get(name, 0)
        if name in boss:
            rows.append(dict(kind="core", key=name, cat="专业挑战室", typ=boss[name], mis=None, cost=40, n=math.ceil(short / EST["hdd"]), why=f"队列：{it.get('for', '')} 缺 {name}"))
        elif name == "丁尼":
            rows.append(dict(kind="den", cat="实战模拟室", typ="基础材料", mis="赏金专项", cost=20, n=math.ceil(short / EST["den"]), why=f"队列：{it.get('for', '')} 缺丁尼"))
        elif name in EXP_A:
            rows.append(dict(kind="expA", cat="实战模拟室", typ="基础材料", mis="调查专项", cost=20, n=math.ceil(short * EXP_A[name] / EST["expA"]), why=f"队列：{it.get('for', '')} 缺经验"))
        elif name in EXP_W:
            rows.append(dict(kind="expW", cat="实战模拟室", typ="基础材料", mis="音擎专项", cost=20, n=math.ceil(short * EXP_W[name] / EST["expW"]), why=f"队列：{it.get('for', '')} 缺音擎经验"))
        else:
            notes.append(f"{name} 还缺 {short:g}（{it.get('for', '')}），不能用电量刷：恶名狩猎每周免费 / 丽都城募 / 活动")
    per_card = 9 * EST["A_per_card"] + 3 * EST["B_per_card"]
    for (cat, typ, mis, kind, key), c in ceq_need.items():
        rows.append(dict(kind=kind, key=key, cat=cat, typ=typ, mis=mis, cost=20, n=math.ceil(c / per_card), why=f"队列：{typ} {key}"))
    return rows, notes, keep


def collect_done(yml, tags):
    """Read back how many cards/runs of our own plan items OneDragon finished."""
    done = []
    for p in (yml or {}).get("plan_list") or []:
        tag = tags.get(p.get("plan_id"))
        if tag and p.get("run_times"):
            done.append({"kind": tag["kind"], "key": tag.get("key"), "cards": p["run_times"] * tag.get("cards_per_run", 1),
                         "stage": f'{p["category_name"]}/{p["mission_type_name"]}/{p.get("mission_name")}'})
    return done


def main():
    import yaml
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--version", action="version", version=f"auto-zzz %(prog)s {__version__}")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = read_json(CONFIG, {"per_day": 240, "enabled": True})
    if not cfg.get("enabled", True): print("daily push disabled in config.json"); return
    yml = yaml.safe_load(open(CHARGE, encoding="utf-8")) or {}
    ledger = read_json(LEDGER, {})
    stamp = state_stamp()
    if ledger.get("state_stamp") != stamp:  # new export from main: start a fresh ledger
        ledger = {"state_stamp": stamp, "done": []}
    if ledger.get("pushed_on") and ledger.get("pushed_on") != dt.date.today().isoformat():
        ledger["done"] += collect_done(yml, ledger.get("tags", {}))  # yesterday's results, only for items we wrote
    cur = load(os.path.join(STATE, "plan", "current.json"))["cur"]
    tg = load(os.path.join(STATE, "plan", "targets.json"))
    own = dict(load(os.path.join(STATE, "plan", "inventory.json"))["own"])
    metas = {m["id"]: m for m in load(os.path.join(STATE, "meta", "agents.json"))["list"]}
    apply_ledger(own, ledger)
    rows = gaps(cur, tg["tgt"], tg.get("on", {}), metas, own)
    # ★ 优先培养：它自己的缺口排最前，再加每天固定次数的驱动盘（区域巡防）
    fp = os.path.join(STATE, "plan", "focus.json")
    focus = load(fp) if os.path.exists(fp) else {}
    stars = [s for s in focus.get("starred", []) if tg.get("on", {}).get(s) and s in metas]
    if stars:
        names = "、".join(metas[s]["name"] for s in stars)
        srows = gaps(cur, tg["tgt"], tg.get("on", {}), metas, own, only=set(stars))
        key = lambda r: (r["cat"], r["typ"], r["mis"])
        sn = {key(r): r["n"] for r in srows}
        rows = [dict(r, n=r["n"] - sn.get(key(r), 0)) for r in rows]
        rows = [r for r in rows if r["n"] > 0]
        disc = []
        for s in stars:
            ds = metas[s].get("discSets") or {}
            area = area_of(ds.get("four", ""))
            runs = int(focus.get("disc_runs", 2) or 0)
            if area and runs > 0:
                disc.append(dict(kind="disc", key=ds["four"], cat="区域巡防", typ=area, mis=None, cost=60, n=runs,
                                 why=f"★{metas[s]['name']}：驱动盘 {ds['four']}"))
        rows = [dict(r, why=f"★{names}：{r['why']}") for r in srows] + disc + rows
    # 刷取队列：已确认的升级卡在材料上，排在最前面
    queue = read_json(QUEUE, {"items": []})
    # upgrade.py 写的队列（fork 的格式：material / need / for_step），只读不改
    fq = read_json(FARM_QUEUE, {"items": []})
    extra = [{"item": x.get("material"), "need": x.get("need"), "for": f'{x.get("name_cn", "")} {x.get("for_step", "")}'.strip()}
             for x in fq.get("items", []) if x.get("material")]
    qrows, qnotes, qkeep = queue_rows({"items": queue.get("items", []) + extra}, own, metas)
    qkeep = [x for x in qkeep if x not in extra]  # only queue.json is rewritten here
    if qrows:
        key = lambda r: (r["cat"], r["typ"], r["mis"])
        qn = {}
        for r in qrows: qn[key(r)] = qn.get(key(r), 0) + r["n"]
        rows = [dict(r, n=r["n"] - qn.get(key(r), 0)) if r["kind"] != "disc" else r for r in rows]
        rows = qrows + [r for r in rows if r["n"] > 0]
    for nline in qnotes: print("  提示：" + nline)
    picked, left = day_one(rows, int(cfg.get("per_day", 240)))
    old = yml.get("plan_list") or []
    team = next((p.get("predefined_team_idx") for p in old if p.get("predefined_team_idx") is not None), 3)
    tags = {}
    items = to_plan_items(picked, team, tags)
    print(f"今日排期（每天 {cfg.get('per_day', 240)} 电量，剩 {left}）：")
    for r in picked: print(f"  {r['cat']} > {r['typ']}{' > ' + r['mis'] if r['mis'] else ''}  x{r['n']}{'次' if r['cost'] != 20 else '张卡'}  （{r['why']}）")
    if not items: print("  没有缺口，不改体力计划。"); return
    new = dict(yml); new["plan_list"] = items; new["loop"] = False
    if a.dry_run:
        out = os.path.join(HERE, "preview_charge_plan.yml")
        yaml.safe_dump(new, open(out, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
        print("演练：没有改 OneDragon 配置，预览写到", out); return
    os.makedirs(os.path.join(HERE, "backups"), exist_ok=True)
    shutil.copy2(CHARGE, os.path.join(HERE, "backups", f"charge_plan_{dt.datetime.now():%Y%m%d_%H%M%S}.yml"))
    yaml.safe_dump(new, open(CHARGE, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
    ledger["pushed_on"] = dt.date.today().isoformat(); ledger["last_push"] = [dict(r) for r in picked]; ledger["tags"] = tags
    json.dump(ledger, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if len(qkeep) != len(queue.get("items", [])):  # drop queue entries the bag now covers
        json.dump({"items": qkeep}, open(QUEUE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写入", CHARGE)


if __name__ == "__main__":
    main()
