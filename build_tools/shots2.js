/** 截两张图：选择方式滑动开关、画笔面板吸管。 */
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');

const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;
const OUT = __dirname;

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1100, height: 760 }, deviceScaleFactor: 2 });
  await page.goto(HTML);
  await page.waitForTimeout(400);
  await page.click('#langCard [data-lang="zh"]');
  await page.waitForTimeout(300);

  // 画一笔，让画面不空
  const bb = await page.locator('#board').boundingBox();
  const cx = bb.x + bb.width / 2, cy = bb.y + bb.height / 2;
  await page.mouse.move(cx - 220, cy - 40);
  await page.mouse.down();
  for (let i = 1; i <= 24; i++) {
    await page.mouse.move(cx - 220 + i * 18, cy - 40 + Math.sin(i / 3) * 26);
  }
  await page.mouse.up();

  // 1. 选择方式面板
  await page.keyboard.press('v');
  await page.waitForTimeout(200);
  await page.click('#btnSelect');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, 'shot_selmode_marquee.png') });

  // 切到点选，看开关滑过去
  await page.click('#selectPop [data-selmode="free"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, 'shot_selmode_free.png') });

  // 2. 画笔面板（含吸管按钮）
  await page.keyboard.press('Escape');
  await page.keyboard.press('p');
  await page.waitForTimeout(150);
  await page.click('#btnPen');
  await page.waitForTimeout(450);
  const penBox = await page.locator('#penPop').boundingBox();
  await page.screenshot({
    path: path.join(OUT, 'shot_pen_eyedropper.png'),
    clip: { x: penBox.x - 12, y: penBox.y - 12, width: penBox.width + 24, height: penBox.height + 24 },
  });
  console.log('done');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
