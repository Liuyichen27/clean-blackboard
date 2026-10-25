"""接口自检：守住「启动即假死」那个坑。

pywebview 会把 js_api 对象的**公开成员**递归翻译成 JS 接口（没有环检测）。
只要 Api 上挂了一个公开属性（比如 window），它就会顺着走进 pythonnet 的
.NET 对象图，永远遍历不完 —— 主线程卡死，窗口被判「未响应」。
老版本就是这么挂的，所以这里把约束固化成测试。

跑法：python build_tools/apitest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import PNG_FILTERS, PROJECT_FILTERS, Api  # noqa: E402

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'✓' if ok else '✗'} {name}{'  — ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


def main() -> int:
    api = Api()
    public = [n for n in dir(api) if not n.startswith("_")]

    not_callable = [n for n in public if not callable(getattr(api, n, None))]
    check("Api 不暴露任何非方法的公开成员", not not_callable,
          f"违规成员：{not_callable}" if not_callable else f"公开成员 {len(public)} 个，全是方法")

    # dir() 是 pywebview 实际遍历的入口，这里直接看它给什么
    listed = dir(api)
    leaked = [n for n in listed if not n.startswith("_")
              and not callable(getattr(api, n, None))]
    check("dir(api) 里没有会引发递归的属性", not leaked, str(leaked))

    check("Api 内部持有窗口的引用是私有的", hasattr(api, "_window") and not hasattr(api, "window"),
          "_window 私有，无公开 window")

    check("工程文件过滤器是字符串元组",
          isinstance(PROJECT_FILTERS, tuple)
          and all(isinstance(x, str) for x in PROJECT_FILTERS)
          and all("(" in x for x in PROJECT_FILTERS),
          str(PROJECT_FILTERS))

    check("PNG 过滤器是字符串元组",
          isinstance(PNG_FILTERS, tuple) and all(isinstance(x, str) for x in PNG_FILTERS),
          str(PNG_FILTERS))

    # 页面会调用的方法都得在
    for name in ("save_project", "open_project", "save_png", "app_info", "quit", "diag"):
        check(f"页面可调用 {name}()", callable(getattr(api, name, None)))

    # ---- 读写往返：把对话框短路掉，直接验落盘逻辑 ----
    import base64
    import json
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="wb_api_"))
    target = tmpdir / "t.wbjson"
    api._ask_save_path = lambda *a, **k: str(target)      # type: ignore[method-assign]
    api._ask_open_path = lambda *a, **k: str(target)      # type: ignore[method-assign]

    payload = {"app": "whiteboard", "version": 2,
               "pages": [{"id": "p1", "objects": [{"id": "a", "type": "text",
                                                   "x": 1, "y": 2, "size": 20, "text": "你好"}]}]}
    r = api.save_project(json.dumps(payload, ensure_ascii=False), "x.wbjson")
    check("save_project 能落盘", bool(r.get("ok")) and target.exists(), str(r))

    check("落盘内容能读回", target.exists()
          and json.loads(target.read_text(encoding="utf-8"))["pages"][0]["objects"][0]["text"] == "你好")

    r = api.open_project()
    check("open_project 能读回内容", bool(r.get("ok")) and "你好" in r.get("content", ""),
          str({k: v for k, v in r.items() if k != "content"}))

    r = api.save_project("{这不是 JSON", "bad.wbjson")
    check("坏 JSON 被拒绝且不写文件", r.get("ok") is False and not (tmpdir / "bad.wbjson").exists(),
          r.get("error", ""))

    api._ask_save_path = lambda *a, **k: None            # type: ignore[method-assign]
    r = api.save_project("{}", "x.wbjson")
    check("取消保存返回 cancel", r.get("ok") is False and r.get("cancel") is True, str(r))

    png = tmpdir / "t.png"
    api._ask_save_path = lambda *a, **k: str(png)         # type: ignore[method-assign]
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = api.save_png("data:image/png;base64," + base64.b64encode(raw).decode(), "t.png")
    check("save_png 能写出图片", bool(r.get("ok")) and png.exists() and png.read_bytes() == raw, str(r))

    r = api.save_png("data:image/jpeg;base64,AAAA", "t.png")
    check("非 PNG 数据被拒绝", r.get("ok") is False, r.get("error", ""))

    print(f"\n{'全部通过' if not fails else '未通过：' + '、'.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
