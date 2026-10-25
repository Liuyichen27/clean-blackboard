/** 给新加的两块面板拍照：滑动清空（白/黑）、分享窗（黑）。 */
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');
const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
  await page.goto(HTML);
  await page.waitForTimeout(400);
  await page.click('#langCard [data-lang="zh"]');
  await page.click('#btnStart');

  // 画点东西，免得预览是白板
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.pages[0].objects = [
      { id: 't1', type: 'text', x: 160, y: 150, size: 64, color: '#1f2937',
        text: '把字写在小黑板上' },
      { id: 'bd', type: 'board', x: 160, y: 260, w: 620, h: 300, color: '#20262f', opacity: 1 },
      { id: 'p1', type: 'path', penType: 'pen', owner: 'bd', color: '#ffffff', width: 6,
        opacity: 1, points: [{ x: 240, y: 320 }, { x: 300, y: 470 }, { x: 420, y: 380 }] },
    ];
    window.__whiteboard.invalidate();
  });
  await page.waitForTimeout(300);

  // 橡皮 -> 再点一次
  await page.click('[data-tool="eraser"]');
  await page.click('[data-tool="eraser"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(__dirname, '_shot_erase.png') });

  // 滑到 60% 看看进度条
  const kb = await page.locator('#eraseKnob').boundingBox();
  const tb = await page.locator('#eraseTrack').boundingBox();
  await page.mouse.move(kb.x + kb.width / 2, kb.y + kb.height / 2);
  await page.mouse.down();
  await page.mouse.move(tb.x + tb.width * 0.62, kb.y + kb.height / 2, { steps: 6 });
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(__dirname, '_shot_erase_half.png') });
  await page.mouse.up();

  // 黑板上再来一次
  await page.evaluate(() => window.__whiteboard.setTheme('black'));
  await page.waitForTimeout(200);
  await page.click('[data-tool="eraser"]');
  await page.click('[data-tool="eraser"]');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(__dirname, '_shot_erase_black.png') });

  // 分享（黑纸）
  await page.click('#btnShare');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(__dirname, '_shot_share_black.png') });

  await browser.close();
  console.log('done');
})().catch((e) => { console.error(e); process.exit(2); });
