"""把 copy_toast.py 打包成单文件 exe。

用法（在项目根目录）：
    .venv/Scripts/python.exe tools/build.py

产物：dist/copy-toast.exe —— 双击即用，无控制台窗口，常驻系统托盘。
排查问题看日志：%LOCALAPPDATA%\\copy-toast\\copy_toast.log

说明：
  * 用 --noconsole 打窗口模式，所以程序里不能直接依赖 print，
    日志统一走 copy_toast.log() 写文件（见 copy_toast.py）。
  * 图标以 --add-data 打进包，运行时由 resource_path() 从解包目录取，
    因此 assets 目录必须在包内、不能只当 exe 图标用。
  * 想改成免解包的目录版（启动更快）：把 --onefile 换成 --onedir。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "copy-toast"
ASSETS = os.path.join(ROOT, "assets")
ICON = os.path.join(ASSETS, "copy_toast.ico")


def main() -> int:
    if not os.path.exists(ICON):
        print("缺少图标文件，请先执行: .venv/Scripts/python.exe tools/make_icon.py")
        return 1

    for sub in ("build", "dist"):
        path = os.path.join(ROOT, sub)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--noconsole",
        "--name", NAME,
        "--icon", ICON,
        # Windows 上分隔符是 ;（os.pathsep），把 assets 整个目录塞进包里。
        # 源路径必须用绝对路径：指定了 --specpath 后，相对路径会被当成
        # 相对于 spec 所在目录解析（会去找 build\assets 然后报找不到）。
        "--add-data", f"{ASSETS}{os.pathsep}assets",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "copy_toast.py"),
    ]
    print("执行:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("打包失败")
        return result.returncode

    exe = os.path.join(ROOT, "dist", f"{NAME}.exe")
    size_mb = os.path.getsize(exe) / 1048576
    print(f"\n打包完成: {exe}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
