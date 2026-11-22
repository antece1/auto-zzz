"""
绝区零一条龙 antece版 启动器。

桌面快捷方式用 .venv\\Scripts\\pythonw.exe 运行本文件（不弹黑框）：
1. 在 main 分支、没有未提交的改动时，从 antece1/auto-zzz 拉取最新代码（只快进，不覆盖本地改动）。
2. 代码更新里 pyproject.toml / uv.lock 有变化时，用 uv 同步依赖。
3. 启动一条龙界面。

每一步写日志到 .log/antece_launcher.log；更新失败不影响启动，启动失败弹窗提示。
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
ANTECE_REPO: str = 'https://github.com/antece1/auto-zzz.git'
BRANCH: str = 'main'
LOG_PATH: Path = ROOT / '.log' / 'antece_launcher.log'
NO_WINDOW: int = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, creationflags=NO_WINDOW)


def update_code() -> bool:
    """
    从 antece1/auto-zzz 快进到最新代码
    :return: 依赖文件是否有变化
    """
    git = shutil.which('git')
    if git is None or not (ROOT / '.git').exists():
        log('找不到 git 或不是 git 仓库，跳过更新')
        return False
    branch = run([git, 'rev-parse', '--abbrev-ref', 'HEAD']).stdout.strip()
    if branch != BRANCH:
        log(f'当前在 {branch} 分支，不是 {BRANCH}，跳过更新')
        return False
    if run([git, 'status', '--porcelain', '--untracked-files=no']).stdout.strip():
        log('有未提交的改动，跳过更新')
        return False

    old = run([git, 'rev-parse', 'HEAD']).stdout.strip()
    fetch = run([git, 'fetch', ANTECE_REPO, BRANCH], timeout=30)
    if fetch.returncode != 0:
        log(f'拉取失败，用本地代码启动：{fetch.stderr.strip()[-300:]}')
        return False
    merge = run([git, 'merge', '--ff-only', 'FETCH_HEAD'])
    if merge.returncode != 0:
        log(f'无法快进（本地有远程没有的提交），用本地代码启动：{merge.stderr.strip()[-300:]}')
        return False
    new = run([git, 'rev-parse', 'HEAD']).stdout.strip()
    if new == old:
        log(f'已是最新 {new[:8]}')
        return False
    log(f'代码已更新 {old[:8]} -> {new[:8]}')
    changed = run([git, 'diff', '--name-only', old, new]).stdout.split()
    return any(name in ('pyproject.toml', 'uv.lock') for name in changed)


def find_uv() -> str | None:
    """uv 可能不在 pythonw 的 PATH 里，再看 winget 和官方安装脚本的默认位置"""
    candidates = [
        shutil.which('uv'),
        str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Links' / 'uv.exe'),
        str(Path.home() / '.local' / 'bin' / 'uv.exe'),
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def sync_deps() -> None:
    uv = find_uv()
    if uv is None:
        log('依赖有变化，但找不到 uv，请在项目目录手动运行 uv sync')
        return
    # --inexact：不卸载手动装的可选依赖（如虚拟手柄）
    result = run([uv, 'sync', '--frozen', '--inexact', '--python', sys.executable], timeout=900)
    log('依赖已同步' if result.returncode == 0 else f'依赖同步失败：{result.stderr.strip()[-500:]}')


def start_gui() -> None:
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    exe = str(pythonw if pythonw.exists() else sys.executable)
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    subprocess.Popen([exe, str(ROOT / 'src' / 'zzz_od' / 'gui' / 'app.py')], cwd=ROOT, env=env)
    log('已启动一条龙界面')


def main() -> None:
    log(f'---- 启动 antece版（{ROOT}）')
    try:
        if update_code():
            sync_deps()
    except Exception:
        log('更新出错，用本地代码启动：\n' + traceback.format_exc())
    try:
        start_gui()
    except Exception:
        log('启动失败：\n' + traceback.format_exc())
        ctypes.windll.user32.MessageBoxW(None, f'启动失败，详情见\n{LOG_PATH}', '绝区零一条龙 antece版', 0x10)


if __name__ == '__main__':
    main()
