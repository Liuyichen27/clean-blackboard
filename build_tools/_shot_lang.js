/** 截图留档：语言选择框 / 英文界面 / 黑板模式下的笔迹与位置读数。 */
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');

const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;
const shot = (n) => path.join(__dirname, n);

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(HTML);
  await page.waitForTimeout(450);

  await page.screenshot({ path: shot('shot-lang.png') });

  await page.click('#langCard [data-lang="zh"]');
  await page.waitForTimeout(200);

  // 白纸上写两笔，再用英文界面截一张
  await page.evaluate(() => {
    const s = window.__whiteboard.state;
    s.pages[0].objects.push(
      { id: 'p1', type: 'path', color: '#1f2937', width: 4, opacity: 1,
        points: [{ x: 220, y: 220 }, { x: 300, y: 260 }, { x: 380, y: 200 }, { x: 470, y: 250 }] });
    window.__whiteboard.invalidate();
  });
  await page.click('#btnStart');
  await page.evaluate(() => window.__whiteboard.setLang('en'));
  await page.waitForTimeout(300);
  await page.click('#btnFiles');
  await page.waitForTimeout(250);
  await page.screenshot({ path: shot('shot-en.png') });
  await page.keyboard.press('Escape');

  // 切黑板：原来的深色笔迹应该翻成浅色
  await page.evaluate(() => {
    window.__whiteboard.setLang('zh');
    window.__whiteboard.setTheme('black');
  });
  await page.waitForTimeout(400);
  await page.screenshot({ path: shot('shot-black2.png') });

  await browser.close();
  console.log('done');
})();
