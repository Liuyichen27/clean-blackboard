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

  // ---- 0. 首次启动：英文提示选语言 ----
  const langDlg = await page.evaluate(() => ({
    shown: document.getElementById('langWrap').classList.contains('show'),
    title: document.querySelector('#langCard h3').textContent.trim(),
    desc: document.querySelector('#langCard p').textContent.trim(),
    opts: [...document.querySelectorAll('#langCard [data-lang]')].map((b) => b.textContent.trim()),
  }));
  check('第一次打开会弹语言选择框', langDlg.shown);
  check('提示是英文', /Choose your language/.test(langDlg.title), langDlg.title);
  check('两个选项：简体中文 / English',
    /简体中文/.test(langDlg.opts[0]) && /English/.test(langDlg.opts[1]), langDlg.opts.join(' | '));

  await page.click('#langCard [data-lang="zh"]');
  await page.waitForTimeout(250);
  check('选完语言后弹框关闭',
    !(await page.evaluate(() => document.getElementById('langWrap').classList.contains('show'))));
  check('选中文后界面是中文',
    (await page.evaluate(() => document.getElementById('fileTitle').textContent)) === '文件');

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
  check('小窗里有吸管按钮',
    await page.evaluate(() => !!document.getElementById('penPick')));
  check('吸管按钮可见',
    await page.isVisible('#penPick'));
  // 走「吸管取到色之后」的同一条路：改原生取色器的值并触发 input
  await page.evaluate(() => {
    const p = document.getElementById('colorPicker');
    p.value = '#12ab34';
    p.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(150);
  const penPicked = await page.evaluate(() => window.__whiteboard.state.color);
  check('取色能设成画笔颜色', penPicked === '#12ab34', penPicked);
  check('取色后原生取色器同步',
    (await page.evaluate(() => document.getElementById('colorPicker').value)) === '#12ab34');

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

  // ---- 9. 锁定（只对图片/小黑板生效，涂鸦钉在纸上不用锁）----
  await page.click('#sbLock');
  await page.waitForTimeout(200);
  s = await st();
  check('涂鸦不参与锁定（本来就钉在纸上）',
    s.objects.every((o) => !o.locked), JSON.stringify(s.objects));

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

  // ---- 18. 小黑板：浮动 / 锁定 / 跟随笔画 ----
  const boardInfo = () => page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    if (!b) return null;
    const kids = s.pages[s.current].objects.filter((o) => o.owner === b.id);
    return {
      id: b.id, locked: !!b.locked, color: b.color,
      x: b.x, y: b.y, w: b.w, h: b.h,
      screenX: b.x * s.cam.s + s.cam.x, screenY: b.y * s.cam.s + s.cam.y,
      kids: kids.length,
      kidPos: kids.map((k) => (k.points ? [k.points[0].x, k.points[0].y] : null)),
    };
  });

  // 在小黑板上写一笔，笔画应被记成它的子笔画
  const b0 = await boardInfo();
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    window.__probe = { x: b.x * s.cam.s + s.cam.x + b.w * s.cam.s / 2,
                       y: b.y * s.cam.s + s.cam.y + b.h * s.cam.s / 2 };
  });
  const pb = await page.evaluate(() => window.__probe);
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.selection = [];
    const canvas = document.getElementById('board');
    canvas.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: window.__probe.x, clientY: window.__probe.y, button: 0, pointerId: 1 }));
    for (let i = 1; i <= 6; i++) {
      canvas.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: window.__probe.x + i * 6, clientY: window.__probe.y + i * 3, buttons: 1, pointerId: 1 }));
    }
    canvas.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: window.__probe.x + 36, clientY: window.__probe.y + 18, button: 0, pointerId: 1 }));
  });
  await page.waitForTimeout(200);
  const b1 = await boardInfo();
  check('在小黑板上写字归属到板子', b1 && b1.kids >= 1, `子笔画 ${b1 ? b1.kids : '?'} 笔`);

  // 拖动小黑板，板上的字要跟着走（用选择工具 + 真实鼠标）
  await page.click('[data-tool="select"]');
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    s.selection = [];
    window.__dragFrom = { x: b.x * s.cam.s + s.cam.x + 16, y: b.y * s.cam.s + s.cam.y + 16 };
  });
  const df = await page.evaluate(() => window.__dragFrom);
  await page.mouse.move(df.x, df.y);
  await page.mouse.down();
  await page.mouse.move(df.x + 60, df.y + 40, { steps: 6 });
  await page.mouse.up();
  await page.waitForTimeout(200);
  const b2 = await boardInfo();
  check('拖动小黑板后板上的字跟着走',
    b2 && b2.kids >= 1 && Math.abs((b2.x - b1.x) - 60 / await page.evaluate(() => window.__whiteboard.state.cam.s)) < 3,
    `板位移 ${(b2.x - b1.x).toFixed(1)}`);

  // 浮动：滚轮平移时小黑板在屏幕上不动
  const beforePan = (await boardInfo()).screenY;
  await page.mouse.move(200, 400);
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(200);
  const afterPan = (await boardInfo()).screenY;
  check('未锁定时小黑板不随白板滚动（浮在屏幕上）',
    Math.abs(afterPan - beforePan) < 2, `屏幕 y：${beforePan.toFixed(1)} → ${afterPan.toFixed(1)}`);

  // 锁定后应跟着白板一起滚
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    s.selection = [b];
    document.getElementById('sbLock').click();
  });
  await page.waitForTimeout(200);
  const lockedInfo = await boardInfo();
  check('小黑板能锁定', lockedInfo.locked, JSON.stringify({ locked: lockedInfo.locked }));

  // 锁定后仍然点得中（否则永远解不开）
  await page.evaluate(() => { window.__whiteboard.state.selection = []; });
  const probe = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    return { x: b.x * s.cam.s + s.cam.x + 12, y: b.y * s.cam.s + s.cam.y + 12 };
  });
  await page.mouse.click(probe.x, probe.y);
  await page.waitForTimeout(200);
  const selAfterClick = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    return s.selection.map((o) => o.type);
  });
  check('锁定后仍能点选（好点解锁）', selAfterClick.includes('board'), JSON.stringify(selAfterClick));
  const beforePan2 = (await boardInfo()).screenY;
  await page.mouse.move(200, 400);
  await page.mouse.wheel(0, 120);
  await page.waitForTimeout(200);
  const afterPan2 = (await boardInfo()).screenY;
  check('锁定后小黑板跟着白板滚动',
    Math.abs(afterPan2 - beforePan2) > 20, `屏幕 y：${beforePan2.toFixed(1)} → ${afterPan2.toFixed(1)}`);


  // ---- 19. 滚动范围与位置提示 ----
  const scrollTop = await page.evaluate(async () => {
    const s = window.__whiteboard.state;
    s.cam.y = 0; s.cam.x = 0;
    const canvas = document.getElementById('board');
    const r = canvas.getBoundingClientRect();
    for (let i = 0; i < 3; i++) {
      canvas.dispatchEvent(new WheelEvent('wheel', { deltaY: -200, bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
    }
    return { camY: s.cam.y, hud: document.getElementById('scrollHud').textContent,
             shown: document.getElementById('scrollHud').classList.contains('show') };
  });
  check('在顶端继续上滑会被挡住', Math.abs(scrollTop.camY) < 1, `cam.y=${scrollTop.camY}`);
  check('提示已达到顶端', /已达到顶端/.test(scrollTop.hud) && scrollTop.shown, scrollTop.hud);

  const scrollMid = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const canvas = document.getElementById('board');
    canvas.dispatchEvent(new WheelEvent('wheel', { deltaY: 900, bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
    return { pos: window.__whiteboard.scrollPos(), hud: document.getElementById('scrollHud').textContent };
  });
  check('滑动时提示当前位置', /当前白板位置/.test(scrollMid.hud) && scrollMid.pos > 0,
    `pos=${scrollMid.pos.toFixed(2)} · ${scrollMid.hud}`);

  const scrollBottom = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.cam.y = -60 * document.getElementById('board').clientHeight;
    const canvas = document.getElementById('board');
    canvas.dispatchEvent(new WheelEvent('wheel', { deltaY: 900, bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
    return { pos: window.__whiteboard.scrollPos(), hud: document.getElementById('scrollHud').textContent };
  });
  check('在底部继续下滑会被挡住', Math.abs(scrollBottom.pos - 50) < 0.05, `pos=${scrollBottom.pos.toFixed(2)}`);
  check('提示已达底端', /已达底端/.test(scrollBottom.hud), scrollBottom.hud);

  // ---- 20. 黑板 / 白板切换 ----
  await page.evaluate(() => { window.__whiteboard.state.cam.y = 0; });
  await page.click('#btnTheme');
  await page.waitForTimeout(200);
  check('点按钮弹出黑白板开关', await page.evaluate(() =>
    document.getElementById('themePop').classList.contains('show')));

  const themeBefore = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    return { theme: s.theme, board: b ? b.color : null,
             paper: getComputedStyle(document.documentElement).getPropertyValue('--paper').trim() };
  });
  await page.click('#themeSwitch');
  await page.waitForTimeout(300);
  const themeAfter = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[s.current].objects.find((o) => o.type === 'board');
    return { theme: s.theme, board: b ? b.color : null,
             paper: getComputedStyle(document.documentElement).getPropertyValue('--paper').trim(),
             bodyBlack: document.body.classList.contains('theme-black') };
  });
  check('开关能切到黑板', themeAfter.theme === 'black' && themeAfter.bodyBlack,
    `${themeBefore.theme} → ${themeAfter.theme}`);
  check('切到黑板后纸张变深', themeAfter.paper !== themeBefore.paper,
    `${themeBefore.paper} → ${themeAfter.paper}`);
  check('小黑板自动变成反色（小白板）',
    themeAfter.board !== themeBefore.board && themeAfter.board.toLowerCase().startsWith('#f'),
    `${themeBefore.board} → ${themeAfter.board}`);

  // 切回白板
  await page.evaluate(() => window.__whiteboard.setTheme('white'));
  await page.waitForTimeout(200);

  // ---- 21. 换纸时笔迹跟着翻色（黑底上不能是黑字）----
  const inkFlip = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const p = s.pages[s.current];
    p.objects = [{ id: 'ink1', type: 'stroke', color: '#1f2937', size: 4,
                   pts: [{ x: 200, y: 200 }, { x: 260, y: 240 }] }];
    s.selection = [];
    window.__whiteboard.setTheme('black');
    const after = p.objects[0].color;
    window.__whiteboard.setTheme('white');
    const back = p.objects[0].color;
    return { after, back };
  });
  const lum = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    return (0.21 * ((n >> 16) & 255) + 0.72 * ((n >> 8) & 255) + 0.07 * (n & 255)) / 255;
  };
  check('切到黑板后深色笔迹翻成浅色（不会看不见）',
    lum(inkFlip.after) > 0.8, `#1f2937 → ${inkFlip.after}`);
  check('切回白板笔迹又翻回深色', lum(inkFlip.back) < 0.35, `${inkFlip.after} → ${inkFlip.back}`);

  // ---- 22. 中英切换 ----
  const en = await page.evaluate(() => {
    window.__whiteboard.setLang('en');
    return {
      tip: document.getElementById('btnPen').title,
      file: document.getElementById('fileTitle').textContent,
      welcome: document.getElementById('welcomeTitle').textContent,
      start: document.getElementById('btnStart').textContent.trim(),
      saved: localStorage.getItem('Language'),
    };
  });
  check('切英文后按钮提示变英文', /Pen/.test(en.tip), en.tip);
  check('切英文后菜单标题变英文', en.file === 'File', en.file);
  check('切英文后欢迎语变英文', /Start your first/.test(en.welcome), en.welcome);
  check('切英文后按钮文字变英文（图标还在）',
    en.start === 'Start writing' &&
    (await page.evaluate(() => !!document.querySelector('#btnPng svg'))), en.start);
  check('语言选择被记住', en.saved === 'en', String(en.saved));

  const zh = await page.evaluate(() => {
    window.__whiteboard.setLang('zh');
    return { file: document.getElementById('fileTitle').textContent,
             start: document.getElementById('btnStart').textContent.trim() };
  });
  check('切回中文也正常', zh.file === '文件' && zh.start === '开始写字', `${zh.file}/${zh.start}`);

  // 右上角那个常驻按钮
  const beforeBtn = await page.evaluate(() => window.__whiteboard.lang());
  await page.click('#langBtn');
  await page.waitForTimeout(200);
  const afterBtn = await page.evaluate(() => ({
    lang: window.__whiteboard.lang(),
    file: document.getElementById('fileTitle').textContent,
    stored: localStorage.getItem('Language'),
  }));
  check('右上角中/EN 按钮能把界面切成英文',
    beforeBtn === 'zh' && afterBtn.lang === 'en' && afterBtn.file === 'File',
    `${beforeBtn} → ${afterBtn.lang} / ${afterBtn.file}`);
  check('语言存在 Language 这个键里', afterBtn.stored === 'en', String(afterBtn.stored));
  await page.click('#langBtn');
  await page.waitForTimeout(150);
  check('再点一下切回中文',
    (await page.evaluate(() => document.getElementById('fileTitle').textContent)) === '文件');

  // ---- 23. 版本更新弹框 ----
  const upd = await page.evaluate(() => {
    window.__whiteboard.showUpdate({ current: '1.0.0', latest: '9.9.9', date: '2026-10-25' });
    return {
      shown: document.getElementById('updateWrap').classList.contains('show'),
      title: document.getElementById('updateTitle').textContent,
      ver: document.getElementById('updateVer').textContent,
      manual: document.getElementById('lnkManual').textContent,
      installer: document.getElementById('lnkInstaller').textContent,
      btns: [document.getElementById('updateLater').textContent,
             document.getElementById('updateNow').textContent],
    };
  });
  check('有新版本时弹出更新框', upd.shown);
  check('更新框写清当前/最新版本',
    /9\.9\.9/.test(upd.title) && /1\.0\.0/.test(upd.ver) && /9\.9\.9/.test(upd.ver),
    `${upd.title} · ${upd.ver}`);
  check('两行兜底链接都在', /手动下载/.test(upd.manual) && /安装器/.test(upd.installer),
    `${upd.manual} | ${upd.installer}`);
  check('有取消和更新两个按钮', upd.btns.join('/') === '以后再说/立即更新', upd.btns.join('/'));
  await page.click('#updateLater');
  check('点以后再说能关掉更新框',
    !(await page.evaluate(() => document.getElementById('updateWrap').classList.contains('show'))));

  // ---- 23.5 小黑板：写在上面的笔画不能溢出板外 ----
  const bd = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.pages[0].objects = [];
    s.cam = { x: 300, y: 200, s: 1 };
    s.pages[0].objects.push({ id: 'bdTest', type: 'board', color: '#20262f',
                              x: 200, y: 120, w: 400, h: 240, opacity: 1 });
    window.__whiteboard.invalidate();
    return { cam: s.cam };
  });
  await page.waitForTimeout(150);
  // 板右边界在屏幕 900px 处，数一条 930~1010 的竖带里有没有墨
  const bandInk = () => page.evaluate(() => {
    const cv = document.getElementById('board');
    const dpr = window.devicePixelRatio || 1;
    const d = cv.getContext('2d').getImageData(Math.round(930 * dpr), Math.round(330 * dpr),
                                               Math.round(80 * dpr), Math.round(220 * dpr)).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 8) n++;
    return n;
  });
  await page.click('[data-tool="pen"]');       // 上一段测的是框选，先切回画笔
  await page.waitForTimeout(100);
  const ink0 = await bandInk();
  const bcx = 200 * bd.cam.s + bd.cam.x + 200;   // 板中心（屏幕）
  const bcy = 120 * bd.cam.s + bd.cam.y + 120;
  await page.mouse.move(bcx, bcy);
  await page.mouse.down();
  for (let i = 1; i <= 18; i++) await page.mouse.move(bcx + i * 18, bcy);
  await page.waitForTimeout(120);
  const inkDrawing = await bandInk();
  await page.mouse.up();
  await page.waitForTimeout(160);
  const inkDone = await bandInk();
  check('画在小黑板上的笔画不会溢出到板外（拖动过程中）', inkDrawing === ink0,
    `板外像素 ${ink0} → ${inkDrawing}`);
  check('落笔后也裁在板面内', inkDone === ink0, `板外像素 ${ink0} → ${inkDone}`);

  // ---- 23.6 全部清除：橡皮点两次，滑到底 ----
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.pages[0].objects.push({ id: 'x1', type: 'line', color: '#1f2937', width: 4,
                              x1: 100, y1: 600, x2: 300, y2: 700 });
    s.pages.push({ id: 'pg2', objects: [{ id: 'x2', type: 'line', color: '#1f2937', width: 4,
                                          x1: 100, y1: 100, x2: 300, y2: 200 }] });
    window.__whiteboard.invalidate();
  });
  await page.click('[data-tool="eraser"]');
  await page.waitForTimeout(120);
  const eraseShut = await page.evaluate(() =>
    document.getElementById('eraserPop').classList.contains('show'));
  check('第一次点橡皮只切工具，不弹面板', !eraseShut);

  await page.click('[data-tool="eraser"]');
  await page.waitForTimeout(200);
  const eraseOpen = await page.evaluate(() => ({
    show: document.getElementById('eraserPop').classList.contains('show'),
    title: document.getElementById('eraseTitle').textContent,
    hint: document.getElementById('eraseHint').textContent,
  }));
  check('再点一次橡皮弹出「全部清除」滑条',
    eraseOpen.show && /全部清除/.test(eraseOpen.title) && /滑动/.test(eraseOpen.hint),
    `${eraseOpen.title} / ${eraseOpen.hint}`);

  const kn = await page.locator('#eraseKnob').boundingBox();
  const tr = await page.locator('#eraseTrack').boundingBox();
  await page.mouse.move(kn.x + kn.width / 2, kn.y + kn.height / 2);
  await page.mouse.down();
  await page.mouse.move(tr.x + tr.width * 0.5, kn.y + kn.height / 2, { steps: 4 });
  await page.mouse.up();
  await page.waitForTimeout(250);
  const halfWay = await page.evaluate(() => window.__whiteboard.state.pages
    .reduce((n, p) => n + p.objects.length, 0));
  check('滑到一半松手不清空', halfWay > 0, `还剩 ${halfWay} 个对象`);
  const pre = await page.evaluate(() => ({
    pages: window.__whiteboard.state.pages.length,
    objs: window.__whiteboard.state.pages.reduce((n, p) => n + p.objects.length, 0),
  }));

  await page.mouse.move(kn.x + kn.width / 2, kn.y + kn.height / 2);
  await page.mouse.down();
  await page.mouse.move(tr.x + tr.width - 4, kn.y + kn.height / 2, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(350);
  const wiped = await page.evaluate(() => ({
    objs: window.__whiteboard.state.pages.reduce((n, p) => n + p.objects.length, 0),
    pages: window.__whiteboard.state.pages.length,
    undo: !document.getElementById('btnUndo').disabled,
  }));
  check('滑到底清空所有页的板书', wiped.objs === 0 && wiped.pages === 1,
    `${wiped.pages} 页 / ${wiped.objs} 个对象`);
  check('清空之后能撤销', wiped.undo);

  await page.click('#btnUndo');
  await page.waitForTimeout(250);
  const back = await page.evaluate(() => ({
    pages: window.__whiteboard.state.pages.length,
    objs: window.__whiteboard.state.pages.reduce((n, p) => n + p.objects.length, 0),
  }));
  check('撤销把页面和笔画都还回来',
    back.pages === pre.pages && back.objs === pre.objs,
    `清空前 ${pre.pages} 页 ${pre.objs} 个 → 撤销后 ${back.pages} 页 ${back.objs} 个`);

  // ---- 23.7 分享：整块板书拼成一张长图 ----
  await page.click('#btnShare');
  await page.waitForTimeout(900);
  const sh = await page.evaluate(() => {
    const img = document.getElementById('shareImg');
    return {
      show: document.getElementById('shareWrap').classList.contains('show'),
      w: img.naturalWidth,
      h: img.naturalHeight,
      meta: document.getElementById('shareMeta').textContent,
      btns: [...document.querySelectorAll('#shareActs button')].map((b) => b.textContent.trim()),
    };
  });
  check('点分享弹出预览窗', sh.show);
  check('长截图按板书内容生成（够宽够长）', sh.w >= 1000 && sh.h >= 300,
    `${sh.w} × ${sh.h}`);
  check('预览窗写明尺寸和页数', /像素|px/.test(sh.meta) && /页|page/.test(sh.meta), sh.meta);
  check('有三个按钮：关闭 / 再复制一次 / 保存到本地',
    sh.btns.length === 3 && sh.btns[2] === '保存到本地', sh.btns.join(' | '));
  await page.click('#shareClose');
  await page.waitForTimeout(200);
  check('关掉预览窗',
    !(await page.evaluate(() => document.getElementById('shareWrap').classList.contains('show'))));

  // ---- 截图留档（趁板面上还有东西）----
  const shot = path.join(__dirname, '_uitest.png');
  await page.screenshot({ path: shot });

  // ---- 24. 每次打开都是空板 ----
  // 假装上一轮写过内容（旧版快照），再刷新：应该一点不剩
  await page.evaluate(() => {
    localStorage.setItem('whiteboard.theme', 'black');
    localStorage.setItem('whiteboard.v2', JSON.stringify({
      current: 1,
      theme: 'black',
      pages: [
        { id: 'old1', objects: [{ id: 'o1', type: 'stroke', color: '#111111', size: 4,
                                  pts: [{ x: 10, y: 10 }, { x: 80, y: 60 }] }] },
        { id: 'old2', objects: [{ id: 'o2', type: 'stroke', color: '#111111', size: 4,
                                  pts: [{ x: 20, y: 20 }, { x: 90, y: 70 }] }] },
      ],
    }));
  });
  await page.reload();
  await page.waitForTimeout(600);
  const blank = await page.evaluate(() => {
    const s = window.__whiteboard.state;
    return {
      objs: s.pages.reduce((n, p) => n + p.objects.length, 0),
      pages: s.pages.length,
      current: s.current,
      snapshot: localStorage.getItem('whiteboard.v2'),
      theme: s.theme,
    };
  });
  check('重开时上一轮写的内容被清空',
    blank.objs === 0 && blank.snapshot === null, `objects=${blank.objs} snapshot=${blank.snapshot}`);
  check('多页也收回成一页空白', blank.pages === 1 && blank.current === 0,
    `${blank.pages} 页 / 当前第 ${blank.current} 页`);
  check('主题这种偏好还留着（上次是黑板）', blank.theme === 'black', blank.theme);

  // 开场提示只出现一次：点过「开始写字」之后再开就直接进空画板
  await page.evaluate(() => localStorage.removeItem('whiteboard.seen'));
  await page.reload();
  await page.waitForTimeout(500);
  const w1 = await page.evaluate(() =>
    !document.getElementById('welcome').classList.contains('hide'));
  await page.click('#btnStart');
  await page.waitForTimeout(200);
  await page.reload();
  await page.waitForTimeout(500);
  const w2 = await page.evaluate(() => ({
    hidden: document.getElementById('welcome').classList.contains('hide'),
    objs: window.__whiteboard.state.pages.reduce((n, p) => n + p.objects.length, 0),
  }));
  check('开场提示只在第一次出现', w1 && w2.hidden, `第一次显示=${w1} 之后隐藏=${w2.hidden}`);
  check('再开一次依然是空板', w2.objs === 0, `objects=${w2.objs}`);

  // ---- 24.5 选择方式：框选 / 点选 ----
  await page.evaluate(() => localStorage.removeItem('whiteboard.selmode'));
  await page.reload();
  await page.waitForTimeout(500);

  // 画一笔横线，方便后面点中
  const bb = await page.locator('#board').boundingBox();
  const ex = bb.x + bb.width / 2, ey = bb.y + bb.height / 2;
  await page.mouse.move(ex - 200, ey);
  await page.mouse.down();
  for (let i = 1; i <= 20; i++) await page.mouse.move(ex - 200 + i * 20, ey);
  await page.mouse.up();
  await page.waitForTimeout(200);

  await page.keyboard.press('v');
  await page.waitForTimeout(150);
  await page.click('#btnSelect');
  await page.waitForTimeout(250);
  const selPop = () => page.evaluate(() =>
    document.getElementById('selectPop').classList.contains('show'));
  check('再点一次选择图标弹出「选择方式」', await selPop());

  const modeNow = () => page.evaluate(() => window.__whiteboard.state.selMode);
  check('默认是框选', (await modeNow()) === 'marquee', await modeNow());
  check('框选项高亮',
    await page.evaluate(() =>
      document.querySelector('#selectPop [data-selmode="marquee"]').classList.contains('on')));
  check('开关在左侧（框选）',
    (await page.evaluate(() =>
      document.getElementById('selSwitch').classList.contains('on'))) === false);

  // 框选：拖一个矩形，应该选中框里的笔画
  await page.click('#board', { position: { x: 20, y: 20 } });
  await page.mouse.move(ex - 260, ey - 100);
  await page.mouse.down();
  await page.mouse.move(ex + 260, ey + 100, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(250);
  const marqueeSel = await page.evaluate(() => window.__whiteboard.state.selection.length);
  check('框选能一次选中框里的对象', marqueeSel >= 1, String(marqueeSel));

  // 切到点选
  await page.click('#btnSelect');
  await page.waitForTimeout(200);
  await page.click('#selectPop [data-selmode="free"]');
  await page.waitForTimeout(250);
  check('能切到点选', (await modeNow()) === 'free', await modeNow());
  check('开关滑到右侧（点选）',
    await page.evaluate(() => document.getElementById('selSwitch').classList.contains('on')));
  check('切换后面板不关（和纸张开关一样）',
    await page.evaluate(() => document.getElementById('selectPop').classList.contains('show')));
  check('点选标签高亮',
    await page.evaluate(() =>
      document.querySelector('#selectPop [data-selmode="free"]').classList.contains('on')));
  check('点选记在 localStorage',
    (await page.evaluate(() => localStorage.getItem('whiteboard.selmode'))) === 'free');
  check('选择图标上有标记',
    (await page.evaluate(() => document.getElementById('btnSelect').dataset.mode)) === 'free');
  check('画布切到箭头光标',
    await page.evaluate(() => document.getElementById('board').classList.contains('is-free-select')));

  // 点选：点一下那条线就选中它
  await page.click('#board', { position: { x: 20, y: 20 } });   // 先取消选择
  await page.waitForTimeout(150);
  await page.mouse.click(ex, ey);
  await page.waitForTimeout(250);
  const one = await page.evaluate(() => window.__whiteboard.state.selection.length);
  check('点选：点中线条就选中它', one === 1, String(one));

  // 点选模式下拖空白不拉框
  await page.mouse.move(ex - 300, ey - 160);
  await page.mouse.down();
  await page.mouse.move(ex - 200, ey - 60, { steps: 8 });
  const midMarquee = await page.evaluate(() => window.__whiteboard.state.marquee);
  await page.mouse.up();
  await page.waitForTimeout(150);
  check('点选模式拖空白不拉框', midMarquee === null, JSON.stringify(midMarquee));

  // ---- 24.6 改颜色 ----
  await page.mouse.click(ex, ey);
  await page.waitForTimeout(200);
  check('选中非文字对象也显示「颜色」按钮',
    await page.evaluate(() =>
      document.getElementById('sbColor').style.display !== 'none'));

  await page.click('#sbColor');
  await page.waitForTimeout(300);
  const cpShown = () => page.evaluate(() =>
    document.getElementById('colorPop').classList.contains('show'));
  check('点「颜色」弹出取色面板', await cpShown());
  check('面板里有常用色', (await page.locator('#cpGrid .cp-dot').count()) >= 12,
    String(await page.locator('#cpGrid .cp-dot').count()));
  check('面板里有大色块', (await page.locator('#cpSVC').count()) === 1);
  check('面板里有色相条', (await page.locator('#cpHue').count()) === 1);
  check('面板里有 RGB 三个框',
    (await page.locator('#cpR').count()) + (await page.locator('#cpG').count())
    + (await page.locator('#cpB').count()) === 3);
  check('面板里有吸管按钮', (await page.locator('#cpPick').count()) === 1);

  // 从对象本身读颜色：撤销会把选中的引用清掉，读 selection 会拿到 undefined
  const colorOf = () => page.evaluate(() => {
    const o = window.__whiteboard.state.pages[0].objects[0];
    return o ? o.color : null;
  });

  await page.click('#cpGrid .cp-dot:nth-child(2)');
  await page.waitForTimeout(250);
  check('点常用色能改颜色', (await colorOf()) === '#ef4444', await colorOf());

  await page.locator('#cpHex').fill('#123456');
  await page.locator('#cpHex').dispatchEvent('change');
  await page.waitForTimeout(250);
  check('填 hex 能改颜色', (await colorOf()) === '#123456', await colorOf());

  await page.locator('#cpR').fill('200');
  await page.locator('#cpR').dispatchEvent('change');
  await page.waitForTimeout(250);
  const afterRgb = await colorOf();
  check('填 RGB 能改颜色', afterRgb.startsWith('#c8'), afterRgb);

  const hueBox = await page.locator('#cpHue').boundingBox();
  await page.mouse.click(hueBox.x + hueBox.width * 0.75, hueBox.y + hueBox.height / 2);
  await page.waitForTimeout(250);
  const afterHue = await colorOf();
  check('拖色相条能改颜色', afterHue !== afterRgb, `${afterRgb} → ${afterHue}`);

  const svBox = await page.locator('#cpSV').boundingBox();
  await page.mouse.move(svBox.x + 20, svBox.y + 20);
  await page.mouse.down();
  await page.mouse.move(svBox.x + svBox.width * 0.8, svBox.y + svBox.height * 0.7, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(250);
  const afterSV = await colorOf();
  check('拖大色块能改颜色', afterSV !== afterHue, `${afterHue} → ${afterSV}`);

  await page.keyboard.press('Control+z');
  await page.waitForTimeout(250);
  check('改色能撤销', (await colorOf()) !== afterSV, await colorOf());

  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);
  check('Esc 能关掉取色面板', !(await cpShown()));

  // ---- 25. 报错 ----
  check('运行期无 JS 报错', errors.length === 0, errors.slice(0, 4).join(' | '));

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
