"""打包成单文件 exe。

用法：
    python build_tools/build.py
产物：dist/白板.exe
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    spec = ROOT / "whiteboard.spec"
    if not spec.exists():
        print("找不到 whiteboard.spec")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm"]
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / "白板.exe"
    if exe.exists():
        print(f"\n打包完成：{exe}")
        print(f"体积：{exe.stat().st_size / 1048576:.1f} MB")
    else:
        # 某些环境下中文名会被转义，兜底找一下
        cands = list((ROOT / "dist").glob("*.exe"))
        if cands:
            print(f"\n打包完成：{cands[0]}")
        else:
            print("没找到产物，检查上面的日志")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
