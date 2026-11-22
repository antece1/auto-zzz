"""ZZZ 自动升级脚本的公共部分：连接 OneDragon 后端、OCR 定位、先确认画面再点击、日志、截图。

只依赖标准库（头像匹配另需 opencv-python / numpy），用 OneDragon 的 .venv\\Scripts\\python.exe 或系统 Python 都能跑。
点击 / 按键走 OneDragon 后端的 MCP 工具（click_game / key_tap），读画面走 HTTP /game/analyze、/game/capture。
"""
from __future__ import annotations

import json
import os
import signal
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__version__ = "0.3.0"  # auto-zzz 版本，见仓库根目录 VERSION
BASE = os.environ.get('AUTOZZZ_BACKEND', 'http://127.0.0.1:23001')  # OneDragon 后端地址
ONEDRAGON_DIR = Path(os.environ.get('ONEDRAGON_DIR', r'C:\ZZZ-OneDragon'))  # OneDragon 安装目录
ONEDRAGON_LOG = ONEDRAGON_DIR / '.log' / 'log.txt'
_TRAD_TO_SIMP = str.maketrans('強確級與擊認證產備裝鍵選擇數據攻擊', '强确级与击认证产备装键选择数据攻击')
_MCP_HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}


class StopRun(Exception):
    """需要立刻停下的情况：画面不对、读数不对、用户按了停止。"""


@dataclass
class Text:
    text: str
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


