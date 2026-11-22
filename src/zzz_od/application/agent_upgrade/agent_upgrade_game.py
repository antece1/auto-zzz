from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from one_dragon.base.geometry.point import Point
from one_dragon.utils import cv2_utils
from one_dragon.utils.log_utils import log

if TYPE_CHECKING:
    from cv2.typing import MatLike

    from zzz_od.context.zzz_context import ZContext

# OCR 偶尔把简体认成繁体（实测「技能强化」→「技能強化」），统一成简体再比较
_TRAD_TO_SIMP = str.maketrans('強確級與擊認證產備裝鍵選擇數據攻擊', '强确级与击认证产备装键选择数据攻击')


class StopRun(Exception):
    """需要立刻停下的情况：画面不对、读数不对、用户按了停止"""


@dataclass
class Text:
    """一条 OCR 结果，坐标是 1920×1080 游戏画面坐标"""

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


class UpgradeGame:
    """
    代理人升级用到的画面操作：截图、OCR 按文字定位、先确认画面再点击、关键步骤截图。
    所有点击前都先用 OCR 确认画面，对不上就抛 StopRun，不猜坐标连点。
    """

    def __init__(self, ctx: ZContext, run_dir: Path) -> None:
        self.ctx: ZContext = ctx
        self.run_dir: Path = run_dir
        self._shot_n: int = 0
        self.last_image: MatLike | None = None

    def check_stop(self) -> None:
        """用户在界面上点了停止（F10）时，当前操作结束后停下"""
        if self.ctx.run_context.is_context_stop:
            raise StopRun('用户要求停止')

    # ---------- 读画面 ----------
    def screenshot(self) -> MatLike:
        _, image = self.ctx.controller.screenshot()
        if image is None:
            raise StopRun('截图失败')
        self.last_image = image
        return image

    def ocr(self) -> list[Text]:
        image = self.screenshot()
        result_list = self.ctx.ocr_service.get_ocr_result_list(image=image, crop_first=False)
        return [Text(r.data.translate(_TRAD_TO_SIMP), int(r.x), int(r.y), int(r.w), int(r.h))
                for r in result_list]

    def shot(self, label: str) -> Path:
        """保存当前画面（已打码 UID），返回文件路径"""
        self._shot_n += 1
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / f'{self._shot_n:03d}_{label}.png'
        image = self.last_image if self.last_image is not None else self.screenshot()
        cv2_utils.save_image(image, str(path))
        return path

    @staticmethod
    def find(texts: list[Text], word: str, region: tuple[int, int, int, int] | None = None,
             exact: bool = False) -> Text | None:
        """按文字找控件。region = (x1, y1, x2, y2)，按控件中心点判断"""
        for t in texts:
            hit = (t.text == word) if exact else (word in t.text)
            if not hit:
                continue
            if region and not (region[0] <= t.cx <= region[2] and region[1] <= t.cy <= region[3]):
                continue
            return t
        return None

    def expect(self, words: list[str], what: str, tries: int = 3, wait: float = 1.0) -> list[Text]:
        """确认当前画面包含全部 words，否则截图并停下。返回这次的 OCR 结果"""
        texts: list[Text] = []
        for _ in range(tries):
            texts = self.ocr()
            if all(self.find(texts, w) for w in words):
                return texts
            time.sleep(wait)
        path = self.shot(f'unexpected_{what}')
        missing = [w for w in words if not self.find(texts, w)]
        raise StopRun(f'画面不对（{what}）：缺少 {missing}，截图 {path.name}')

    # ---------- 操作（每次都先确认画面） ----------
    def click_text(self, word: str, what: str, region: tuple[int, int, int, int] | None = None,
                   wait: float = 1.5, exact: bool = False) -> None:
        self.check_stop()
        texts = self.ocr()
        t = self.find(texts, word, region, exact)
        if t is None:
            path = self.shot(f'missing_{what}')
            raise StopRun(f'找不到按钮「{word}」（{what}），截图 {path.name}')
        log.info(f'点击「{t.text}」@{t.cx},{t.cy}（{what}）')
        self.ctx.controller.click(Point(t.cx, t.cy))
        time.sleep(wait)

    def click_xy(self, x: int, y: int, what: str, must_see: list[str], wait: float = 1.5) -> None:
        """固定坐标点击：只有当前画面包含 must_see 全部文字时才点"""
        self.check_stop()
        self.expect(must_see, f'点击前确认:{what}')
        log.info(f'点击 @{x},{y}（{what}）')
        self.ctx.controller.click(Point(x, y))
        time.sleep(wait)

    def key(self, key: str, what: str, wait: float = 1.5) -> None:
        self.check_stop()
        log.info(f'按键 {key}（{what}）')
        self.ctx.controller.btn_tap(key)
        time.sleep(wait)

    def precheck(self) -> None:
        """开始前检查：游戏窗口存在且是 1920×1080"""
        controller = self.ctx.controller
        if controller is None or not controller.is_game_window_ready:
            raise StopRun('找不到游戏窗口')
        rect = controller.game_win.win_rect
        if rect is None:
            raise StopRun('读不到游戏窗口大小')
        if (rect.width, rect.height) != (1920, 1080):
            raise StopRun(f'游戏窗口是 {rect.width}×{rect.height}，请在游戏设置里改成 1920×1080 再运行')
        log.info('开始前检查通过：游戏窗口 1920×1080')
