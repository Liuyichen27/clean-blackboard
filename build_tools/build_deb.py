"""把简黑板打成 Debian / Ubuntu 可安装的 .deb。

为什么不是 PyInstaller 单文件
------------------------------
PyInstaller 不能交叉编译：在 Windows 上跑不出一份 Linux 可执行文件，而
这台机器没有 Linux 环境（WSL 只装了壳，没装发行版）。所以这里做成
`Architecture: all` 的**源码包 + 系统 python3**：deb 里放 Python 源码和
界面资源，运行时用系统的 python3 + python3-webview（WebKitGTK）跑。
好处是不绑架构、不绑发行版，坏处是依赖得由 apt 装（control 里写清楚了）。

产物
----
    dist/cleanblackboard_<版本>_all.deb

顺带做完整性自检：重新把 deb 读一遍，校验 ar 结构、control 字段、
data.tar.gz 里的文件清单和权限。

用法
----
    python build_tools/build_deb.py
"""

from __future__ import annotations

import gzip
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

PKG = "cleanblackboard"
APP_DIR = "/usr/lib/cleanblackboard"
DESKTOP = "cleanblackboard.desktop"
MAINTAINER = "Liuyichen27 <Liuyichen27@users.noreply.github.com>"
HOMEPAGE = "https://github.com/Liuyichen27/clean-blackboard"

# 依赖说明：
# * python3-webview   —— Debian 12+ / Ubuntu 22.04+ 都有，提供 import webview
# * gir1.2-webkit2-4.x —— pywebview 的 GTK 后端真正干活的 WebKitGTK
# * xclip / wl-clipboard 不是硬依赖：装了才能把分享长图一键进剪贴板，
#   没装只是退化成「另存为 PNG」，所以放 Recommends。
DEPENDS = (
    "python3 (>= 3.9), "
    "python3-webview (>= 3.0) | python3-pip, "
    "gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0 | gir1.2-webkit2-3.0, "
    "python3-gi"
)
# 中文字体是必需的：没有 CJK 字体会整屏方块，不是「可选优化」
RECOMMENDS = "fonts-noto-cjk, xclip | wl-clipboard"
SUGGESTS = "fonts-noto-cjk-extra"

ICON_SIZES = (512, 256, 128, 64, 48, 32)

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=CleanBlackboard
Name[zh_CN]=简黑板
GenericName=Whiteboard
GenericName[zh_CN]=白板
Comment=Double-click and write. Offline, no account.
Comment[zh_CN]=双击就能写的白板，不联网、无账号
Exec=cleanblackboard %f
Icon=cleanblackboard
Terminal=false
Categories=Graphics;Office;Education;
Keywords=whiteboard;draw;paint;teaching;annotation;
Keywords[zh_CN]=白板;手写;画板;教学;批注;
MimeType=application/x-cleanblackboard;
StartupWMClass=CleanBlackboard
StartupNotify=true
"""

LAUNCHER = """#!/bin/sh
# CleanBlackboard 启动器：真正的内容在 /usr/lib/cleanblackboard
set -e
APP_DIR=/usr/lib/cleanblackboard

if [ ! -f "$APP_DIR/main.py" ]; then
    echo "找不到 $APP_DIR/main.py，安装可能不完整，请重新安装：" >&2
    echo "  sudo apt install --reinstall ./cleanblackboard_*.deb" >&2
    exit 1
fi

if ! python3 -c "import webview" >/dev/null 2>&1; then
    echo "简黑板需要 python3-webview（WebKitGTK 后端），现在没装：" >&2
    echo "  sudo apt install python3-webview gir1.2-webkit2-4.1" >&2
    echo "装完再运行 cleanblackboard。" >&2
    exit 1
fi

exec python3 "$APP_DIR/main.py" "$@"
"""

POSTINST = """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi
exit 0
"""

POSTRM = """#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
# 用户数据（~/.local/share/CleanBlackboard）不动，卸载不该带走草稿
exit 0
"""


def read_version() -> str:
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("main.py 里找不到 VERSION")
    return m.group(1)


def control_text(ver: str, installed_kb: int) -> str:
    return f"""Package: {PKG}
