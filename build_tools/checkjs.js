// 打包前的界面自检：页面里的脚本能不能被 JS 引擎解析。
// 用法：node build_tools/checkjs.js
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', 'ui', 'index.html');
const html = fs.readFileSync(file, 'utf8');
const re = /<script\b[^>]*>([\s\S]*?)<\/script>/gi;

let m;
let i = 0;
let bad = 0;
while ((m = re.exec(html))) {
  const src = m[1];
  if (!src.trim()) continue;
  i += 1;
  try {
    new Function(src);
    console.log(`script #${i} OK (${src.length} chars)`);
  } catch (e) {
    bad += 1;
    console.log(`script #${i} SYNTAX ERROR: ${e.message}`);
  }
}
console.log(bad ? 'FAIL' : 'ALL OK');
process.exit(bad ? 1 : 0);
