# 白板 · Whiteboard

[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org)
[![License](https://img.shields.io/badge/license-MIT-12B76A)](LICENSE)
[![Size](https://img.shields.io/badge/exe-14%20MB-2F6BFF)](#)

双击打开就能写的白板。不用注册、不用登录、不联网。

![界面](assets/shot-canvas.png)

<sub>右边那条 56 px 的细条就是全部工具栏；框选之后浮出的工具条可以置顶、锁定、改字号颜色。</sub>

## 为什么又做一个白板

市面上的白板要么绑账号绑云端，要么打开先弹一个登录框；好不容易进去，写两笔就卡成幻灯片。

这个白板的目标很朴素：**点开 <kbd>白板.exe</kbd>，0.5 秒后就能写字。** 没有启动页、没有账号、没有云同步。文件留在你自己的硬盘上。

## 上手

| 想做的事 | 怎么做 |
| --- | --- |
| 写字 | 直接按住鼠标拖；按 <kbd>P</kbd> 切回画笔 |
| 换颜色、粗细、笔型 | **再点一次画笔图标**，弹出小窗（笔 / 荧光笔 / 书法笔） |
| 框选一批东西 | 按 <kbd>V</kbd>，在空白处拖出选框 |
| 改选中的东西 | 选中后浮出工具条：置顶 / 克隆 / 锁定 / 字号 / 颜色 / 删除 |
| 移动位置 | 拖它本身；右上角小方块可以缩放 |
| 加图片 | 直接把图片**拖进窗口**，或 <kbd>Ctrl</kbd>+<kbd>V</kbd> 粘贴 |
| 插一块小黑板 | 点侧边栏的小黑板图标，在上面写字自动变白 |
| 存下来 | <kbd>Ctrl</kbd>+<kbd>S</kbd> 存工程（`.wbjson`），<kbd>Ctrl</kbd>+<kbd>E</kbd> 导出 PNG |
| 打开 | <kbd>Ctrl</kbd>+<kbd>O</kbd>，或把 `.wbjson` **拖到 exe 图标上** |

侧边栏是右边一条 56 px 的细条，按 <kbd>Tab</kbd> 收起，给画布让出整块地方。

## 快捷键

| 键 | 作用 |
| --- | --- |
| <kbd>P</kbd> / <kbd>E</kbd> / <kbd>V</kbd> / <kbd>T</kbd> | 画笔 / 橡皮 / 选择 / 文字 |
| <kbd>1</kbd>~<kbd>4</kbd> | 粗细 |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> | 撤销 / 重做 |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | 克隆选中 |
| <kbd>Delete</kbd> | 删除选中 |
| <kbd>Ctrl</kbd>+<kbd>滚轮</kbd> | 缩放画布 |
| <kbd>空格</kbd>+拖 | 平移画布 |
| <kbd>Tab</kbd> | 收起 / 展开侧边栏 |

## 关于「未响应」

之前那版一写长笔画就会白屏卡住几秒，Windows 直接打上"未响应"。原因和修法：

1. **每帧重画全部内容** —— 1000 个对象，每帧都要重算 1000 遍。改成两块画布：已完成的内容画进离屏缓存（`cache` canvas），每帧只 `drawImage` 贴一次，只有正在写的那一笔是实时画的。
2. **每个点都单独 `stroke()`** —— 一笔 600 个点就是 600 次绘制调用，GPU 直接被拖死。改成按笔宽分组建路径，一次 `stroke()` 画完整笔。
3. **每个 pointermove 都直接重绘** —— 高刷屏一秒来 240 个事件，重绘次数是帧率的几倍。改成 `requestAnimationFrame` 合并，一帧最多画一次。

实测（1440×900，Edge 内核）：600 点长笔画两帧内画完，约 **7 ms**，空闲帧率 **240 fps**。自检脚本 `build_tools/uitest.js` 里第 14、15 项就是在量这个。

## 数据在哪

全部在本地：

- `%APPDATA%\WhiteboardDesktop\webview\` —— 自动保存的草稿（关掉再开还在）
- 你自己存的 `.wbjson` —— 就是 JSON，可以用文本编辑器打开，也可以写脚本批量生成

不联网、不上传、不需要账号。删掉这个目录就等于清空所有痕迹。

## 从源码跑

```bash
pip install pywebview pillow
python main.py
```

需要 Windows 10/11 自带的 WebView2 运行时（一般都有；没有的话去微软官网装一个）。

## 打包成 exe

```bash
pip install pyinstaller
python build_tools/build.py
# 产物：dist/白板.exe（单文件，约 14 MB）
```

打包完建议跑一遍两个自检：

```bash
python build_tools/smoke.py dist/白板.exe   # 能否开、会不会假死、界面画出来没有
node   build_tools/uitest.js                # 画笔/框选/工具条/小黑板/存档/导出 PNG
```

`uitest.js` 用真实 Edge 内核跑 27 项断言，exe 里装的就是同一份 `index.html`，所以过了这套就等于过了桌面版。

## 工程结构

```
whiteboard/
├─ main.py                原生外壳：窗口、DPI、文件对话框、崩溃日志
├─ ui/index.html          整个界面（HTML + CSS + Canvas，单文件）
├─ assets/                图标
└─ build_tools/
   ├─ build.py            PyInstaller 打包
   ├─ smoke.py            启动自检（窗口是否假死、是否白屏）
   ├─ uitest.js           交互自检（27 项）
   └─ checkjs.js          页面脚本语法检查
```

界面刻意做成单文件：没有构建步骤、没有 npm、没有依赖，改完存盘刷新就见效。

## 已知边界

- 只支持 Windows（WebView2 + PyInstaller 打包）
- 手写压感：支持 Windows Ink 笔（Surface / 数位板），鼠标只有固定粗细
- 对象数量上到几千个时拖动会开始变慢（离屏缓存失效，需要全量重画）
- 没有多人协作、没有云同步，这不是遗漏，是取舍

## 许可

MIT License，详见 [LICENSE](LICENSE)。

---

<sub>English: A desktop whiteboard for Windows that opens straight into a canvas — no account, no sign-in, no network. Built with pywebview (WebView2) and a single-file HTML/CSS/Canvas UI, packaged as a 14 MB single executable. Supports pen/highlighter/brush, free marquee selection with a floating toolbar (bring to front, lock, font size, color, delete), drag-and-drop images, an embedded mini blackboard, multi-page, undo/redo, `.wbjson` project files and PNG export. Rendering uses an offscreen cache layer plus stroke-path batching, which keeps long strokes at ~7 ms per frame.</sub>
