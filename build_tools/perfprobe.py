"""量渲染开销：放 300 笔迹上去，看拖动/平移/写字时每帧要多久。

跑法：python build_tools/perfprobe.py
结果同时写 %APPDATA%\\WhiteboardDesktop\\perf.txt
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import app_dir, window_geometry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "ui" / "index.html"
out: list[str] = []


def say(m: str) -> None:
    out.append(m)
    print(m, flush=True)


def call(window, js: str, timeout: float = 30.0):
    box: dict = {}

    def run():
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
        return "<<超时>>", timeout * 1000
    return box.get("v", box.get("e")), box.get("ms", 0.0)


def run_timed(window, start_js: str, budget: float = 25.0) -> str:
    """启动一段带 rAF 的测量，轮询 window.__perf 取结果。"""
    call(window, "window.__perf = null; window.__whiteboard.resetPerf(); 1")
    call(window, start_js)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < budget:
        v, _ = call(window, "window.__perf || ''")
        if v:
            return str(v)
        time.sleep(0.2)
    return "<<没等到结果>>"


def stats(window) -> str:
    """静态层重建了几次、平均每次多久、平均每帧多久。"""
    js = r"""
    (() => {
      const p = window.__whiteboard.perf;
      return JSON.stringify({
        重建次数: p.cacheN,
        平均重建ms: +(p.cacheN ? p.cacheMs / p.cacheN : 0).toFixed(1),
        帧数: p.frameN,
        平均每帧ms: +(p.frameN ? p.frameMs / p.frameN : 0).toFixed(1),
        选中: window.__whiteboard.state.selection.length,
        对象: window.__whiteboard.state.pages[0].objects.length,
      });
    })()
    """
    v, _ = call(window, js)
    return str(v)


SEED = r"""
(() => {
  const w = window.__whiteboard, s = w.state;
  s.pages = [{ id: 'p1', objects: [] }];
  s.current = 0;
  s.tool = 'select';
  const objs = s.pages[0].objects;
  for (let k = 0; k < 300; k++) {
    const pts = [];
    const x0 = (k % 20) * 70 + 40, y0 = (k % 15) * 46 + 40;
    for (let i = 0; i < 40; i++) pts.push({ x: x0 + i * 1.5, y: y0 + Math.sin(i / 5) * 12, p: 0.5, t: i });
    objs.push({ id: 'k' + k, type: 'path', penType: 'pen', color: '#1f2937',
                width: 3, opacity: 1, pressure: false, points: pts });
  }
  document.getElementById('welcome').classList.add('hide');
  w.invalidate();
  return objs.length;
})()
"""

TAIL = """
      const gaps = [];
      for (let k = 1; k < ts.length; k++) gaps.push(ts[k] - ts[k - 1]);
      gaps.sort((a, b) => a - b);
      window.__perf = JSON.stringify({
        frames: ts.length,
        avg: +(gaps.reduce((a, b) => a + b, 0) / Math.max(1, gaps.length)).toFixed(1),
        p95: +(gaps[Math.floor(gaps.length * 0.95)] || 0).toFixed(1),
        worst: +(gaps[gaps.length - 1] || 0).toFixed(1),
      });