class Game:
    def __init__(self, run_dir: Path, log_path: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_path
        self._sid: str | None = None
        self._rpc_id = 10
        self._shot_n = 0
        self.stop_requested = False
        signal.signal(signal.SIGINT, self._on_sigint)

    # ---------- 日志 ----------
    def log(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        with self.log_path.open('a', encoding='utf-8') as f:
            f.write(line + '\n')

    def _on_sigint(self, *_: object) -> None:
        self.stop_requested = True
        self.log('收到 Ctrl+C，当前步骤结束后停下')

    def check_stop(self) -> None:
        if self.stop_requested:
            raise StopRun('用户要求停止')

    # ---------- HTTP / MCP ----------
    def _get(self, path: str, timeout: int = 60) -> bytes:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.read()

    def _mcp(self, body: dict) -> dict | None:
        headers = dict(_MCP_HEADERS)
        if self._sid:
            headers['Mcp-Session-Id'] = self._sid
        req = urllib.request.Request(BASE + '/mcp', data=json.dumps(body).encode(), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=60) as r:
            self._sid = r.headers.get('Mcp-Session-Id') or self._sid
            raw = r.read().decode('utf-8', 'replace')
            ctype = r.headers.get('Content-Type', '')
        if not raw.strip():
            return None
        if 'event-stream' in ctype:
            msg = None
            for line in raw.splitlines():
                if line.startswith('data:'):
                    d = json.loads(line[5:].strip())
                    if 'id' in d:
                        msg = d
            return msg
        return json.loads(raw)

    def _ensure_session(self) -> None:
        if self._sid:
            return
        self._mcp({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'auto-zzz', 'version': __version__}}})
        self._mcp({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def _tool(self, name: str, args: dict) -> dict:
        self._ensure_session()
        self._rpc_id += 1
        res = self._mcp({'jsonrpc': '2.0', 'id': self._rpc_id, 'method': 'tools/call',
                         'params': {'name': name, 'arguments': args}})
        if res is None or 'error' in res:
            raise StopRun(f'MCP {name} 调用失败: {res}')
        r = res['result']
        if r.get('structuredContent') is not None:
            return r['structuredContent']
        return {'text': ' '.join(c.get('text', '') for c in r.get('content', []))}

    # ---------- 读画面 ----------
    def window(self) -> dict:
        return json.loads(self._get('/game/window'))

    def status(self) -> dict:
        return json.loads(self._get('/game/status'))

    def ocr(self) -> list[Text]:
        d = json.loads(self._get('/game/analyze'))
        # OCR 偶尔把简体认成繁体（实测「技能强化」→「技能強化」），统一成简体再比较
        return [Text(t['text'].translate(_TRAD_TO_SIMP), t['x'], t['y'], t['width'], t['height'])
                for t in d.get('ocr_texts', [])]

    def shot(self, label: str) -> Path:
        self._shot_n += 1
        p = self.run_dir / f'{self._shot_n:03d}_{label}.png'
        p.write_bytes(self._get('/game/capture'))
        return p

    @staticmethod
    def find(texts: list[Text], word: str, region: tuple[int, int, int, int] | None = None,
             exact: bool = False) -> Text | None:
        """按文字找控件。region = (x1, y1, x2, y2)，按控件中心点判断。"""
        for t in texts:
            hit = (t.text == word) if exact else (word in t.text)
            if not hit:
                continue
            if region and not (region[0] <= t.cx <= region[2] and region[1] <= t.cy <= region[3]):
                continue
            return t
        return None

    def expect(self, words: list[str], what: str, tries: int = 3, wait: float = 1.0) -> list[Text]:
        """确认当前画面包含全部 words，否则截图并停下。返回这次的 OCR 结果。"""
        texts: list[Text] = []
        for _ in range(tries):
            texts = self.ocr()
            if all(self.find(texts, w) for w in words):
                return texts
            time.sleep(wait)
        p = self.shot(f'unexpected_{what}')
        raise StopRun(f'画面不对（{what}）：缺少 {[w for w in words if not self.find(texts, w)]}，截图 {p.name}')

    # ---------- 操作（每次都先确认画面） ----------
    def click_text(self, word: str, what: str, region: tuple[int, int, int, int] | None = None,
                   wait: float = 1.5, exact: bool = False) -> None:
        self.check_stop()
        texts = self.ocr()
        t = self.find(texts, word, region, exact)
        if t is None:
            p = self.shot(f'missing_{what}')
            raise StopRun(f'找不到按钮「{word}」（{what}），截图 {p.name}')
        self.log(f'点击「{t.text}」@{t.cx},{t.cy}（{what}）')
        self._tool('click_game', {'x': t.cx, 'y': t.cy})
        time.sleep(wait)

    def click_xy(self, x: int, y: int, what: str, must_see: list[str], wait: float = 1.5) -> None:
        """固定坐标点击：只有当前画面包含 must_see 全部文字时才点。"""
        self.check_stop()
        self.expect(must_see, f'点击前确认:{what}')
        self.log(f'点击 @{x},{y}（{what}）')
        self._tool('click_game', {'x': x, 'y': y})
        time.sleep(wait)

    def key(self, k: str, what: str, wait: float = 1.5) -> None:
        self.check_stop()
        self.log(f'按键 {k}（{what}）')
        self._tool('key_tap', {'key': k})
        time.sleep(wait)

    # ---------- 开始前检查 ----------
    def precheck(self) -> None:
        try:
            health = json.loads(self._get('/health', timeout=5))
        except Exception as e:  # noqa: BLE001
            raise StopRun(f'OneDragon 后端没开（{BASE}）：{e}') from e
        if not health.get('ready'):
            raise StopRun('OneDragon 后端还没准备好')
        w = self.window()
        if not w.get('is_win_valid'):
            raise StopRun('找不到游戏窗口')
        if (w.get('width'), w.get('height')) != (1920, 1080):
            raise StopRun(f"游戏窗口是 {w.get('width')}×{w.get('height')}，请在游戏设置里改成 1920×1080 再运行")
        st = self.status()
        if st.get('state') == 'running':
            raise StopRun(f"后端有任务在跑：{st.get('app')}")
        if ONEDRAGON_LOG.exists() and time.time() - ONEDRAGON_LOG.stat().st_mtime < 30:
            # 只看最近 30 秒里的「指令[」行（应用在跑）；overlay 提示等不算
            with ONEDRAGON_LOG.open('rb') as f:
                f.seek(max(0, ONEDRAGON_LOG.stat().st_size - 8000))
                tail = f.read().decode('utf-8', 'replace').splitlines()
            now = time.localtime()
            for line in tail:
                if '指令[' not in line or not line.startswith('['):
                    continue
                try:
                    hh, mm, ss = line[1:9].split(':')
                    age = (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec) - (int(hh) * 3600 + int(mm) * 60 + int(ss))
                except ValueError:
                    continue
                if 0 <= age < 30:
                    raise StopRun(f'OneDragon 30 秒内有应用在跑：{line[:80]}')
        self.log(f"开始前检查通过：窗口 1920×1080，后端空闲")
