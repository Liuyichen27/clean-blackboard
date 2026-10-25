const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');
const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(HTML);
  await page.waitForTimeout(400);
  await page.click('#btnStart');
  await page.waitForTimeout(200);

  // 画几笔 + 插小黑板 + 在板子上写字
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.pages[0].objects.push(
      { id: 'p1', type: 'path', color: '#1f2937', width: 4, opacity: 1,
        points: [{x:220,y:220},{x:300,y:260},{x:380,y:200},{x:470,y:250}] },
      { id: 'p2', type: 'path', color: '#2f6bff', width: 4, opacity: 1,
        points: [{x:230,y:320},{x:330,y:330},{x:430,y:310}] });
    window.__whiteboard.invalidate();
  });
  await page.click('#btnBoard');
  await page.waitForTimeout(300);
  // 在板面上写一笔
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    const b = s.pages[0].objects.find(o => o.type === 'board');
    const cx = (b.x + b.w / 2) * s.cam.s + s.cam.x;
    const cy = (b.y + b.h / 2) * s.cam.s + s.cam.y;
    window.__p = { cx, cy };
  });
  const p = await page.evaluate(() => window.__p);
  await page.mouse.move(p.cx - 120, p.cy - 20);
  await page.mouse.down();
  for (let i = 1; i <= 10; i++) await page.mouse.move(p.cx - 120 + i * 24, p.cy - 20 + Math.sin(i) * 14);
  await page.mouse.up();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(__dirname, 'shot-white.png') });

  // 悬停主题按钮看开关
  await page.click('#btnTheme');
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(__dirname, 'shot-switch.png') });

  // 切黑板
  await page.click('#themeSwitch');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(__dirname, 'shot-black.png') });

  await browser.close();
  console.log('done');
})();
