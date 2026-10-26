/** 用线上真实的 Release 正文，截一张更新弹窗的图，确认更新内容显示正常。 */
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { chromium } = require('playwright-core');

const HTML = pathToFileURL(path.join(__dirname, '..', 'ui', 'index.html')).href;
const CACHE = 'C:/Users/Liuyi/CleanBlackboard/update.json';

async function main() {
  const info = JSON.parse(fs.readFileSync(CACHE, 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1000, height: 720 }, deviceScaleFactor: 2 });
  await page.goto(HTML);
  await page.waitForTimeout(400);
  await page.click('#langCard [data-lang="zh"]');
  await page.waitForTimeout(300);

  await page.evaluate((i) => {
    window.__whiteboard.showUpdate({
      current: '1.2.0', latest: i.version, date: i.date, notes: i.notes,
    });
  }, info);
  await page.waitForTimeout(400);
  const card = await page.locator('#updateCard').boundingBox();
  await page.screenshot({
    path: path.join(__dirname, 'shot_update_notes.png'),
    clip: { x: card.x - 16, y: card.y - 16, width: card.width + 32, height: card.height + 32 },
  });
  console.log('note text:\n' + (await page.evaluate(() => document.getElementById('updateNote').textContent)));
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
