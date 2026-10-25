"""CleanBlackboard - 简黑板 · 桌面外壳。

用 pywebview 把 ui/index.html 装进一个原生窗口（Windows 上走 WebView2）。
所有文件读写都通过 js_api 暴露给页面，页面自己不碰磁盘。
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "简黑板"                       # 中文名
APP_EN = "Clean Blackboard"              # 完整英文名
APP_SLUG = "CleanBlackboard"             # 英文简写：exe 文件名、标题栏前缀
APP_TITLE = f"{APP_SLUG} - {APP_NAME}"   # 标题栏：CleanBlackboard - 简黑板
APP_ID = "CleanBlackboard"
LEGACY_APP_ID = "WhiteboardDesktop"
VERSION = "1.1.0"

# ---------- 更新检查 ----------
REPO = "Liuyichen27/clean-blackboard"          # 本项目
INSTALLER_REPO = "Liuyichen27/SwiftGet"        # 自研下载器（当作备用安装器）
EXE_ASSET = f"{APP_SLUG}.exe"
INSTALLER_ASSET = "SwiftGet.exe"
PROXY = "https://gh-proxy.com/"                # github 直连不稳时的镜像
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
INBOX = "inbox"                                # 下载目录里的子文件夹名

PROJECT_EXT = ".wbjson"
# pywebview 的 file_types 要求「字符串元组」，格式是 "说明 (*.ext;*.ext2)"。
# 早先写成 [("说明", "*.ext")] 这种列表套元组，每次保存都会抛
# TypeError: expected string or bytes-like object, got 'tuple' —— 直接导致存不了文件。
PROJECT_FILTERS = (
    f"简黑板工程 (*{PROJECT_EXT})",
    "JSON 文件 (*.json)",
    "所有文件 (*.*)",
)
PNG_FILTERS = ("PNG 图片 (*.png)",)
PNG_PREFIX = "data:image/png;base64,"


def resource_root() -> Path:
    """打包成 exe 后资源在临时解包目录里，源码运行时在项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    """用户数据目录：%APPDATA%\\CleanBlackboard。"""
    base = Path(os.environ.get("APPDATA") or str(Path.home()))
    d = base / APP_ID
    old = base / LEGACY_APP_ID
    # 改名前叫 WhiteboardDesktop，老用户的草稿一并搬过来
    if not d.exists() and old.exists():
        try:
            old.rename(d)
        except Exception:
            pass
    d.mkdir(parents=True, exist_ok=True)
    return d


def downloads_dir() -> Path:
    """优先落到「下载」文件夹，找不到就用应用数据目录，保证一定写得进去。"""
    for name in ("Downloads", "下载"):
        d = Path.home() / name
        if d.is_dir():
            return d
    d = app_dir() / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 两个 opener：直连（无视系统代理）和走环境变量里的代理。
# 用户机上的代理时开时关，直连失败再退回代理，两条路都试过才报错。
_OPEN_DIRECT = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(),
)
_OPEN_ENV = urllib.request.build_opener()


def _ua() -> str:
    return f"{APP_SLUG}/{VERSION} (+https://github.com/{REPO})"


def _open(url: str, timeout: float, direct: bool, accept: str = "*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": _ua(), "Accept": accept})
    return (_OPEN_DIRECT if direct else _OPEN_ENV).open(req, timeout=timeout)


