/**
 * 生成文档用截图：欢迎页 + 画好的画布（含小黑板、框选工具条）。
 *
 * 用真实 Edge 内核渲染，和 exe 里看到的一致。
 *   NODE_PATH=<workspace>/node_modules node build_tools/shots.js
 */
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');

const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(HTML);
  await page.waitForTimeout(600);

  // 1) 欢迎页：卡片居中 + 右侧细长条
  await page.screenshot({ path: path.join(__dirname, '..', 'assets', 'shot-welcome.png') });

  // 2) 画布：手写笔迹、形状、文字、小黑板
  await page.click('#btnStart');
  await page.waitForTimeout(400);

  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const objs = s.pages[s.current].objects;

    const wave = (x0, y0, len, amp, color, width, n) => {
      const points = [];
      for (let i = 0; i < n; i += 1) {
        points.push({ x: x0 + (i / n) * len, y: y0 + Math.sin(i / 9) * amp, p: 0.5, t: i });
      }
      objs.push({ id: 'd' + Math.random().toString(36).slice(2), type: 'path', penType: 'pen',
        color, width, opacity: 1, pressure: false, points });
    };

    // 标题文字
    objs.push({ id: 't1', type: 'text', color: '#16213a', opacity: 1,
      x: 150, y: 110, size: 42, text: '今天的课：一次函数' });

    // 三色笔迹
    wave(150, 230, 420, 26, '#2f6bff', 5, 220);
    wave(150, 300, 420, 26, '#ef4444', 5, 220);
    wave(150, 370, 420, 26, '#22c55e', 5, 220);

    // 一个矩形（待框选）
    objs.push({ id: 'r1', type: 'rect', color: '#f59e0b', width: 4, opacity: 1,
      x1: 640, y1: 200, x2: 900, y2: 330, fill: false });

    // 小黑板
    objs.push({ id: 'b1', type: 'board', color: '#20262f', opacity: 1,
      x: 640, y: 380, w: 460, h: 250 });

    // 小黑板上的白字
    objs.push({ id: 't2', type: 'text', color: '#f4f7ff', opacity: 1,
      x: 690, y: 450, size: 34, text: 'y = kx + b' });
    const points = [];
    for (let i = 0; i < 160; i += 1) {
      points.push({ x: 690 + i * 2, y: 560 - Math.sin(i / 40) * 40, p: 0.5, t: i });
    }
    objs.push({ id: 'p2', type: 'path', penType: 'pen', color: '#f4f7ff', width: 4,
      opacity: 1, pressure: false, points });

    window.__whiteboard.invalidate && window.__whiteboard.invalidate();
  });
  await page.waitForTimeout(400);

  // 框选矩形，让浮动工具条出现在图里
  const pts = await page.evaluate(() => {
    const o = window.__whiteboard.state.pages[0].objects.find((x) => x.id === 'r1');
    return { x: o.x1, y: o.y1, w: o.x2 - o.x1, h: o.y2 - o.y1 };
  });
  await page.click('[data-tool="select"]');
  await page.mouse.move(pts.x - 30, pts.y - 30);
  await page.mouse.down();
  await page.mouse.move(pts.x + pts.w + 30, pts.y + pts.h + 30, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(500);

  await page.screenshot({ path: path.join(__dirname, '..', 'assets', 'shot-canvas.png') });

  const n = await page.evaluate(() => window.__whiteboard.state.selection.length);
  console.log(`截图完成，框中 ${n} 个对象`);
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
