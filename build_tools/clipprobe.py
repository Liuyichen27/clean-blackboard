"""真机验一次：分享长图 + 原生剪贴板兜底。

开一个真窗口（跟正式版一样的参数），点一下分享，再直接调一次 Api.copy_image，
把结果写进 %APPDATA%/CleanBlackboard/clipprobe.txt，然后自己关掉。

用法：.buildenv/Scripts/python.exe build_tools/clipprobe.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import Api, app_dir, window_geometry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "ui" / "index.html"

out: list[str] = []


def say(msg: str) -> None:
    out.append(msg)
    print(msg, flush=True)


def call(win, js: str, timeout: float = 20.0):
    box: dict = {}

    def run() -> None:
        try:
            box["v"] = win.evaluate_js(js)
        except Exception as e:  # noqa: BLE001
            box["e"] = f"{type(e).__name__}: {e}"

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    return box.get("v", box.get("e"))


def probe(api: Api) -> None:
    win = webview.windows[0]
    time.sleep(1.6)

    say(f"pywebview: {call(win, 'typeof window.pywebview')}")
    say(f"native: {call(win, 'typeof (window.pywebview && window.pywebview.api)')}")

    # 造点内容，然后点分享（异步，先点火再读数）
    call(win, r"""
      (() => {
        const s = window.__whiteboard.state;
        s.pages[0].objects = [
          { id: 'p1', type: 'path', penType: 'pen', color: '#1f2937', width: 6, opacity: 1,
            points: [{x:120,y:140},{x:420,y:320},{x:760,y:180}] },
          { id: 't1', type: 'text', x: 120, y: 60, size: 42, color: '#1f2937', text: '分享测试' },
        ];
        s.pages.push({ id: 'pg2', objects: [
          { id: 'p2', type: 'path', penType: 'pen', color: '#e0453f', width: 6, opacity: 1,
            points: [{x:140,y:140},{x:700,y:520}] } ]});
        window.__whiteboard.invalidate();
        document.getElementById('btnShare').click();
        return 1;
      })()
    """)
    time.sleep(3.0)
    say("分享窗：" + str(call(win, r"""
      (() => {
        const img = document.getElementById('shareImg');
        return JSON.stringify({
          shown: document.getElementById('shareWrap').classList.contains('show'),
          w: img.naturalWidth, h: img.naturalHeight,
          meta: document.getElementById('shareMeta').textContent,
        });
      })()
    """)))

    # 原生兜底：直接调 Api，不经过页面
    data_url = call(win, r"""
      (() => {
        const c = document.createElement('canvas');
        c.width = 320; c.height = 160;
        const g = c.getContext('2d');
        g.fillStyle = '#2f6bff'; g.fillRect(0, 0, 320, 160);
        g.fillStyle = '#fff'; g.font = 'bold 44px sans-serif'; g.fillText('CB', 120, 98);
        return c.toDataURL('image/png');
      })()
    """)
    if isinstance(data_url, str) and data_url.startswith("data:image/png"):
        say(f"dataURL 长度 {len(data_url)}")
        t0 = time.perf_counter()
        res = api.copy_image(data_url)
        say(f"原生 copy_image → {json.dumps(res, ensure_ascii=False)}（{(time.perf_counter()-t0)*1000:.0f} ms）")
    else:
        say(f"取 dataURL 失败：{data_url}")


def on_loaded(api: Api) -> None:
    try:
        probe(api)
    except Exception as e:  # noqa: BLE001
        say(f"探针异常：{type(e).__name__}: {e}")
    finally:
        (app_dir() / "clipprobe.txt").write_text("\n".join(out), encoding="utf-8")
        time.sleep(0.3)
        webview.windows[0].destroy()


def main() -> int:
    w, h, x, y = window_geometry()
    api = Api()
    win = webview.create_window("CleanBlackboard 剪贴板探针", url=str(HTML), width=w, height=h,
                                x=x, y=y, min_size=(880, 560), js_api=api,
                                background_color="#EEF0F4")
    api._window = win
    win.events.loaded += lambda: on_loaded(api)
    webview.start(private_mode=False, storage_path=str(app_dir() / "webview"),
                  gui="edgechromium", debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
