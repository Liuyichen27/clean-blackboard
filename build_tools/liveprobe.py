"""在真实 WebView2 内核里做探针：复现用户反馈的三个问题。

和 main.py 用完全一样的窗口参数与 storage_path，跑完自己关掉。

用法：
    python build_tools/liveprobe.py

它只回答问题，不改代码：
  1. 启动时笔设置面板是不是自己弹出来了
  2. 点画笔图标能不能开 / 关
  3. 每次操作，JS 主线程被占了多久（>200ms 人就能感觉到卡，>2s Windows 会打「未响应」）
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app_dir, make_dpi_aware, window_geometry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "ui" / "index.html"

out: list[str] = []


def say(msg: str) -> None:
    out.append(msg)
    print(msg, flush=True)


def call(window, js: str, timeout: float = 20.0) -> tuple[object, float, bool]:
    """在主线程里执行 JS，返回 (结果, 耗时ms, 是否超时)。"""
    box: dict = {}

    def run() -> None:
        t0 = time.perf_counter()
        try:
            box["v"] = window.evaluate_js(js)
        except Exception as e:  # noqa: BLE001
            box["e"] = f"{type(e).__name__}: {e}"
        box["ms"] = (time.perf_counter() - t0) * 1000

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        return "<<超时：JS 线程被卡住>>", timeout * 1000, True
    return box.get("v", box.get("e")), box.get("ms", 0.0), False


def boot_state(window) -> None:
    js = r"""
    (() => {
      const p = document.getElementById('penPop');
      const cs = getComputedStyle(p);
      return JSON.stringify({
        wb: typeof window.__whiteboard,
        errors: window.__errors || null,
        pywebview: typeof window.pywebview,
        penPopClass: p.className,
        penPopDisplay: cs.display,
        penPopVis: cs.visibility,
        penPopLeft: cs.left,
        penPopRect: (() => { const r = p.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })(),
        tool: (window.__whiteboard && window.__whiteboard.state.tool) || null,
        dpr: devicePixelRatio,
        vw: innerWidth, vh: innerHeight,
        railW: document.getElementById('rail').getBoundingClientRect().width,
        canvas: (() => { const c = document.getElementById('board'); return [c.clientWidth, c.clientHeight, c.width, c.height]; })(),
      });
    })()
    """
    v, ms, to = call(window, js)
    say(f"\n[启动状态] 读取耗时 {ms:.0f} ms{'  ← 超时' if to else ''}")
    say(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))


def heartbeat(window, label: str, wait: float = 1.2) -> None:
    """心跳：页面每 50ms 自增一次，卡住就停。"""
    call(window, "window.__b=0; if(!window.__bt){window.__bt=setInterval(()=>window.__b++,50);} 1")
    time.sleep(wait)
    v, ms, to = call(window, "window.__b")
    expect = wait / 0.05
    say(f"  [心跳] {label}: {v}/{expect:.0f} 次（{ms:.0f} ms 往返）{'  ← 超时' if to else ''}")


def probe() -> None:
    window = webview.windows[0]
    time.sleep(1.2)

    boot_state(window)
    heartbeat(window, "空闲")

    say("\n[点一次画笔图标]")
    v, ms, to = call(window, "document.getElementById('btnPen').click(); 1")
    time.sleep(0.4)
    v, ms2, to2 = call(window, r"""
      (() => { const p = document.getElementById('penPop');
        return JSON.stringify({cls: p.className, disp: getComputedStyle(p).display,
          rect: (() => { const r = p.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width)]; })()}); })()
    """)
    say(f"  点击耗时 {ms:.0f} ms / 读状态 {ms2:.0f} ms")
    say(f"  结果 {v}")

    say("\n[再点一次画笔图标（应当收起）]")
    v, ms, to = call(window, "document.getElementById('btnPen').click(); 1")
    time.sleep(0.4)
    v, ms2, _ = call(window, r"""
      (() => { const p = document.getElementById('penPop');
        return JSON.stringify({cls: p.className, disp: getComputedStyle(p).display}); })()
    """)
    say(f"  点击耗时 {ms:.0f} ms")
    say(f"  结果 {v}")

    say("\n[不点任何东西，直接点外面（应当关闭）]")
    call(window, "document.getElementById('btnPen').click(); 1")
    time.sleep(0.3)
    call(window, "document.getElementById('welcome').click(); 1")
    time.sleep(0.3)
    v, ms, _ = call(window, r"""
      (() => { const p = document.getElementById('penPop');
        return JSON.stringify({cls: p.className, disp: getComputedStyle(p).display}); })()
    """)
    say(f"  点空白后 {v}")

    say("\n[开始写字 + 画一笔]")
    v, ms, _ = call(window, "document.getElementById('btnStart').click(); 1")
    say(f"  点「开始写字」{ms:.0f} ms")
    time.sleep(0.3)
    v, ms, to = call(window, r"""
      (() => {
        const c = document.getElementById('board');
        c.setPointerCapture = () => {};   // 合成事件没有真实 pointerId
        c.releasePointerCapture = () => {};
        const r = c.getBoundingClientRect();
        const mk = (t, x, y, btns) => c.dispatchEvent(new PointerEvent(t, {
          bubbles: true, cancelable: true, clientX: x, clientY: y,
          pointerId: 1, isPrimary: true, pointerType: 'mouse', button: 0, buttons: btns,
        }));
        const t0 = performance.now();
        mk('pointerdown', r.x + 300, r.y + 300, 1);
        for (let i = 1; i < 60; i++) mk('pointermove', r.x + 300 + i * 5, r.y + 300 + Math.sin(i / 4) * 34, 1);
        mk('pointerup', r.x + 600, r.y + 300, 0);
        const dt = performance.now() - t0;
        return JSON.stringify({ ms: Math.round(dt), objs: window.__whiteboard.state.pages[0].objects.length });
      })()
    """)
    say(f"  画一笔（60 点）{v}  往返 {ms:.0f} ms{'  ← 超时' if to else ''}")
    heartbeat(window, "画完之后")

    say("\n[连续快速点击 20 次]")
    v, ms, to = call(window, r"""
      (() => {
        const t0 = performance.now();
        for (let i = 0; i < 20; i++) document.getElementById('btnPen').click();
        return Math.round(performance.now() - t0);
      })()
    """)
    say(f"  20 次点击总计 {v} ms{'  ← 超时' if to else ''}")

    say("\n[撤销 / 重做]")
    v, ms, to = call(window, r"""
      (() => {
        const t0 = performance.now();
        document.getElementById('btnUndo').click();
        document.getElementById('btnRedo').click();
        return Math.round(performance.now() - t0);
      })()
    """)
    say(f"  {v} ms{'  ← 超时' if to else ''}")

    say("\n[窗口是否被判定未响应]")
    import ctypes

    hwnd = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _):
        nonlocal hwnd
        n = ctypes.windll.user32.GetWindowTextLengthW(h)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            ctypes.windll.user32.GetWindowTextW(h, buf, n + 1)
            if "简黑板" in buf.value:
                hwnd = h
        return True

    ctypes.windll.user32.EnumWindows(cb, 0)
    say(f"  hwnd={hwnd} IsHungAppWindow={bool(ctypes.windll.user32.IsHungAppWindow(hwnd)) if hwnd else 'n/a'}")

    say(f"\n崩溃日志：{(app_dir() / 'crash.log')}")


def on_loaded() -> None:
    try:
        probe()
    except Exception as e:  # noqa: BLE001
        say(f"探针异常：{type(e).__name__}: {e}")
    finally:
        (app_dir() / "probe.txt").write_text("\n".join(out), encoding="utf-8")
        time.sleep(0.3)
        webview.windows[0].destroy()


def main() -> int:
    w, h, x, y = window_geometry()
    webview.create_window("简黑板 探针", url=str(HTML), width=w, height=h, x=x, y=y,
                          min_size=(880, 560), background_color="#EEF0F4")
    webview.windows[0].events.loaded += on_loaded
    webview.start(private_mode=False, storage_path=str(app_dir() / "webview"),
                  gui="edgechromium", debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
