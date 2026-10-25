"""白板 · 桌面外壳。

用 pywebview 把 ui/index.html 装进一个原生窗口（Windows 上走 WebView2）。
所有文件读写都通过 js_api 暴露给页面，页面自己不碰磁盘。
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import traceback
from pathlib import Path

APP_NAME = "白板"
APP_ID = "WhiteboardDesktop"
VERSION = "1.0.0"

PROJECT_EXT = ".wbjson"
PNG_PREFIX = "data:image/png;base64,"


def resource_root() -> Path:
    """打包成 exe 后资源在临时解包目录里，源码运行时在项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    """用户数据目录：%APPDATA%\\WhiteboardDesktop。"""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


class Api:
    """暴露给页面 JS 的原生能力。"""

    def __init__(self) -> None:
        self.window = None

    # ---------- 工程文件 ----------

    def save_project(self, content: str, suggested: str = "") -> dict:
        """弹出保存对话框，把 JSON 写进文件。"""
        try:
            path = self._ask_save_path(
                suggested or f"白板-{self._stamp()}{PROJECT_EXT}",
                [(f"白板工程 (*{PROJECT_EXT})", f"*{PROJECT_EXT}"),
                 ("JSON 文件 (*.json)", "*.json")],
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
            path = self._ask_open_path(
                [(f"白板工程 (*{PROJECT_EXT})", f"*{PROJECT_EXT}"),
                 ("JSON 文件 (*.json)", "*.json")],
            )
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
                suggested or f"白板-{self._stamp()}.png",
                [("PNG 图片 (*.png)", "*.png")],
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

    def quit(self) -> None:
        os._exit(0)

    # ---------- 内部 ----------

    def _ask_save_path(self, filename: str, file_types: list[tuple[str, str]]) -> str | None:
        import webview

        result = self.window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(Path.home() / "Documents"),
            save_filename=filename,
            file_types=file_types,
        )
        return self._first(result)

    def _ask_open_path(self, file_types: list[tuple[str, str]]) -> str | None:
        import webview

        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
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
            APP_NAME,
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


def main() -> int:
    try:
        import webview

        html = resource_root() / "ui" / "index.html"
        if not html.exists():
            raise FileNotFoundError(f"找不到界面文件：{html}")

        api = Api()
        win_w, win_h, win_x, win_y = window_geometry()
        window = webview.create_window(
            f"{APP_NAME} {VERSION}",
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
        api.window = window
        window.events.loaded += lambda: open_file_from_args(window)

        icon = resource_root() / "assets" / "app.ico"
        start_kwargs = {
            "private_mode": False,          # 关掉隐私模式，localStorage 才会留下来
            "storage_path": str(app_dir() / "webview"),
            "gui": "edgechromium",          # Win10/11 自带 WebView2
            "debug": os.environ.get("WHITEBOARD_DEBUG") == "1",
        }
        if sys.platform == "win32":
            start_kwargs["ssl"] = True

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