def _get_json(url: str, timeout: float = 6.0) -> dict:
    last: Exception | None = None
    for direct in (True, False):
        try:
            with _open(url, timeout, direct, "application/vnd.github+json") as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def _get_bytes(url: str, timeout: float = 30.0, limit: int = 300 * 1024 * 1024) -> bytes:
    last: Exception | None = None
    for direct in (True, False):
        try:
            with _open(url, timeout, direct) as r:
                buf: list[bytes] = []
                got = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > limit:
                        raise ValueError("文件超过上限")
                    buf.append(chunk)
                return b"".join(buf)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def _ver_tuple(s: str) -> tuple[int, ...]:
    nums = []
    for part in str(s or "").lstrip("vV").split("."):
        m = re.match(r"\d+", part)
        nums.append(int(m.group()) if m else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def fetch_latest(tries: int = 3) -> dict | None:
    """查 GitHub 上最新 release。直连 + 镜像各试一遍，弱网下多轮重试。"""
    fake = os.environ.get("WB_FAKE_LATEST")
    if fake:  # 自测用：假装线上有个新版本
        return {
            "tag": fake if fake.startswith("v") else f"v{fake}",
            "version": fake.lstrip("vV"),
            "date": "2026-10-25",
            "assets": {EXE_ASSET: ""},
            "page": RELEASES_PAGE,
        }

    urls = [
        f"https://api.github.com/repos/{REPO}/releases/latest",
        f"{PROXY}https://api.github.com/repos/{REPO}/releases/latest",
    ]
    for attempt in range(tries):
        for url in urls:
            try:
                data = _get_json(url)
            except Exception:  # noqa: BLE001
                continue
            tag = str(data.get("tag_name") or "").strip()
            if not tag:
                continue
            assets = {
                a.get("name"): a.get("browser_download_url")
                for a in data.get("assets") or []
                if a.get("name")
            }
            return {
                "tag": tag,
                "version": tag.lstrip("vV"),
                "date": str(data.get("published_at") or "")[:10],
                "assets": assets,
                "page": data.get("html_url") or RELEASES_PAGE,
            }
        time.sleep(0.8 + attempt)
    return None


def check_update() -> dict:
    cur = VERSION
    info = fetch_latest()
    if not info:
        return {"ok": False, "error": "连不上 GitHub，稍后再试", "current": cur}
    has = _ver_tuple(info["version"]) > _ver_tuple(cur)
    return {
        "ok": True,
        "current": cur,
        "latest": info["version"],
        "date": info["date"],
        "has_update": has,
        "page": info["page"],
        "asset_url": info["assets"].get(EXE_ASSET) or "",
    }


def download_asset(urls: list[str], dest: Path, exe: bool = True,
                   on_progress=None) -> Path:
    """按顺序试下载源，边下边回报进度，落盘后校验文件头。

    校验这一步很要紧：网络不通时 github 会返回一个 200 的 HTML 错误页，
    不查文件头就会把它当成 exe 存下来，用户双击只会看到「不是有效的应用」。
    """
    last: Exception | None = None
    targets = [u for u in urls if u]
    # 先直连跑一轮（镜像/官方都在列表里），全挂了再借系统代理试一轮
    for direct in (True, False):
        for url in targets:
            try:
                last_tick = 0.0
                with _open(url, 30.0, direct) as r:
                    total = int(r.headers.get("Content-Length") or 0)
                    buf: list[bytes] = []
                    got = 0
                    head = b""
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        if not head:
                            head = chunk[:2]
                        got += len(chunk)
                        if got > 300 * 1024 * 1024:
                            raise ValueError("文件超过上限")
                        buf.append(chunk)
                        now = time.time()
                        if on_progress and (now - last_tick > 0.4 or (total and got >= total)):
                            last_tick = now
                            try:
                                on_progress(got, total)
                            except Exception:  # noqa: BLE001
                                pass
                blob = b"".join(buf)
                if not blob:
                    raise ValueError("空文件")
                if exe and not head.startswith(b"MZ"):
                    raise ValueError("下载到的不是可执行文件")
                dest.write_bytes(blob)
                return dest
            except Exception as e:  # noqa: BLE001
                last = e
    raise last or RuntimeError("没有可用的下载地址")


class Api:
    """暴露给页面 JS 的原生能力。

    ⚠️ 这里**绝对不能**放公开的属性（尤其是 window）。
    pywebview 启动时会把本对象"翻译"成 JS 接口，做法是递归遍历所有公开成员
    （webview/util.py 的 get_functions）且没有环检测。一旦挂上 Window，
    就会顺着它走进 pythonnet 的整个 .NET 对象图，永远遍历不完 ——
    主线程卡在 create_window 里，窗口被 Windows 判为「未响应」。
    所有对 window 的引用一律用下划线开头（会被跳过），并靠 __dir__ 再兜一层。
    """

    def __init__(self) -> None:
        self._window = None

    def __dir__(self):
        # 只把公开方法暴露出去，属性一个都不给
        return [n for n in super().__dir__()
                if not n.startswith('_') and callable(getattr(self, n, None))]

    # ---------- 工程文件 ----------

    def save_project(self, content: str, suggested: str = "") -> dict:
        """弹出保存对话框，把 JSON 写进文件。"""
        try:
            path = self._ask_save_path(
                suggested or f"{APP_SLUG}-{self._stamp()}{PROJECT_EXT}",
                PROJECT_FILTERS,
            )
            if not path:
                return {"ok": False, "cancel": True}

            data = json.loads(content)  # 先校验，别把半截文件写进磁盘
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def open_project(self) -> dict:
        """弹出打开对话框，把文件内容读出来交给页面。"""
        try:
            path = self._ask_open_path(PROJECT_FILTERS)
            if not path:
                return {"ok": False, "cancel": True}

            text = Path(path).read_text(encoding="utf-8")
            json.loads(text)  # 无效 JSON 直接在这里报错
            return {"ok": True, "path": path, "content": text}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- 图片 ----------

    def save_png(self, data_url: str, suggested: str = "") -> dict:
        """把页面传来的 dataURL 写成 PNG。"""
        try:
            if not data_url.startswith(PNG_PREFIX):
                return {"ok": False, "error": "图片数据格式不对"}

            path = self._ask_save_path(
                suggested or f"{APP_SLUG}-{self._stamp()}.png",
                PNG_FILTERS,
            )
            if not path:
                return {"ok": False, "cancel": True}

            blob = base64.b64decode(data_url[len(PNG_PREFIX):])
            Path(path).write_bytes(blob)
            return {"ok": True, "path": path, "bytes": len(blob)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- 杂项 ----------

    def app_info(self) -> dict:
        return {
            "name": APP_NAME,
            "version": VERSION,
            "data_dir": str(app_dir()),
            "platform": sys.platform,
        }

    # ---------- 更新 ----------

    def open_url(self, url: str) -> dict:
        """只放行 http/https，别让页面拿 file:// 去开本地东西。"""
        if not re.match(r"^https?://", str(url or "")):
            return {"ok": False, "error": "只允许 http/https 链接"}
        try:
            webbrowser.open(str(url))
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def check_update(self) -> dict:
        try:
            return check_update()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "current": VERSION, "error": f"{type(e).__name__}: {e}"}

    def _progress_cb(self):
        """下载进度回传给页面：每 0.4 秒最多一次，UI 卡住也不影响下载。"""
        def report(got: int, total: int) -> None:
            if self._window is None:
                return
            payload = json.dumps({
                "got": got,
                "total": total,
                "pct": round(got * 100.0 / total, 1) if total else None,
            })
            self._window.evaluate_js(
                "window.__whiteboard && window.__whiteboard.updateProgress(%s)" % payload
            )
        return report

    def download_update(self) -> dict:
        """下载最新版 exe 到「下载」文件夹。返回路径，让用户自己运行。"""
        try:
            info = check_update()
            if not info.get("ok"):
                return info
            ver = info["latest"]
            if not info.get("has_update"):
                return {"ok": False, "error": f"已经是最新版本 v{VERSION}"}

            # 镜像排前面：国内直连 release 资源经常只有几十 KB/s
            tag = str(info.get("tag") or f"v{ver}")
            direct = f"https://github.com/{REPO}/releases/download/{tag}/{EXE_ASSET}"
            urls = [
                f"{PROXY}{direct}",
                direct,
                info.get("asset_url") or "",
            ]
            dest = downloads_dir() / f"{APP_SLUG}-{ver}.exe"
            download_asset(urls, dest, on_progress=self._progress_cb())
            return {"ok": True, "path": str(dest), "version": ver}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def download_installer(self) -> dict:
        """下载自研安装器 SwiftGet，装不动的时候用它兜底。"""
        try:
            dest = downloads_dir() / "SwiftGet.exe"
            direct = f"https://github.com/{INSTALLER_REPO}/releases/latest/download/{INSTALLER_ASSET}"
            urls = [f"{PROXY}{direct}", direct]
            download_asset(urls, dest, on_progress=self._progress_cb())
            return {"ok": True, "path": str(dest)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def quit(self) -> None:
        os._exit(0)

    # ---------- 诊断 ----------

    def diag(self, msg: str) -> bool:
        """诊断模式下由页面写执行轨迹，用于定位卡死。

        直接 append 到文件：页面卡住时最后一条就是卡的位置。
        """
        try:
            path = app_dir() / "diag.log"
            too_big = path.exists() and path.stat().st_size > 2_000_000
            with open(path, "w" if too_big else "a", encoding="utf-8") as f:
                f.write(str(msg)[:500] + "\n")
            return True
        except Exception:
            return False

    # ---------- 内部 ----------

    def _ask_save_path(self, filename: str, file_types: tuple[str, ...]) -> str | None:
        from webview import FileDialog

        result = self._window.create_file_dialog(
            FileDialog.SAVE,
            directory=str(Path.home() / "Documents"),
            save_filename=filename,
            file_types=file_types,
        )
        return self._first(result)

    def _ask_open_path(self, file_types: tuple[str, ...]) -> str | None:
        from webview import FileDialog

        result = self._window.create_file_dialog(
            FileDialog.OPEN,
            allow_multiple=False,
            directory=str(Path.home() / "Documents"),
            file_types=file_types,
        )
        return self._first(result)

    @staticmethod
    def _first(result) -> str | None:
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            return result[0] if result else None
        return str(result)

    @staticmethod
    def _stamp() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y%m%d-%H%M")


def desktop_available() -> bool:
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


def make_dpi_aware() -> float:
    """声明 DPI 感知，返回缩放比。不做的话 200% 屏上窗口会大出一倍。"""
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def window_geometry() -> tuple[int, int, int, int]:
    """按当前屏幕算一个合适的初始窗口：不超过工作区的 86%，并居中。"""
    import ctypes

    scale = make_dpi_aware()
    try:
        u = ctypes.windll.user32
        work_w = u.GetSystemMetrics(0) / scale
        work_h = u.GetSystemMetrics(1) / scale
    except Exception:
        work_w, work_h = 1280, 800

    w = int(min(1400, max(960, work_w * 0.86)))
    h = int(min(900, max(620, work_h * 0.86)))
    x = int(max(0, (work_w - w) / 2))
    y = int(max(0, (work_h - h) / 2 - 20))
    return w, h, x, y


def report_crash(exc: BaseException) -> None:
    """窗口模式下没有控制台，把崩溃写进文件再弹个框，别让用户看到闪退。"""
    log = app_dir() / "crash.log"
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {__import__('datetime').datetime.now()} =====\n")
            f.write("".join(traceback.format_exception(exc)))
    except Exception:
        pass

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            f"启动失败：{exc}\n\n详细信息已写入：\n{log}",
            APP_TITLE,
            0x10,
        )
    except Exception:
        pass


def open_file_from_args(window) -> None:
    """支持把 .wbjson 拖到 exe 图标上直接打开。"""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        return
    path = Path(args[0])
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text)  # 先校验，别把坏文件塞给页面
        # 用 JSON 字符串字面量过去，再在页面里 JSON.parse：
        # 直接把文件内容拼进 JS 会被 U+2028 之类的字符搞崩。
        literal = json.dumps(text)
        window.evaluate_js(
            "window.__whiteboard && "
            f"window.__whiteboard.loadProject(JSON.parse({literal}))"
        )
    except Exception as e:
        print(f"打开 {path} 失败：{e}", file=sys.stderr)


