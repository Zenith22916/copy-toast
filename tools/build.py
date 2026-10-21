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
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "copy-toast"
ASSETS = os.path.join(ROOT, "assets")
ICON = os.path.join(ASSETS, "copy_toast.ico")


def fix_integrity_level(exe: str) -> None:
    """把 exe 的完整性标签设为 Medium。

    为什么必须做这一步：
      如果打包目录继承了「低完整性」标记（沙箱工具、部分解压软件、
      从低完整性位置复制过来的目录都会留下这个标记），生成的 exe 也会
      继承它。Windows 规定带 Low 标签的可执行文件启动后进程就是 Low 完整性，
      而 Low 进程无法向 explorer 发送 Shell_NotifyIcon，结果是：
      程序在跑、但托盘图标挂不上，用户看到的就是「双击没反应」。
      实测日志里就是 `托盘图标添加失败: err=5`。

    这一步失败不影响 exe 本身，只打警告，提示用户手动处理。
    """
    try:
        last = None
        for attempt in range(5):
            r = subprocess.run(
                ["icacls", exe, "/setintegritylevel", "Medium"],
                capture_output=True,
            )
            if r.returncode == 0:
                print("已设置 exe 完整性级别: Medium")
                return
            last = r
            # PyInstaller 刚写完文件时可能还被短暂占用，等一下再试
            time.sleep(1.0)
        detail = (last.stdout or b"").decode("gbk", "replace") if last else ""
        print(f"[警告] 设置完整性级别失败 (rc={last.returncode if last else '?'}): {detail.strip()}")
        print("       常见原因：当前 Python 进程本身是低完整性（如跑在沙箱/受限环境里），"
              "无权改文件标签。")
        print("       请在普通命令行窗口里手动执行：")
        print(f'       icacls "{exe}" /setintegritylevel Medium')
    except OSError as exc:
        print(f"[警告] 无法调用 icacls: {exc}")
        print(f'       请手动执行: icacls "{exe}" /setintegritylevel Medium')


def _remove_tree(path: str) -> None:
    """删掉整个目录，尽量彻底，但不因为删不掉就中断打包。

    旧产物里的 exe 可能带着低完整性标签或被占用，直接 rmtree 会抛
    PermissionError。先试 rmtree，失败再逐个文件改标签后重删；
    最后仍残留就跳过——PyInstaller 会覆盖同名文件，不影响这次打包。
    """
    if not os.path.isdir(path):
        return
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass

    for dirpath, _, files in os.walk(path):
        for name in files:
            f = os.path.join(dirpath, name)
            try:
                subprocess.run(["icacls", f, "/reset"], capture_output=True)
            except OSError:
                pass
            try:
                os.remove(f)
            except OSError:
                pass
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def main() -> int:
    if not os.path.exists(ICON):
        print("缺少图标文件，请先执行: .venv/Scripts/python.exe tools/make_icon.py")
        return 1

    for sub in ("build", "dist"):
        _remove_tree(os.path.join(ROOT, sub))

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

    fix_integrity_level(exe)

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