Version: {ver}
Section: graphics
Priority: optional
Architecture: all
Depends: {DEPENDS}
Recommends: {RECOMMENDS}
Suggests: {SUGGESTS}
Installed-Size: {installed_kb}
Maintainer: {MAINTAINER}
Homepage: {HOMEPAGE}
Description: CleanBlackboard - a whiteboard you just open and write on
 A distraction-free desktop whiteboard: pen / highlighter / brush, box or
 click selection with a colour panel (swatches, hex, RGB, hue bar, eyedropper),
 sticky mini-blackboards, multi-page, long-screenshot sharing, and PNG /
 project export. Everything runs offline, no account, no telemetry.
 .
 简黑板：双击就能写的桌面白板。三档笔、框选/点选、选中改色（常用色 /
 十六进制 / RGB / 色相条 / 吸管）、小黑板、多页、分享长截图，全部离线可用。
"""


# ----------------------------------------------------------------------
# tar / ar 构造
# ----------------------------------------------------------------------
def _tar_bytes(entries: list[tuple[str, Path | None, bytes | None, int]]) -> bytes:
    """entries: (归档内路径, 源文件, 内存内容, 模式)。

    所有条目属主都写成 root:root，时间戳用构建时间 —— 这是 Debian 包的规矩，
    不然装到别人机器上会看到一堆奇怪的用户名。
    """
    buf = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        tf.encoding = "utf-8"
        for name, src, data, mode in entries:
            info = tarfile.TarInfo(name)
            info.mtime = now
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mode = mode
            if data is None and src is not None:
                data = src.read_bytes()
            payload = data or b""
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

    raw = buf.getvalue()
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=now) as gz:
        gz.write(raw)
    return out.getvalue()


def _ar_member(name: str, data: bytes, mtime: int) -> bytes:
    # ar 头固定 60 字节：名字 16 / 时间 12 / 属主 6 / 属组 6 / 权限 8 / 大小 10 / 魔数 2
    header = (
        f"{name:<16}{mtime:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n"
    ).encode("ascii")
    body = data if len(data) % 2 == 0 else data + b"\n"
    return header + body


def build_ar(*members: tuple[str, bytes]) -> bytes:
    now = int(time.time())
    out = b"!<arch>\n"
    for name, data in members:
        out += _ar_member(name, data, now)
    return out


# ----------------------------------------------------------------------
# 文件树
# ----------------------------------------------------------------------
def collect_entries(ver: str, stage: Path) -> tuple[list, list[str]]:
    """返回 (tar 条目表, md5sums 行)。顺便把文件落到 stage 供打图标。"""
    entries: list[tuple[str, Path | None, bytes | None, int]] = []
    md5: list[str] = []
    seen: set[str] = set()

    def add(path: str, src: Path | None = None, data: bytes | None = None,
            mode: int = 0o644) -> None:
        payload = data if data is not None else (src.read_bytes() if src else b"")
        entries.append((path, None, payload, mode))
        if mode & 0o111 == 0:      # 只对普通文件算 md5
            md5.append(f"{hashlib.md5(payload).hexdigest()}  {path[2:]}")
        # 目录得先出现，tar 才是规范顺序
        parent = str(Path(path).parent).replace("\\", "/")
        while parent not in (".", "/", ""):
            d = f"./{parent.lstrip('./')}/" if not parent.startswith("./") else f"{parent}/"
            if d not in seen:
                seen.add(d)
                entries.insert(len(entries) - 1,
                               (d, None, b"", 0o755))
            parent = str(Path(parent).parent).replace("\\", "/")

    # 1) 程序本体
    add(f".{APP_DIR}/main.py", ROOT / "main.py")
    add(f".{APP_DIR}/README.md", ROOT / "README.md")
    add(f".{APP_DIR}/LICENSE", ROOT / "LICENSE")
    add(f".{APP_DIR}/使用说明.txt", ROOT / "使用说明.txt")
    for f in sorted((ROOT / "ui").rglob("*")):
        if f.is_file():
            rel = f.relative_to(ROOT).as_posix()
            add(f".{APP_DIR}/{rel}", f)
    for f in sorted((ROOT / "assets").glob("app.*")):
        add(f".{APP_DIR}/assets/{f.name}", f)

    # 2) 启动器
    add("./usr/bin/cleanblackboard", None, LAUNCHER.encode("utf-8"), 0o755)

    # 3) 桌面入口
    add(f"./usr/share/applications/{DESKTOP}", None, DESKTOP_ENTRY.encode("utf-8"))

    # 4) 图标（多尺寸）
    src_icon = ROOT / "assets" / "app.png"
    for size in ICON_SIZES:
        out = stage / f"icon-{size}.png"
        try:
            from PIL import Image
            with Image.open(src_icon) as im:
                im.convert("RGBA").resize((size, size), Image.LANCZOS).save(out)
        except Exception:
            if size == 256:
                shutil.copy2(src_icon, out)
            else:
                continue
        if out.exists():
            add(f"./usr/share/icons/hicolor/{size}x{size}/apps/cleanblackboard.png", out)

    # 5) 文档
    add(f"./usr/share/doc/{PKG}/copyright", None,
        f"CleanBlackboard {ver}\nMIT License\n{HOMEPAGE}\n".encode("utf-8"))
    add(f"./usr/share/doc/{PKG}/changelog.gz", None,
        gzip.compress(
            f"cleanblackboard ({ver}) unstable; urgency=medium\n\n"
            f"  * Release {ver}.\n\n"
            f" -- {MAINTAINER}  {time.strftime('%a, %d %b %Y %H:%M:%S +0800')}\n"
            .encode("utf-8"), mtime=0))

    # 去重 + 排序（目录在前）
    uniq: dict[str, tuple] = {}
    for e in entries:
        uniq[e[0]] = e
    ordered = sorted(uniq.values(), key=lambda e: (e[0].count("/"), e[0]))
    return ordered, md5


def build() -> int:
    ver = read_version()
    stage = Path(tempfile.mkdtemp(prefix="cb_deb_"))
    try:
        # shell 脚本先过一遍 sh -n：少写个 fi、多写个 done 这类低级错，
        # 装到别人机器上就是「装完点不开」，在这里拦住最划算
        sh = shutil.which("sh")
        if sh:
            for label, src in (("启动器", LAUNCHER), ("postinst", POSTINST),
                               ("postrm", POSTRM)):
                f = stage / f"syntax_{label}.sh"
                f.write_text(src, encoding="utf-8", newline="\n")
                r = subprocess.run([sh, "-n", str(f)], capture_output=True, text=True)
                if r.returncode != 0:
                    raise SystemExit(f"{label} 语法错误：{r.stderr.strip()}")
            print(f"✓ 启动器 / postinst / postrm 语法通过（{Path(sh).name} -n）")

        data_entries, md5_lines = collect_entries(ver, stage)
        data_tar = _tar_bytes(data_entries)

        # Installed-Size 按解包后 KB 估算（Debian 惯例向上取整）
        total_bytes = sum(len(d or b"") for _, _, d, _ in data_entries)
        installed_kb = max(1, (total_bytes + 1023) // 1024)

        ctrl_dir = stage / "ctrl"
        ctrl_dir.mkdir(exist_ok=True)
        (ctrl_dir / "control").write_text(control_text(ver, installed_kb), encoding="utf-8")
        (ctrl_dir / "postinst").write_text(POSTINST, encoding="utf-8")
        (ctrl_dir / "postrm").write_text(POSTRM, encoding="utf-8")
        (ctrl_dir / "md5sums").write_text("\n".join(md5_lines) + "\n", encoding="utf-8")

        ctrl_entries = [
            ("./control", None, (ctrl_dir / "control").read_bytes(), 0o644),
            ("./md5sums", None, (ctrl_dir / "md5sums").read_bytes(), 0o644),
            ("./postinst", None, (ctrl_dir / "postinst").read_bytes(), 0o755),
            ("./postrm", None, (ctrl_dir / "postrm").read_bytes(), 0o755),
        ]
        ctrl_tar = _tar_bytes(ctrl_entries)

        deb = build_ar(
            ("debian-binary", b"2.0\n"),
            ("control.tar.gz", ctrl_tar),
            ("data.tar.gz", data_tar),
        )

        DIST.mkdir(exist_ok=True)
        out = DIST / f"{PKG}_{ver}_all.deb"
        out.write_bytes(deb)
        print(f"打好了：{out}")
        print(f"  大小 {len(deb) / 1024:.1f} KB · 解包后 {installed_kb} KB · {len(data_entries)} 个条目")

        return verify(out, ver)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ----------------------------------------------------------------------
# 自检：把打好的 deb 读回来验一遍
# ----------------------------------------------------------------------
def _read_ar(blob: bytes) -> list[tuple[str, bytes]]:
    if not blob.startswith(b"!<arch>\n"):
        raise SystemExit("不是 ar 归档")
    out = []
    pos = 8
    while pos + 60 <= len(blob):
        head = blob[pos:pos + 60]
        if head[58:60] != b"`\n":
            raise SystemExit(f"ar 头魔数不对（偏移 {pos}）")
        name = head[0:16].decode("ascii").strip()
        size = int(head[48:58].decode("ascii").strip() or 0)
        pos += 60
        out.append((name, blob[pos:pos + size]))
        pos += size + (size % 2)
    return out


def _untar(blob: bytes) -> list[tuple[str, int, bytes]]:
    raw = gzip.decompress(blob)
    out = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
        for m in tf.getmembers():
            data = tf.extractfile(m).read() if m.isfile() else b""
            out.append((m.name, m.mode, data, m.uid, m.gid))
    return out


def verify(deb: Path, ver: str) -> int:
    print("\n自检：")
    blob = deb.read_bytes()
    members = _read_ar(blob)
    names = [n for n, _ in members]
    ok = True

    def chk(cond: bool, what: str, detail: str = "") -> None:
        nonlocal ok
        print(f"  {'✓' if cond else '✗'} {what}{('  — ' + detail) if detail else ''}")
        ok = ok and cond

    chk(names == ["debian-binary", "control.tar.gz", "data.tar.gz"],
        "ar 成员顺序正确", " / ".join(names))
    chk(dict(members)["debian-binary"] == b"2.0\n", "debian-binary 是 2.0")

    ctrl = {n.lstrip("./"): (m, d) for n, m, d, _, _ in _untar(dict(members)["control.tar.gz"])}
    required = {"Package", "Version", "Architecture", "Maintainer", "Description", "Depends"}
    text = ctrl["control"][1].decode("utf-8")
    fields = {ln.split(":", 1)[0] for ln in text.splitlines() if ":" in ln and not ln.startswith(" ")}
    chk(required <= fields, "control 必需字段齐全", f"缺 {required - fields}" if required - fields else "")
    chk("Package: cleanblackboard" in text, "Package 名正确")
    chk(f"Version: {ver}" in text, "版本号与 main.py 一致", ver)
    chk("Architecture: all" in text, "Architecture: all（纯 Python，不绑架构）")
    chk(ctrl["postinst"][0] & 0o111 != 0, "postinst 可执行")
    chk(ctrl["postrm"][0] & 0o111 != 0, "postrm 可执行")

    data = _untar(dict(members)["data.tar.gz"])
    paths = {p: (mode, payload) for p, mode, payload, _, _ in data}
    must = [
        f".{APP_DIR}/main.py",
        f".{APP_DIR}/ui/index.html",
        f"./usr/bin/cleanblackboard",
        f"./usr/share/applications/{DESKTOP}",
        "./usr/share/icons/hicolor/256x256/apps/cleanblackboard.png",
    ]
    for p in must:
        chk(p in paths, f"包含 {p}")
    chk(paths[f"./usr/bin/cleanblackboard"][0] & 0o111 != 0, "启动器可执行")
    chk(paths[f".{APP_DIR}/main.py"][0] == 0o644, "main.py 权限 0644")
    chk(all(uid == 0 and gid == 0 for _, _, _, uid, gid in data), "所有条目属主是 root")
    chk(paths.get(f".{APP_DIR}/ui/index.html", (0, b""))[1].startswith(b"<!DOCTYPE") or
        b"<html" in paths.get(f".{APP_DIR}/ui/index.html", (0, b""))[1][:400].lower(),
        "界面文件内容完整")

    # md5sums 和实际文件对得上
    sums = dict(
        (ln.split("  ", 1)[1], ln.split("  ", 1)[0])
        for ln in ctrl["md5sums"][1].decode("utf-8").splitlines() if "  " in ln
    )
    bad = [p for p, h in sums.items()
           if f"./{p}" in paths and hashlib.md5(paths[f"./{p}"][1]).hexdigest() != h]
    chk(not bad, "md5sums 与实际内容一致", f"{len(sums)} 项" if not bad else str(bad[:3]))

    print(f"\n{'自检通过' if ok else '自检失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(build())