def probe_update(window) -> None:
    """启动后在后台查一次最新版，有新版本才打扰用户。

    放线程里跑，网络再慢也不会拖住窗口；查不到就当没事发生。
    """
    try:
        info = check_update()
        if not (info.get("ok") and info.get("has_update")):
            return
        payload = json.dumps({
            "current": info["current"],
            "latest": info["latest"],
            "date": info.get("date") or "",
        }, ensure_ascii=True)
        window.evaluate_js(
            "window.__whiteboard && window.__whiteboard.showUpdate(%s)" % payload
        )
    except Exception:  # noqa: BLE001
        pass  # 更新检查失败绝不能影响正常使用


def main() -> int:
    try:
        import webview

        html = resource_root() / "ui" / "index.html"
        if not html.exists():
            raise FileNotFoundError(f"找不到界面文件：{html}")

        api = Api()
        win_w, win_h, win_x, win_y = window_geometry()
        window = webview.create_window(
            f"{APP_TITLE} {VERSION}",
            url=str(html),
            js_api=api,
            width=win_w,
            height=win_h,
            x=win_x,
            y=win_y,
            min_size=(880, 560),
            background_color="#EEF0F4",
            text_select=False,
            confirm_close=False,
        )
        api._window = window

        def on_loaded() -> None:
            open_file_from_args(window)
            if os.environ.get("WB_NO_UPDATE_CHECK") == "1":
                return
            threading.Thread(
                target=lambda: (time.sleep(1.5), probe_update(window)),
                daemon=True,
            ).start()

        window.events.loaded += on_loaded

        start_kwargs = {
            "private_mode": False,          # 关掉隐私模式，localStorage 才会留下来
            "storage_path": str(app_dir() / "webview"),
            "gui": "edgechromium",          # Win10/11 自带 WebView2
            "debug": os.environ.get("WHITEBOARD_DEBUG") == "1",
        }
        try:
            webview.start(**start_kwargs)
        except Exception:
            # 没有 WebView2 时退回系统默认内核，至少还能打开
            webview.start(private_mode=False, storage_path=str(app_dir() / "webview"))

        return 0
    except BaseException as exc:  # noqa: BLE001
        report_crash(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