"""

IDLE = """
(() => {
  const ts = [];
  const t0 = performance.now();
  const tick = (t) => {
    ts.push(t);
    if (t - t0 < 1500) requestAnimationFrame(tick);
    else {
""" + TAIL + """
    }
  };
  requestAnimationFrame(tick);
})()
"""

DRAG = """
(() => {
  const c = document.getElementById('board');
  c.setPointerCapture = () => {}; c.releasePointerCapture = () => {};
  const r = c.getBoundingClientRect();
  const ev = (t, x, y, b) => c.dispatchEvent(new PointerEvent(t, {
    bubbles: true, cancelable: true, clientX: x, clientY: y,
    pointerId: 1, isPrimary: true, pointerType: 'mouse', button: 0, buttons: b }));
  ev('pointerdown', r.x + 60, r.y + 60, 1);
  const ts = [];
  const t0 = performance.now();
  let i = 0;
  const tick = (t) => {
    ts.push(t);
    i++;
    ev('pointermove', r.x + 60 + i * 4, r.y + 60 + i * 2, 1);
    if (t - t0 < 1500) requestAnimationFrame(tick);
    else {
      ev('pointerup', r.x + 60 + i * 4, r.y + 60 + i * 2, 0);
""" + TAIL + """
    }
  };
  requestAnimationFrame(tick);
})()
"""

PAN = """
(() => {
  const c = document.getElementById('board');
  c.setPointerCapture = () => {}; c.releasePointerCapture = () => {};
  window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }));
  const r = c.getBoundingClientRect();
  const ev = (t, x, y, b) => c.dispatchEvent(new PointerEvent(t, {
    bubbles: true, cancelable: true, clientX: x, clientY: y,
    pointerId: 2, isPrimary: true, pointerType: 'mouse', button: 0, buttons: b }));
  ev('pointerdown', r.x + 400, r.y + 400, 1);
  const ts = [];
  const t0 = performance.now();
  let i = 0;
  const tick = (t) => {
    ts.push(t);
    i++;
    ev('pointermove', r.x + 400 + i * 2, r.y + 400 + i, 1);
    if (t - t0 < 1500) requestAnimationFrame(tick);
    else {
      ev('pointerup', r.x + 400 + i * 2, r.y + 400 + i, 0);
      window.dispatchEvent(new KeyboardEvent('keyup', { key: ' ' }));
""" + TAIL + """
    }
  };
  requestAnimationFrame(tick);
})()
"""

DRAW = """
(() => {
  const c = document.getElementById('board');
  c.setPointerCapture = () => {}; c.releasePointerCapture = () => {};
  window.__whiteboard.state.tool = 'pen';
  const r = c.getBoundingClientRect();
  const ev = (t, x, y, b) => c.dispatchEvent(new PointerEvent(t, {
    bubbles: true, cancelable: true, clientX: x, clientY: y,
    pointerId: 3, isPrimary: true, pointerType: 'mouse', button: 0, buttons: b }));
  ev('pointerdown', r.x + 100, r.y + 500, 1);
  const ts = [];
  const t0 = performance.now();
  let i = 0;
  const tick = (t) => {
    ts.push(t);
    i++;
    ev('pointermove', r.x + 100 + i * 3, r.y + 500 + Math.sin(i / 6) * 60, 1);
    if (t - t0 < 1500) requestAnimationFrame(tick);
    else {
      ev('pointerup', r.x + 100 + i * 3, r.y + 500, 0);
""" + TAIL + """
    }
  };
  requestAnimationFrame(tick);
})()
"""


def probe() -> None:
    w = webview.windows[0]
    time.sleep(1.0)
    n, _ = call(w, SEED)
    size, _ = call(w, "document.getElementById('board').width + 'x' + document.getElementById('board').height")
    say(f"塞入 {n} 笔迹（每笔 40 点），画布 {size}")
    time.sleep(0.6)

    for label, js in (("空闲", IDLE), ("拖动对象", DRAG), ("平移画布", PAN), ("写字", DRAW)):
        r = run_timed(w, js)
        say(f"  {label:6s} → 帧 {r}")
        say(f"          → 渲染 {stats(w)}")

    say("\n判读：avg 约 16.7ms = 60fps。worst > 200ms 能感到卡，> 1000ms Windows 会打「未响应」。")


def on_loaded() -> None:
    try:
        probe()
    except Exception as e:  # noqa: BLE001
        say(f"探针异常：{type(e).__name__}: {e}")
    finally:
        (app_dir() / "perf.txt").write_text("\n".join(out), encoding="utf-8")
        time.sleep(0.2)
        webview.windows[0].destroy()


def main() -> int:
    w, h, x, y = window_geometry()
    webview.create_window("白板 性能探针", url=str(HTML), width=w, height=h, x=x, y=y,
                          min_size=(880, 560), background_color="#EEF0F4")
    webview.windows[0].events.loaded += on_loaded
    webview.start(private_mode=True, gui="edgechromium", debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
