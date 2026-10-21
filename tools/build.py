"""把 copy_toast.py 打包成免解包的目录版。

用法（在项目根目录）：
    .venv/Scripts/python.exe tools/build.py

产物：dist/copy-toast/copy-toast.exe —— 双击即用，无控制台窗口，常驻系统托盘。
排查问题看日志：%LOCALAPPDATA%\\copy-toast\\copy_toast.log

为什么用 --onedir 而不是 --onefile：
  * --onefile 每次启动都要把自身解包到 %TEMP%\\_MEIxxxxx，再运行里面的 exe。
    这个「运行时释放可执行文件并执行」的行为会被火绒 HIPS 等主防拦下，
    表现就是双击后静默退出、或弹「Could not create temporary directory!」。
  * --onedir 不解包、不释放任何可执行文件，直接原地加载，启动也更快。
  * 代价是产物从一个 exe 变成一个文件夹：整个 copy-toast 目录要一起拷走，
    只拷 exe 会报缺少文件。

说明：
  * 用 --noconsole 打窗口模式，所以程序里不能直接依赖 print，
    日志统一走 copy_toast.log() 写文件（见 copy_toast.py）。
  * 图标以 --add-data 打进包，运行时由 resource_path() 从程序目录取。
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
        "--onedir",                      # 免解包，绕开主防对自解压的拦截
        "--noconsole",
        "--name", NAME,
        "--icon", ICON,
        # Windows 上分隔符是 ;（os.pathsep），把 assets 整个目录塞进包。
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

    out_dir = os.path.join(ROOT, "dist", NAME)
    exe = os.path.join(out_dir, f"{NAME}.exe")
    if not os.path.exists(exe):
        print(f"打包失败：没有生成 {exe}")
        return 1

    total = sum(
        os.path.getsize(os.path.join(dirpath, f))
        for dirpath, _, files in os.walk(out_dir) for f in files
    )
    print(f"\n打包完成: {exe}")
    print(f"整个 {NAME} 目录共 {total / 1048576:.1f} MB，"
          f"分发时请连同目录一起拷走（只拷 exe 会缺文件）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
