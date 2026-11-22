"""每晚 23:00：从 HoYoLAB 战绩接口读账号，更新本地规划数据，并把数据（不含 UID）推到 GitHub Pages。

用法（Windows 计划任务每天 23:00 运行）:
  python hoyolab_sync.py            # 同步并推送到 GitHub
  python hoyolab_sync.py --no-push  # 只更新本地，不推 GitHub
  python hoyolab_sync.py --dry-run  # 只读接口、打印结果，不写任何文件

读到的: 代理人（等级、影画、5 个技能、核心技、音擎）、已装备的驱动盘、电量。
读不到的: 背包材料、丁尼、储蓄电量 —— 背包数量保持上次截图读到的值。

登录凭证在同目录 hoyolab_config.json（ltoken_v2 / ltuid_v2，从浏览器 Cookie 复制）。只用 GET 读数据。
"""
from __future__ import annotations

import argparse, datetime as dt, json, os, subprocess, sys, time, urllib.request

__version__ = "0.3.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "upgrade", "state")
CONFIG = os.path.join(HERE, "hoyolab_config.json")
RAW_DIR = os.path.join(HERE, "hoyolab_raw")          # 原始返回，只留在本机
LOG = os.path.join(HERE, "hoyolab_sync.log")
API = "https://sg-public-api.hoyolab.com/event/game_record_zzz/api/zzz/"
SKILL_IDX = {0: 0, 2: 1, 6: 2, 1: 3, 3: 4}           # skill_type -> 普攻/闪避/支援/特殊技/连携技
CORE_TYPE = 5                                         # 核心技：接口等级 1-7，7 = F
DISC_CAP = {"S": 15, "A": 12, "B": 9}
DEFAULT_TARGET_SK = [10, 8, 8, 10, 10]
PUBLISH = [("plan", "current.json"), ("plan", "targets.json"), ("plan", "inventory.json"), ("plan", "focus.json"),
           ("meta", "agents.json"), ("", "discs.json"), ("", "status.json")]


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
    except OSError: pass


def rj(p, default=None):
    try: return json.load(open(p, encoding="utf-8-sig"))
    except FileNotFoundError: return default


