"""生成 Hephaestus 正式品牌图标（V1.2）。

设计：深色圆角底板 + 绿色渐变 H 字母 + 琥珀色火花点，强调“锻造/科技”意象，
在 16px 任务栏尺寸下仍能辨认。运行：
    python tools/make_icon.py
产物：
    desktop/assets/Hephaestus.ico   多尺寸 Windows 图标
    desktop/assets/Hephaestus.png   512px 预览图
    docs/assets/icon-preview.png    方案对比与尺寸预览
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "desktop" / "assets"
DOCS = ROOT / "docs" / "assets"
CANVAS = 1024
GREEN_TOP = (176, 246, 204)
GREEN_BOTTOM = (54, 146, 94)
PLATE_TOP = (20, 40, 30)
PLATE_BOTTOM = (8, 18, 13)
AMBER = (255, 197, 120)
AMBER_DARK = (224, 138, 60)


def vertical_gradient(width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        column.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return column.resize((width, height), Image.BICUBIC)


def rounded_mask(size: int, inset: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, size - inset, size - inset], radius=radius, fill=255
    )
    return mask


def h_mask(size: int, scale: float = 1.0) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    center = size / 2
    bar_w = 118 * scale
    gap = 192 * scale
    top = center - 226 * scale
    bottom = center + 226 * scale
    cross_top = center - 60 * scale
    cross_bottom = center + 60 * scale
    radius = 26 * scale
    left = center - gap / 2 - bar_w / 2
    right = center + gap / 2 - bar_w / 2
    draw.rounded_rectangle([left, top, left + bar_w, bottom], radius=radius, fill=255)
    draw.rounded_rectangle([right, top, right + bar_w, bottom], radius=radius, fill=255)
    draw.rounded_rectangle([left, cross_top, right + bar_w, cross_bottom], radius=radius, fill=255)
    return mask


def hexagon_points(center: tuple[float, float], radius: float) -> list[tuple[float, float]]:
    return [
        (center[0] + radius * math.cos(math.radians(60 * i)), center[1] + radius * math.sin(math.radians(60 * i)))
        for i in range(6)
    ]


def render_plate() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    plate_mask = rounded_mask(CANVAS, 26, 212)
    image.paste(vertical_gradient(CANVAS, CANVAS, PLATE_TOP, PLATE_BOTTOM), (0, 0), plate_mask)

    # 中心绿色柔光，让底板有轻微纵深。
    glow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [CANVAS * 0.16, CANVAS * 0.10, CANVAS * 0.84, CANVAS * 0.90], fill=(46, 160, 104, 70)
    )
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    image = Image.alpha_composite(image, Image.composite(glow, Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0)), plate_mask))

    # 细边框。
    border = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        [26, 26, CANVAS - 26, CANVAS - 26], radius=212, outline=(76, 196, 140, 120), width=4
    )
    return Image.alpha_composite(image, border)


def draw_h(image: Image.Image, scale: float = 1.0) -> Image.Image:
    mask = h_mask(CANVAS, scale)
    gradient = vertical_gradient(CANVAS, CANVAS, GREEN_TOP, GREEN_BOTTOM).convert("RGBA")
    image.paste(gradient, (0, 0), mask)
    # 顶部高光（用 alpha_composite，避免 paste 把 H 的 alpha 覆盖成半透明）。
    highlight = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 0))
    ImageDraw.Draw(highlight).rectangle([0, 0, CANVAS, CANVAS * 0.46], fill=(255, 255, 255, 30))
    highlight.putalpha(ImageChops.multiply(highlight.getchannel("A"), mask))
    return Image.alpha_composite(image, highlight)


def draw_ember(image: Image.Image, center: tuple[float, float], radius: float) -> Image.Image:
    glow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [center[0] - radius * 2.4, center[1] - radius * 2.4, center[0] + radius * 2.4, center[1] + radius * 2.4],
        fill=(255, 190, 110, 120),
    )
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(28)))
    points = [
        (center[0], center[1] - radius),
        (center[0] + radius, center[1]),
        (center[0], center[1] + radius),
        (center[0] - radius, center[1]),
    ]
    ImageDraw.Draw(image).polygon(points, fill=(*AMBER, 255))
    ImageDraw.Draw(image).line(points + [points[0]], fill=(*AMBER_DARK, 220), width=3)
    return image


def render_monogram() -> Image.Image:
    image = render_plate()
    image = draw_h(image)
    image = draw_ember(image, (CANVAS * 0.772, CANVAS * 0.278), 30)
    return image


def render_hex() -> Image.Image:
    image = render_plate()
    ring = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    ImageDraw.Draw(ring).polygon(
        hexagon_points((CANVAS / 2, CANVAS / 2), 392),
        outline=(76, 196, 140, 200),
    )
    layer = ImageDraw.Draw(ring)
    layer.line(hexagon_points((CANVAS / 2, CANVAS / 2), 392) + hexagon_points((CANVAS / 2, CANVAS / 2), 392)[:1], fill=(76, 196, 140, 200), width=16, joint="curve")
    image = Image.alpha_composite(image, ring)
    image = draw_h(image, scale=0.78)
    return image


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc") if bold else Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/segoeuib.ttf") if bold else Path("C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()


def build_preview(monogram: Image.Image, hex_version: Image.Image) -> Image.Image:
    width, height = 1440, 860
    sheet = Image.new("RGB", (width, height), (15, 17, 21))
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(38, bold=True)
    label_font = load_font(22)
    small_font = load_font(18)
    draw.text((60, 40), "Hephaestus V1.2 — icon proposals", font=title_font, fill=(240, 246, 242))
    draw.text((60, 96), "A：H 字母 + 火花（推荐）    B：六边形 + H", font=label_font, fill=(150, 168, 158))

    def paste_icon(source: Image.Image, size: int, x: int, y: int) -> None:
        icon = source.resize((size, size), Image.LANCZOS)
        sheet.paste(icon, (x, y), icon)

    # 方案 A 大图与尺寸阶梯。
    draw.text((60, 160), "方案 A · 256 / 128 / 64 / 48 / 32 / 16 px", font=label_font, fill=(190, 210, 198))
    paste_icon(monogram, 256, 60, 200)
    ladder = [128, 64, 48, 32, 16]
    x = 360
    for size in ladder:
        paste_icon(monogram, size, x, 200 + (128 - size) // 2)
        draw.text((x, 340), f"{size}px", font=small_font, fill=(150, 168, 158))
        x += size + 40

    # 浅色背景检查。
    draw.text((60, 420), "浅色背景 / 任务栏效果", font=label_font, fill=(190, 210, 198))
    draw.rounded_rectangle([60, 460, 1380, 600], radius=18, fill=(247, 252, 249))
    x = 90
    for size in [64, 48, 40, 32, 24, 16]:
        paste_icon(monogram, size, x, 460 + (140 - size) // 2)
        x += size + 80

    # 方案 B。
    draw.text((60, 640), "方案 B · 六边形", font=label_font, fill=(190, 210, 198))
    paste_icon(hex_version, 128, 60, 680)
    paste_icon(hex_version, 48, 220, 720)
    paste_icon(hex_version, 32, 290, 736)
    paste_icon(hex_version, 16, 350, 752)

    draw.text(
        (520, 700),
        "推荐 A：纯字母轮廓在小尺寸下更清晰，琥珀色火花点\n提供唯一高亮点，和现有深绿 UI 主色一致。",
        font=small_font,
        fill=(170, 190, 178),
    )
    return sheet


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    monogram = render_monogram()
    hex_version = render_hex()

    ico = ASSETS / "Hephaestus.ico"
    base = monogram.resize((1024, 1024), Image.LANCZOS)
    base.save(ico, format="ICO", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    base.resize((512, 512), Image.LANCZOS).save(ASSETS / "Hephaestus.png", format="PNG")
    build_preview(monogram, hex_version).save(DOCS / "icon-preview.png", format="PNG")

    with Image.open(ico) as check:
        print("ico sizes:", sorted(check.info.get("sizes", [])))
    print("wrote:", ico)
    print("wrote:", ASSETS / "Hephaestus.png")
    print("wrote:", DOCS / "icon-preview.png")


if __name__ == "__main__":
    main()
