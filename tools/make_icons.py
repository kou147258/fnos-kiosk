#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— 图标生成器。

生成 64×64 与 256×256 PNG：渐变背景 + 「显示」字样的圆角图标。
要求：系统 python3 + Pillow（apt install python3-pil）。
"""

import os
import struct
import sys
import zlib


def _png(width, height, pixels_rgb):
    """写一个 8-bit RGB PNG（无 alpha，简单可靠）。"""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter
        row = pixels_rgb[y * width * 3:(y + 1) * width * 3]
        raw.extend(row)
    idat = zlib.compress(bytes(raw), 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def _blend(c1, c2, t):
    return tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))


def _draw_icon(size):
    """极简「浏览器 + 屏幕」风格图标：渐变方块 + 浏览器窗口 + 显示器边框。"""
    bg1 = (10, 19, 34)
    bg2 = (18, 36, 74)
    accent = (59, 130, 246)
    text = (232, 238, 251)
    dim = (147, 165, 196)
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            r, g, b = _blend(bg1, bg2, t)
            # 圆角遮罩
            radius = int(size * 0.18)
            inside = True
            cx = x - radius
            cy = y - radius
            if x < radius and y < radius:
                if cx * cx + cy * cy > radius * radius:
                    inside = False
            elif x >= size - radius and y < radius:
                cx = size - 1 - radius - cx
                cy = y - radius
                if cx * cx + cy * cy > radius * radius:
                    inside = False
            elif x < radius and y >= size - radius:
                cx = x - radius
                cy = size - 1 - radius - cy
                if cx * cx + cy * cy > radius * radius:
                    inside = False
            elif x >= size - radius and y >= size - radius:
                cx = size - 1 - radius - cx
                cy = size - 1 - radius - cy
                if cx * cx + cy * cy > radius * radius:
                    inside = False
            if not inside:
                pixels.extend((0, 0, 0))
                continue
            # 屏幕外框（圆角矩形）
            frame_t = max(2, size // 16)
            outer_pad = size // 8
            inner_pad = outer_pad + frame_t + size // 24
            in_frame = (outer_pad <= x < size - outer_pad and
                        outer_pad <= y < size - outer_pad)
            in_screen = (inner_pad <= x < size - inner_pad and
                         inner_pad <= y < size - inner_pad)
            if in_frame and not in_screen:
                pixels.extend(accent)
                continue
            if in_screen:
                # 在屏幕内画一个「页」字风格的简化符号：左对齐文本条
                # 三条短横线 + 一条长横线
                line_h = max(2, size // 18)
                y0 = inner_pad + (size - 2 * inner_pad) // 3
                y1 = inner_pad + (size - 2 * inner_pad) // 2
                y2 = inner_pad + 2 * (size - 2 * inner_pad) // 3
                line_x0 = inner_pad + size // 20
                line_x1_short = inner_pad + (size - 2 * inner_pad) // 3
                line_x1_long = size - inner_pad - size // 20
                if y0 <= y < y0 + line_h and line_x0 <= x < line_x1_short:
                    pixels.extend(text)
                elif y1 <= y < y1 + line_h and line_x0 <= x < line_x1_long:
                    pixels.extend(text)
                elif y2 <= y < y2 + line_h and line_x0 <= x < line_x1_long:
                    pixels.extend(dim)
                else:
                    pixels.extend((r, g, b))
                continue
            pixels.extend((r, g, b))
    return _png(size, size, bytes(pixels))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    targets = [
        # FNOS 桌面图标位置
        os.path.normpath(os.path.join(here, "..", "app", "ui", "images")),
        # Web 前端引用位置（index.html / settings.html 用 <img src="images/icon-64.png">）
        os.path.normpath(os.path.join(here, "..", "app", "web", "images")),
    ]
    pngs = {"icon-64.png": _draw_icon(64), "icon-256.png": _draw_icon(256)}
    for d in targets:
        os.makedirs(d, exist_ok=True)
        for name, data in pngs.items():
            with open(os.path.join(d, name), "wb") as f:
                f.write(data)
    print("图标已生成：")
    for d in targets:
        print("  " + os.path.join(d, "icon-64.png"))
        print("  " + os.path.join(d, "icon-256.png"))


if __name__ == "__main__":
    main()