def wj(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


class Hoyolab:
    def __init__(self, cfg: dict) -> None:
        self.q = f"server={cfg['server']}&role_id={cfg['role_id']}"
        self.headers = {
            "Cookie": f"ltoken_v2={cfg['ltoken_v2']}; ltuid_v2={cfg['ltuid_v2']}",
            "x-rpc-lang": "zh-cn", "Accept": "application/json",
            "Origin": "https://act.hoyolab.com", "Referer": "https://act.hoyolab.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        }

    def get(self, path: str) -> dict:
        req = urllib.request.Request(API + path, headers=self.headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("retcode") != 0:
            raise RuntimeError(f"{path.split('?')[0]} 返回 {d.get('retcode')}：{d.get('message')}")
        return d["data"]

    def fetch_all(self) -> dict:
        basic = self.get("avatar/basic?" + self.q)
        infos = []
        for a in basic.get("avatar_list", []):
            time.sleep(0.4)  # 一次只能查一个 id；放慢一点，别给接口压力
            infos += self.get(f"avatar/info?id_list[]={a['id']}&need_wiki=false&{self.q}").get("avatar_list", [])
        note = self.get("note?" + self.q)
        return {"basic": basic, "infos": infos, "note": note}


def num(v):
    try: return int(str(v).strip())
    except (TypeError, ValueError): return v


def convert(raw: dict, id_map: dict[int, str]) -> dict:
    """HoYoLAB -> 规划用的格式（和网页数据库一致）。"""
    agents = {}
    for a in raw["infos"]:
        hid = a["id"]
        aid = id_map.get(hid, f"agent_{hid}")
        m = num(a.get("rank", 0)) or 0
        bonus = (2 if m >= 3 else 0) + (2 if m >= 5 else 0)
        sk, core = [1] * 5, 0
        for s in a.get("skills", []):
            t, lv = s.get("skill_type"), num(s.get("level", 1)) or 1
            if t in SKILL_IDX: sk[SKILL_IDX[t]] = max(1, lv - bonus)
            elif t == CORE_TYPE: core = max(0, min(6, lv - 1))
        w = a.get("weapon") or {}
        discs = []
        for e in a.get("equip") or []:
            rar = e.get("rarity") or ""
            main = (e.get("main_properties") or [{}])[0]
            discs.append({
                "slot": num(e.get("equipment_type")), "set": (e.get("equip_suit") or {}).get("name"),
                "rarity": rar, "level": num(e.get("level")), "level_cap": DISC_CAP.get(rar),
                "main_stat": {"stat": main.get("property_name"), "value": main.get("base")},
                "sub_stats": [{"stat": p.get("property_name"), "value": p.get("base"),
                               "upgrades": max(0, (num(p.get("level", 1)) or 1) - 1) if isinstance(num(p.get("level", 1)), int) else 0}
                              for p in e.get("properties") or []],
            })
        agents[aid] = {
            "hid": hid, "name": a.get("name_mi18n") or a.get("full_name_mi18n") or aid,
            "rarity": a.get("rarity"), "m": m,
            "cur": {"lv": num(a.get("level", 1)), "sk": sk, "core": core,
                    "wr": w.get("rarity") if w.get("name") else "-", "wl": num(w.get("level", 1)) or 1,
                    "wname": w.get("name"), "wrefine": num(w.get("star"))},
            "discs": sorted(discs, key=lambda x: x["slot"] if isinstance(x["slot"], int) else 9),
        }
    energy = (raw["note"].get("energy") or {}).get("progress") or {}
    return {"agents": agents, "battery": {"current": energy.get("current"), "max": energy.get("max")}}


def merge_into_state(conv: dict, synced_at: str) -> list[str]:
    cur_doc = rj(os.path.join(STATE, "plan", "current.json"), {"cur": {}})
    tgt_doc = rj(os.path.join(STATE, "plan", "targets.json"), {"tgt": {}, "on": {}})
    meta_doc = rj(os.path.join(STATE, "meta", "agents.json"), {"list": []})
    metas = {x["id"]: x for x in meta_doc["list"]}
    changes = []
    for aid, a in conv["agents"].items():
        old = cur_doc["cur"].get(aid)
        new = {**(old or {}), **a["cur"]}
        if old and any(old.get(k) != new.get(k) for k in ("lv", "sk", "core", "wl", "wr")):
            changes.append(f"{a['name']}：" + "，".join(f"{k} {old.get(k)}→{new.get(k)}" for k in ("lv", "sk", "core", "wl") if old.get(k) != new.get(k)))
        elif not old:
            changes.append(f"新代理人 {a['name']}")
        cur_doc["cur"][aid] = new
        if aid in metas: metas[aid].update(rarity=a["rarity"] or metas[aid].get("rarity"), m=a["m"], hid=a["hid"])
        else: metas[aid] = {"id": aid, "name": a["name"], "rarity": a["rarity"], "m": a["m"], "hid": a["hid"]}
        if aid not in tgt_doc["tgt"]:
            tgt_doc["tgt"][aid] = {"lv": 60, "sk": [max(s, t) for s, t in zip(a["cur"]["sk"], DEFAULT_TARGET_SK)], "core": 6, "wl": 60}
            tgt_doc.setdefault("on", {})[aid] = False
    cur_doc.update(source="hoyolab", snapAt=synced_at[:16].replace("T", " "), updated_at=synced_at)
    meta_doc["list"] = list(metas.values()); meta_doc["updated_at"] = synced_at
    wj(os.path.join(STATE, "plan", "current.json"), cur_doc)
    wj(os.path.join(STATE, "plan", "targets.json"), tgt_doc)
    wj(os.path.join(STATE, "meta", "agents.json"), meta_doc)
    wj(os.path.join(STATE, "discs.json"), {"agents": {k: v["discs"] for k, v in conv["agents"].items() if v["discs"]}, "taken_at": synced_at})
    wj(os.path.join(STATE, "status.json"), {"battery": conv["battery"], "synced_at": synced_at, "source": "HoYoLAB 战绩接口",
                                            "agents": len(conv["agents"]), "changes": changes})
    return changes


def publish(cfg: dict, synced_at: str) -> None:
    repo = cfg.get("repo_dir") or ROOT  # 默认：脚本所在的 auto-zzz 仓库
    if not os.path.isdir(os.path.join(repo, ".git")):
        log("找不到 auto-zzz 仓库，跳过 GitHub 推送"); return
    out = os.path.join(repo, "docs", "data")
    uid = str(cfg.get("role_id") or "")
    for sub, f in PUBLISH:
        src = os.path.join(STATE, sub, f)
        if not os.path.exists(src): continue
        text = open(src, encoding="utf-8-sig").read()
        if uid and uid in text:
            raise RuntimeError(f"{f} 里出现了 UID，停止推送")
        name = f"{sub}_{f}" if sub else f
        open(os.path.join(out, name), "w", encoding="utf-8").write(text)
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, encoding="utf-8")
    git("add", "docs/data")
    if not git("diff", "--cached", "--quiet").returncode:
        log("账号数据没有变化，不用推送"); return
    r = git("commit", "-m", f"data: HoYoLAB sync {synced_at[:10]}")
    if r.returncode: raise RuntimeError("git commit 失败：" + r.stderr.strip())
    r = git("push", "-q", "origin", "HEAD")
    if r.returncode: raise RuntimeError("git push 失败：" + r.stderr.strip())
    log("已推送到 GitHub Pages")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--version", action="version", version=f"auto-zzz %(prog)s {__version__}")
    a = ap.parse_args()
    if sys.stdout: sys.stdout.reconfigure(encoding="utf-8")  # pythonw（计划任务不弹窗）时没有 stdout
    cfg = rj(CONFIG, {})
    if not cfg.get("ltoken_v2") or not cfg.get("ltuid_v2"):
        log(f"还没填登录凭证：请在 {CONFIG} 里填 ltoken_v2 和 ltuid_v2"); return 2
    synced_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        raw = Hoyolab(cfg).fetch_all()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "-100" in msg or "10001" in msg:
            msg += "（登录凭证失效：请重新从浏览器复制 ltoken_v2 / ltuid_v2）"
        log("读取 HoYoLAB 失败：" + msg); return 1
    if not a.dry_run:
        wj(os.path.join(RAW_DIR, f"{synced_at[:10]}.json"), raw)
    # HoYoLAB 数字编号 -> 规划用的 id：先看 meta 里存的 hid，再看第一次读取时的快照
    id_map = {}
    for p in (os.path.join(ROOT, "snapshots", "2026-11-21_1115.json"), os.path.join(ROOT, "data", "account", "snapshot_2026-11-21.json")):
        id_map.update({x["hoyolab_id"]: x["id"] for x in rj(p, {"agents": []}).get("agents", []) if x.get("hoyolab_id")})
    id_map.update({x["hid"]: x["id"] for x in rj(os.path.join(STATE, "meta", "agents.json"), {"list": []})["list"] if x.get("hid")})
    conv = convert(raw, id_map)
    log(f"读到 {len(conv['agents'])} 个代理人，电量 {conv['battery'].get('current')}/{conv['battery'].get('max')}")
    if a.dry_run:
        for aid, x in list(conv["agents"].items())[:5]:
            log(f"  {x['name']} Lv{x['cur']['lv']} 技能{x['cur']['sk']} 核心{x['cur']['core']} 音擎{x['cur']['wname']} Lv{x['cur']['wl']} 盘{len(x['discs'])}")
        return 0
    changes = merge_into_state(conv, synced_at)
    log("变化：" + ("；".join(changes) if changes else "无"))
    if cfg.get("push_to_github", True) and not a.no_push:
        try: publish(cfg, synced_at)
        except Exception as e:  # noqa: BLE001
            log("推送 GitHub 失败：" + str(e)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
