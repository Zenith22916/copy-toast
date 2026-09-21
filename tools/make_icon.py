"""生成 copy-toast 的托盘图标（多尺寸 .ico）。

用法：
    python tools/make_icon.py

图标设计：深色圆角方块底 + 绿色「复制」双页图形（后页描边、前页实心）。
配色取自程序本体：底色 #242424，成功绿 #4CAF50。

为什么手写 ICO 容器：Pillow 的 ICO 保存会丢掉 20/40 这类中间尺寸
（实测只写进 16/24/32/48/64/128/256）。而 Windows 在 125% / 150% 缩放
下托盘会取 20px / 24px，尺寸缺档就只能拉伸，边缘会糊。
所以这里自己拼 ICO 目录 + 32 位 BMP，尺寸完全可控。
"""

from __future__ import annotations

import os
import struct

from PIL import Image, ImageDraw

BG = (0, 0, 0, 0)              # 透明背景
TILE = (36, 36, 36, 255)       # 圆角方块底色 #242424
TILE_EDGE = (58, 58, 58, 255)  # 方块描边
GREEN = (76, 175, 80, 255)     # 成功绿 #4CAF50

BASE = 256                     # 基准绘制尺寸
ICON_SIZES = [16, 20, 24, 28, 32, 40, 48, 64, 128, 256]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw_icon(size: int) -> Image.Image:
    """按目标尺寸绘制图标。

    小尺寸下等比缩放的描边会糊，所以这里按尺寸分别计算笔画粗细，
    保证 16px 时依然清晰。内部用 4 倍超采样再缩回，边缘更干净。
    """
    ss = 4
    s = size * ss
    img = Image.new("RGBA", (s, s), BG)
    d = ImageDraw.Draw(img)
    k = s / BASE  # 相对基准的缩放系数

    def px(v: float) -> float:
        return v * k

    # 圆角方块底
    d.rounded_rectangle(
        [px(10), px(10), s - px(10), s - px(10)],
        radius=px(54),
        fill=TILE,
        outline=TILE_EDGE,
        width=max(1, round(px(5))),
    )

    # 后页（描边空心），偏左上
    stroke = max(ss, round(px(17)))
    d.rounded_rectangle(
        [px(64), px(56), px(158), px(150)],
        radius=px(18),
        outline=GREEN,
        width=stroke,
    )

    # 前页（实心），偏右下，盖住后页一角形成「复制」语义。
    # 先在前页位置铺一圈底色再画前页，制造前后页之间的间隙；
    # 否则两块绿色在小尺寸下会糊成一团，认不出是「复制」。
    gap = px(10)
    d.rounded_rectangle(
        [px(102) - gap, px(110) - gap, px(196) + gap, px(204) + gap],
        radius=px(18) + gap,
        fill=TILE,
    )
    d.rounded_rectangle(
        [px(102), px(110), px(196), px(204)],
        radius=px(18),
        fill=GREEN,
    )

    return img.resize((size, size), Image.LANCZOS)


def _to_bmp32(img: Image.Image) -> bytes:
    """把 RGBA 图编成 ICO 内嵌的 32 位 BMP（BITMAPINFOHEADER + 倒序 BGRA + AND 掩码）。"""
    w, h = img.size
    px = img.convert("RGBA").load()

    # 像素数据自下而上，BGRA 顺序
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))

    # AND 掩码：1bpp，每行补齐到 4 字节。32 位图靠 alpha 通道做透明，
    # 这里全填 0 即可（历史上老系统才依赖该掩码）。
    row_bytes = ((w + 31) // 32) * 4
    and_mask = bytes(row_bytes * h)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,              # biSize
        w,               # biWidth
        h * 2,           # biHeight：XOR 与 AND 两张图叠加，故为 2 倍
        1,               # biPlanes
        32,              # biBitCount
        0,               # biCompression
        len(xor) + len(and_mask),  # biSizeImage
        0, 0, 0, 0,      # 分辨率 / 调色板相关，置 0
    )
    return header + bytes(xor) + and_mask


def write_ico(path: str, sizes: list[int]) -> None:
    """按指定尺寸列表写出多尺寸 ICO。"""
    blobs = [_to_bmp32(draw_icon(n)) for n in sizes]

    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(sizes))  # ICONDIR
    offset = 6 + 16 * len(sizes)                  # 图像数据紧跟在目录之后
    for n, blob in zip(sizes, blobs):
        dim = 0 if n == 256 else n                # 256 在 ICO 里用 0 表示
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for blob in blobs:
        out += blob

    with open(path, "wb") as fh:
        fh.write(out)


def main() -> None:
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)

    ico_path = os.path.join(assets, "copy_toast.ico")
    write_ico(ico_path, ICON_SIZES)

    # 预览图：大图 + 小尺寸放大条，便于肉眼检查小尺寸清晰度
    preview = Image.new("RGBA", (430, 250), (28, 28, 28, 255))
    big_view = draw_icon(190)
    preview.paste(big_view, (20, 30), big_view)
    x = 240
    for n in (16, 20, 24, 32, 48):
        small = draw_icon(n)
        zoom = small.resize((n * 4, n * 4), Image.NEAREST)
        preview.paste(zoom, (x, 40), zoom)
        x += n * 4 + 6
    preview.save(os.path.join(assets, "icon_preview.png"))

    old = os.path.join(assets, "_preview.png")
    if os.path.exists(old):
        os.remove(old)

    print("已生成:", ico_path, "尺寸:", ICON_SIZES)
    print("预览:", os.path.join(assets, "icon_preview.png"))


if __name__ == "__main__":
    main()
