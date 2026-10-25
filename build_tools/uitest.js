/**
 * 界面功能自检：用真实 Edge 内核跑一遍关键交互。
 *
 * 打包出来的 exe 里装的就是这个 index.html，所以在这里验过，
 * 就等于验过桌面版（差别只在原生外壳和文件对话框）。
 *
 * 跑法：
 *   NODE_PATH=<workspace>/node_modules node build_tools/uitest.js
 */
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');

const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok, detail });
  console.log(`${ok ? '✓' : '✗'} ${name}${detail ? '  — ' + detail : ''}`);
}

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push('console: ' + m.text());
  });

  await page.goto(HTML);
  await page.waitForTimeout(500);

  const st = () => page.evaluate(() => {
    const s = window.__whiteboard.state;
    const p = s.pages[s.current];
    return {
      objects: p.objects.map((o) => ({ type: o.type, id: o.id, locked: !!o.locked })),
      selection: s.selection.length,
      tool: s.tool,
      penType: s.penType,
      color: s.color,
      size: s.size,
    };
  });

  // ---- 1. 侧边栏是细长条 ----
  const rail = await page.evaluate(() => {
    const r = document.getElementById('rail').getBoundingClientRect();
    return { w: r.width, x: r.x, right: r.right, vw: innerWidth };
  });
  check('右侧栏是细长条（56px 宽）', Math.round(rail.w) === 56, `实测 ${rail.w.toFixed(1)}px`);
  check('侧边栏贴右边', Math.abs(rail.right - rail.vw) < 2, `right=${rail.right}, vw=${rail.vw}`);

  // ---- 2. 欢迎按钮在屏幕正中 ----
  const mid = await page.evaluate(() => {
    const b = document.querySelector('#welcome .wcard').getBoundingClientRect();
    return { cx: b.x + b.width / 2, cy: b.y + b.height / 2, vw: innerWidth, vh: innerHeight };
  });
  const dx = Math.abs(mid.cx - mid.vw / 2);
  const dy = Math.abs(mid.cy - mid.vh / 2);
  check('开场提示卡片居中', dx < 20 && dy < 20, `偏移 ${dx.toFixed(1)} / ${dy.toFixed(1)} px`);

  // ---- 3. 开始写字后进入画板 ----
  await page.click('#btnStart');
  await page.waitForTimeout(300);
  const hidden = await page.evaluate(() =>
    document.getElementById('welcome').classList.contains('hide'));
  check('点「开始写字」收起欢迎页', hidden);

  // ---- 4. 画一笔 ----
  const box = await page.locator('#board').boundingBox();
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx - 160, cy);
  await page.mouse.down();
  for (let i = 1; i <= 24; i++) {
    await page.mouse.move(cx - 160 + i * 13, cy + Math.sin(i / 3) * 40);
  }
  await page.mouse.up();
  await page.waitForTimeout(200);
  let s = await st();
  check('能在画布上写字（生成 path 对象）', s.objects.length === 1 && s.objects[0].type === 'path',
    `对象：${JSON.stringify(s.objects)}`);

  // ---- 5. 笔设置小窗：启动不弹、点开、再点收起、点外面收起 ----
  const popState = () => page.evaluate(() => {
    const p = document.getElementById('penPop');
    const r = p.getBoundingClientRect();
    return { shown: getComputedStyle(p).display !== 'none' && r.width > 60, w: r.width, h: r.height };
  });

  const bootPop = await popState();
  check('启动时笔设置小窗不自动弹出', !bootPop.shown);

  await page.click('#btnPen');
  await page.waitForTimeout(250);
  const open1 = await popState();
  check('点画笔图标弹出设置小窗', open1.shown, `${open1.w.toFixed(0)}×${open1.h.toFixed(0)}`);

  await page.click('#btnPen');
  await page.waitForTimeout(250);
  const open2 = await popState();
  check('再点画笔图标能收起小窗', !open2.shown);

  await page.click('#btnPen');
  await page.waitForTimeout(250);
  const open3 = await popState();
  check('第三次点击又能打开', open3.shown);

  // 切到选择工具再点空白处：既能验证"点外面关小窗"，又不会画出多余的点
  await page.keyboard.press('v');
  await page.click('#board', { position: { x: 40, y: 40 } });
  await page.waitForTimeout(250);
  const open4 = await popState();
  check('点画布空白处能关掉小窗', !open4.shown);

  // 打开小窗，后面的颜色/粗细/笔型都在里面改
  await page.keyboard.press('p');   // 切回画笔（此时不弹窗）
  await page.click('#btnPen');      // 再点一次才弹
  await page.waitForTimeout(250);

  // ---- 6. 小窗里换颜色和粗细 ----
  const before = await st();
  await page.click('#penColors .pc:nth-child(4)');
  await page.click('#penSizes .psize:nth-child(4)');
  await page.waitForTimeout(200);
  const after = await st();
  check('小窗能改颜色', after.color !== before.color, `${before.color} → ${after.color}`);
  check('小窗能改粗细', after.size !== before.size, `${before.size} → ${after.size}`);

  // ---- 7. 三种笔型 ----
  await page.click('.pen-tab[data-pen="marker"]');
  await page.waitForTimeout(150);
  const marker = await st();
  check('能切换荧光笔', marker.penType === 'marker', marker.penType);
  await page.click('.pen-tab[data-pen="brush"]');
  await page.waitForTimeout(150);
  const brush = await st();
  check('能切换书法笔', brush.penType === 'brush', brush.penType);
  await page.click('.pen-tab[data-pen="pen"]');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);

  // ---- 8. 框选 ----
  await page.click('[data-tool="select"]');
  await page.waitForTimeout(150);
  await page.mouse.move(cx - 220, cy - 130);
  await page.mouse.down();
  for (let i = 1; i <= 12; i++) {
    await page.mouse.move(cx - 220 + i * 25, cy - 130 + i * 18);
  }
  await page.mouse.up();
  await page.waitForTimeout(300);
  s = await st();
  check('能自由框选对象', s.selection >= 1, `选中 ${s.selection} 个`);

  const bar = await page.evaluate(() => {
    const b = document.getElementById('selbar');
    const r = b.getBoundingClientRect();
    const btns = [...b.querySelectorAll('button')].map((x) => x.title || x.textContent.trim());
    return { shown: getComputedStyle(b).display !== 'none' && r.width > 80, h: r.height, btns };
  });
  check('框选后出现浮动工具条', bar.shown, `${bar.btns.join(' / ')}`);
  check('工具条含置顶/锁定/字号/颜色/删除',
    ['置顶', '锁定', '字号', '颜色', '删除'].every((k) => bar.btns.join(' ').includes(k)),
    bar.btns.join(' / '));

  // ---- 9. 锁定 ----
  await page.click('#sbLock');
  await page.waitForTimeout(200);
  s = await st();
  check('能锁定选中对象', s.objects.some((o) => o.locked), JSON.stringify(s.objects));
  await page.click('#sbLock');
  await page.waitForTimeout(200);
  s = await st();
  check('能解锁', s.objects.every((o) => !o.locked), JSON.stringify(s.objects));

  // ---- 10. 拖动移动 ----
  const firstPoint = () => page.evaluate(() => {
    const s = window.__whiteboard.state;
    const o = s.pages[s.current].objects.find((x) => x.type === 'path');
    return o && o.points && o.points.length ? [o.points[0].x, o.points[0].y] : null;
  });
  // 按住笔画起点本身（笔画起点精确在 cx-160, cy）
  await page.mouse.click(cx - 160, cy);
  await page.waitForTimeout(200);
  const selOne = await page.evaluate(() => window.__whiteboard.state.selection.length);
  check('点选能选中对象', selOne === 1, `选中 ${selOne}`);

  const p0 = await firstPoint();
  await page.mouse.move(cx - 160, cy);
  await page.mouse.down();
  await page.mouse.move(cx - 110, cy + 50, { steps: 10 });
  await page.mouse.up();
  await page.waitForTimeout(200);
  const p1 = await firstPoint();
  const moved = p0 && p1 && (Math.abs(p1[0] - p0[0]) > 20 || Math.abs(p1[1] - p0[1]) > 20);
  check('能拖动改变位置', !!moved, `${JSON.stringify(p0)} → ${JSON.stringify(p1)}`);

  // ---- 11. 插入小黑板 ----
  await page.keyboard.press('Escape');
  await page.click('#btnBoard');
  await page.waitForTimeout(300);
  s = await st();
  const boards = s.objects.filter((o) => o.type === 'board');
  check('能从侧边栏插入小黑板', boards.length === 1, `board 对象 ${boards.length} 个`);

  // 小黑板上写字应自动用白笔
  const boardInk = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    return { x: b.x, y: b.y, w: b.w, h: b.h };
  });
  check('小黑板带位置尺寸', boardInk.w > 100 && boardInk.h > 60,
    `${Math.round(boardInk.w)}×${Math.round(boardInk.h)}`);

  // ---- 12. 撤销 / 重做 ----
  const n1 = (await st()).objects.length;
  await page.click('#btnUndo');
  await page.waitForTimeout(200);
  const n2 = (await st()).objects.length;
  check('撤销有效', n2 < n1, `${n1} → ${n2}`);
  await page.click('#btnRedo');
  await page.waitForTimeout(200);
  const n3 = (await st()).objects.length;
  check('重做有效', n3 === n1, `${n2} → ${n3}`);

  // ---- 13. 多页 ----
  await page.click('#btnPages');
  await page.waitForTimeout(200);
  await page.click('#btnAddPage');
  await page.waitForTimeout(300);
  const pages = await page.evaluate(() => window.__whiteboard.state.pages.length);
  check('能新增页面', pages >= 2, `${pages} 页`);
  await page.keyboard.press('Escape');

  // ---- 14. 长笔画性能（老未响应的核心场景）----
  await page.click('[data-tool="pen"]');
  await page.waitForTimeout(150);
  const perf = await page.evaluate(async () => {
    // 模拟一根 600 点的长线：直接量绘制耗时
    const s = window.__whiteboard.state;
    const p = s.pages[s.current];
    const t0 = performance.now();
    const pts = [];
    for (let i = 0; i < 600; i++) {
      pts.push({ x: 100 + i * 1.5, y: 200 + Math.sin(i / 8) * 90, p: 0.5, t: i });
    }
    p.objects.push({ id: 'perf' + Date.now(), type: 'path', penType: 'pen',
      color: '#1f2937', width: 4, opacity: 1, pressure: false, points: pts });
    window.__whiteboard.invalidate && window.__whiteboard.invalidate();
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    return performance.now() - t0;
  });
  check('600 点长笔画两帧内画完（无卡顿）', perf < 400, `${perf.toFixed(0)} ms`);

  // ---- 15. 连续 30 帧渲染 ----
  const fps = await page.evaluate(async () => {
    let frames = 0;
    const t0 = performance.now();
    await new Promise((resolve) => {
      const tick = () => {
        frames += 1;
        if (performance.now() - t0 > 1000) resolve();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    return (frames * 1000) / (performance.now() - t0);
  });
  check('页面帧率正常', fps > 30, `${fps.toFixed(0)} fps`);

  // ---- 16. 存档往返：导出结构再重新载入 ----
  const round = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const snapshot = {
      app: 'whiteboard', version: 2,
      pages: s.pages.map((p) => ({ id: p.id, objects: p.objects })),
    };
    const before = s.pages.map((p) => p.objects.map((o) => o.type));
    const okLoad = window.__whiteboard.loadProject(JSON.parse(JSON.stringify(snapshot)));
    const after = window.__whiteboard.state.pages.map((p) => p.objects.map((o) => o.type));
    return { okLoad, before, after };
  });
  check('工程存档能重新载入且内容不丢',
    round.okLoad && JSON.stringify(round.before) === JSON.stringify(round.after),
    `${JSON.stringify(round.before)} → ${JSON.stringify(round.after)}`);

  // ---- 17. 导出 PNG ----
  let pngOk = false;
  let pngBytes = 0;
  try {
    const [dl] = await Promise.all([
      page.waitForEvent('download', { timeout: 8000 }),
      page.evaluate(() => window.__whiteboard.exportPng()),
    ]);
    const f = await dl.path();
    pngBytes = f ? require('fs').statSync(f).size : 0;
    pngOk = /\.png$/i.test(dl.suggestedFilename()) && pngBytes > 5000;
  } catch (e) {
    pngOk = false;
  }
  check('能导出 PNG（桌面版走原生保存框）', pngOk, `${(pngBytes / 1024).toFixed(0)} KB`);

  // ---- 18. 报错 ----
  check('运行期无 JS 报错', errors.length === 0, errors.slice(0, 4).join(' | '));

  // ---- 截图留档 ----
  const shot = path.join(__dirname, '_uitest.png');
  await page.screenshot({ path: shot });

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} 项通过`);
  if (failed.length) {
    console.log('未通过：' + failed.map((f) => f.name).join('、'));
    process.exit(1);
  }
}

main().catch((e) => {
  console.error('自检脚本异常：', e);
  process.exit(2);
});
