from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont, ImageFilter


WIDTH = 1200
HEIGHT = 675
SCALE = 2
OUT_DIR = Path("outputs/emotion_release_images_2026-06-05")


PALETTE = {
    "ink": "#23506D",
    "muted": "#5C7E91",
    "blue": "#EAF7FF",
    "blue_2": "#D8EFFB",
    "teal": "#66C7C4",
    "teal_dark": "#2C9BA0",
    "red": "#EF6C73",
    "red_dark": "#CF4C54",
    "yellow": "#FFD66B",
    "white": "#FFFFFF",
    "lavender": "#D8D6FF",
    "pink": "#FFDADF",
    "green": "#DFF6E9",
}


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size * SCALE)
        except OSError:
            continue
    return ImageFont.load_default()


def xy(values):
    return tuple(int(round(v * SCALE)) for v in values)


def sc(value):
    return int(round(value * SCALE))


def new_canvas():
    img = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), PALETTE["blue"])
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT * SCALE):
        t = y / (HEIGHT * SCALE - 1)
        top = hex_to_rgb(PALETTE["blue"])
        bottom = hex_to_rgb(PALETTE["blue_2"])
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line([(0, y), (WIDTH * SCALE, y)], fill=color)
    return img


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def add_soft_panel(draw, box, fill="#FFFFFF", outline="#BEE3F2", radius=34, width=3):
    draw.rounded_rectangle(xy(box), radius=sc(radius), fill=fill, outline=outline, width=sc(width))


def add_shadow(base, box, radius=36, alpha=55, offset=(0, 8)):
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    x0, y0, x1, y1 = xy(box)
    ox, oy = xy(offset)
    shadow_draw.rounded_rectangle(
        (x0 + ox, y0 + oy, x1 + ox, y1 + oy),
        radius=sc(radius),
        fill=(40, 95, 120, alpha),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(sc(10)))
    return Image.alpha_composite(base.convert("RGBA"), shadow)


def draw_sine(draw, start, end, amp=18, waves=3, fill="#2C9BA0", width=6):
    sx, sy = start
    ex, ey = end
    points = []
    for i in range(130):
        t = i / 129
        x = sx + (ex - sx) * t
        y = sy + (ey - sy) * t + math.sin(t * math.tau * waves) * amp
        points.append(xy((x, y)))
    draw.line(points, fill=fill, width=sc(width), joint="curve")


def draw_person(draw, cx, cy, scale=1.0, emotion_lines=True):
    skin = "#F4C6A8"
    hair = "#2D5A76"
    shirt = "#FFFFFF"
    pants = "#7AB8D8"

    draw.ellipse(xy((cx - 44 * scale, cy - 120 * scale, cx + 44 * scale, cy - 32 * scale)), fill=skin)
    draw.pieslice(
        xy((cx - 48 * scale, cy - 132 * scale, cx + 48 * scale, cy - 45 * scale)),
        180,
        360,
        fill=hair,
    )
    draw.arc(xy((cx - 20 * scale, cy - 78 * scale, cx + 20 * scale, cy - 52 * scale)), 20, 160, fill="#8B5E4B", width=sc(3))
    draw.ellipse(xy((cx - 18 * scale, cy - 86 * scale, cx - 11 * scale, cy - 79 * scale)), fill="#31556B")
    draw.ellipse(xy((cx + 11 * scale, cy - 86 * scale, cx + 18 * scale, cy - 79 * scale)), fill="#31556B")

    draw.rounded_rectangle(
        xy((cx - 68 * scale, cy - 32 * scale, cx + 68 * scale, cy + 106 * scale)),
        radius=sc(38 * scale),
        fill=shirt,
        outline="#B7DCEB",
        width=sc(3),
    )
    draw.line(xy((cx - 66 * scale, cy + 2 * scale, cx - 128 * scale, cy + 54 * scale)), fill="#7BAFC8", width=sc(18 * scale))
    draw.line(xy((cx + 66 * scale, cy + 2 * scale, cx + 128 * scale, cy + 54 * scale)), fill="#7BAFC8", width=sc(18 * scale))
    draw.rounded_rectangle(xy((cx - 92 * scale, cy + 96 * scale, cx - 8 * scale, cy + 148 * scale)), radius=sc(22), fill=pants)
    draw.rounded_rectangle(xy((cx + 8 * scale, cy + 96 * scale, cx + 92 * scale, cy + 148 * scale)), radius=sc(22), fill=pants)

    if emotion_lines:
        for idx, color in enumerate([PALETTE["teal_dark"], PALETTE["red"], PALETTE["yellow"]]):
            draw_sine(
                draw,
                (cx - 128 * scale, cy - 2 * scale + idx * 28 * scale),
                (cx + 128 * scale, cy - 2 * scale + idx * 28 * scale),
                amp=8 * scale,
                waves=2.1,
                fill=color,
                width=4 * scale,
            )


def draw_cover():
    base = new_canvas().convert("RGBA")
    base = add_shadow(base, (230, 438, 970, 555), radius=40, alpha=45)
    draw = ImageDraw.Draw(base)

    draw.rounded_rectangle(xy((230, 392, 970, 540)), radius=sc(46), fill="#BDE0F1")
    draw.rounded_rectangle(xy((270, 332, 930, 470)), radius=sc(44), fill="#D7EDF8", outline="#A7D5EA", width=sc(3))
    draw.rounded_rectangle(xy((202, 384, 312, 540)), radius=sc(42), fill="#A9D1E7")
    draw.rounded_rectangle(xy((888, 384, 998, 540)), radius=sc(42), fill="#A9D1E7")
    draw.rounded_rectangle(xy((285, 370, 430, 454)), radius=sc(28), fill="#F4FBFF")
    draw.rounded_rectangle(xy((770, 370, 915, 454)), radius=sc(28), fill="#F4FBFF")

    draw_person(draw, 600, 365, 1.05, True)

    for i, color in enumerate([PALETTE["teal"], PALETTE["red"], PALETTE["yellow"]]):
        draw_sine(draw, (210, 180 + i * 48), (990, 180 + i * 48), amp=15, waves=3.2, fill=color, width=5)
    for x, y, r, c in [(162, 126, 9, PALETTE["teal"]), (1038, 150, 7, PALETTE["yellow"]), (1010, 505, 10, PALETTE["red"]), (160, 498, 7, PALETTE["lavender"])]:
        draw.ellipse(xy((x - r, y - r, x + r, y + r)), fill=c)

    return finish(base)


def draw_cup():
    base = new_canvas().convert("RGBA")
    draw = ImageDraw.Draw(base)
    add_soft_panel(draw, (240, 110, 960, 575), fill="#F7FCFF", outline="#BEE3F2", radius=42)

    cup = (425, 185, 775, 530)
    draw.rounded_rectangle(xy(cup), radius=sc(34), fill="#E9F8FF", outline="#6DBAD6", width=sc(5))
    draw.polygon(xy((438, 244, 762, 244, 724, 515, 476, 515)), fill="#C8EEFA", outline="#6DBAD6")
    draw.rectangle(xy((462, 246, 738, 365)), fill="#83D8E7")
    draw.pieslice(xy((462, 220, 738, 272)), 0, 180, fill="#B8F0FA", outline="#5EB4D0", width=sc(4))
    draw.arc(xy((462, 336, 738, 389)), 0, 180, fill="#52ACC5", width=sc(5))

    for x, y, r in [(515, 330, 12), (640, 305, 9), (700, 350, 15), (575, 384, 8), (650, 426, 11)]:
        draw.ellipse(xy((x - r, y - r, x + r, y + r)), fill="#F7FDFF", outline="#6DBAD6", width=sc(2))

    for x, h, offset in [(505, 74, 0), (600, 96, 0.6), (704, 70, 1.2)]:
        points = []
        for i in range(80):
            t = i / 79
            y = 168 - h * t
            wave = math.sin(t * math.tau * 1.4 + offset) * 12
            points.append(xy((x + wave, y)))
        draw.line(points, fill="#90BFD2", width=sc(5), joint="curve")
        draw.line([(p[0] + sc(24), p[1]) for p in points], fill="#C6DEEA", width=sc(4), joint="curve")

    draw.rounded_rectangle(xy((792, 282, 884, 422)), radius=sc(42), outline="#7FC6DD", width=sc(7))
    draw.rounded_rectangle(xy((816, 310, 860, 394)), radius=sc(24), fill="#F7FCFF")
    return finish(base)


def draw_pressure_gauge():
    base = new_canvas().convert("RGBA")
    draw = ImageDraw.Draw(base)
    add_soft_panel(draw, (210, 95, 990, 585), fill="#F7FCFF", outline="#BEE3F2", radius=42)

    center = (545, 405)
    radius = 205
    draw.pieslice(xy((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)), 190, 350, fill="#E5F5FC")
    draw.arc(xy((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)), 190, 350, fill="#2D6A88", width=sc(12))
    draw.arc(xy((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)), 305, 350, fill=PALETTE["red"], width=sc(28))
    draw.arc(xy((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)), 245, 305, fill=PALETTE["yellow"], width=sc(24))
    draw.arc(xy((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)), 190, 245, fill=PALETTE["teal"], width=sc(24))

    for deg in range(195, 346, 25):
        a = math.radians(deg)
        x0 = center[0] + math.cos(a) * 158
        y0 = center[1] + math.sin(a) * 158
        x1 = center[0] + math.cos(a) * 184
        y1 = center[1] + math.sin(a) * 184
        draw.line(xy((x0, y0, x1, y1)), fill="#2D6A88", width=sc(5))

    angle = math.radians(333)
    tip = (center[0] + math.cos(angle) * 160, center[1] + math.sin(angle) * 160)
    left = (center[0] + math.cos(angle + math.pi / 2) * 12, center[1] + math.sin(angle + math.pi / 2) * 12)
    right = (center[0] + math.cos(angle - math.pi / 2) * 12, center[1] + math.sin(angle - math.pi / 2) * 12)
    draw.polygon([xy(tip), xy(left), xy(right)], fill=PALETTE["red_dark"])
    draw.ellipse(xy((center[0] - 24, center[1] - 24, center[0] + 24, center[1] + 24)), fill="#2D6A88")
    draw.arc(xy((center[0] - 138, center[1] - 138, center[0] + 138, center[1] + 138)), 200, 340, fill="#9FCDE0", width=sc(4))

    burst_center = (850, 260)
    burst_points = []
    for i in range(18):
        a = i / 18 * math.tau
        r = 84 if i % 2 == 0 else 46
        burst_points.append(xy((burst_center[0] + math.cos(a) * r, burst_center[1] + math.sin(a) * r)))
    draw.polygon(burst_points, fill="#FFE6E8", outline=PALETTE["red"], width=sc(5))
    draw.line(xy((820, 230, 880, 290)), fill=PALETTE["red_dark"], width=sc(9))
    draw.line(xy((880, 230, 820, 290)), fill=PALETTE["red_dark"], width=sc(9))
    draw.ellipse(xy((837, 247, 863, 273)), fill=PALETTE["red_dark"])

    return finish(base)


def draw_emotion_labels():
    base = new_canvas().convert("RGBA")
    draw = ImageDraw.Draw(base)
    add_soft_panel(draw, (180, 88, 1020, 590), fill="#F7FCFF", outline="#BEE3F2", radius=42)

    draw_person(draw, 395, 390, 0.95, False)
    draw.rounded_rectangle(xy((296, 518, 494, 548)), radius=sc(15), fill="#7AB8D8")
    draw.line(xy((500, 410, 595, 394)), fill="#7BAFC8", width=sc(14))
    draw.ellipse(xy((586, 382, 614, 410)), fill="#F4C6A8")
    draw.arc(xy((602, 342, 680, 420)), 286, 56, fill=PALETTE["teal_dark"], width=sc(6))
    draw.polygon(xy((674, 347, 705, 354, 681, 376)), fill=PALETTE["teal_dark"])

    labels = [
        ("愤怒", "#FFE3E5", PALETTE["red"], (650, 190), -8),
        ("悲伤", "#E4F4FF", "#4C9ED1", (795, 270), 5),
        ("焦虑", "#FFF3C8", "#D99C20", (640, 382), 7),
        ("快乐", "#E6F8ED", "#34A56F", (820, 455), -6),
    ]
    label_font = font(40, bold=True)
    for text, fill, outline, (x, y), angle in labels:
        card = Image.new("RGBA", (220 * SCALE, 96 * SCALE), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, 220 * SCALE - 1, 96 * SCALE - 1), radius=sc(22), fill=fill, outline=outline, width=sc(4))
        bbox = cd.textbbox((0, 0), text, font=label_font)
        cd.text(((220 * SCALE - (bbox[2] - bbox[0])) / 2, (96 * SCALE - (bbox[3] - bbox[1])) / 2 - sc(4)), text, fill=PALETTE["ink"], font=label_font)
        card = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        base.alpha_composite(card, xy((x - card.size[0] / SCALE / 2, y - card.size[1] / SCALE / 2)))

    return finish(base)


def draw_emotion_envelope():
    base = new_canvas().convert("RGBA")
    draw = ImageDraw.Draw(base)
    add_soft_panel(draw, (205, 95, 995, 585), fill="#F7FCFF", outline="#BEE3F2", radius=42)

    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, alpha in [(245, 26), (180, 34), (116, 48)]:
        gd.ellipse(xy((600 - r, 330 - r, 600 + r, 330 + r)), fill=(255, 214, 107, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(sc(20)))
    base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base)

    for deg in range(0, 360, 30):
        a = math.radians(deg)
        x0 = 600 + math.cos(a) * 110
        y0 = 318 + math.sin(a) * 76
        x1 = 600 + math.cos(a) * 184
        y1 = 318 + math.sin(a) * 128
        draw.line(xy((x0, y0, x1, y1)), fill="#FFD66B", width=sc(5))

    draw.polygon(xy((350, 415, 600, 232, 850, 415)), fill="#DDF4FF", outline="#6DBAD6")
    draw.rounded_rectangle(xy((345, 292, 855, 508)), radius=sc(26), fill="#EAF8FF", outline="#6DBAD6", width=sc(5))
    draw.polygon(xy((350, 300, 600, 438, 850, 300, 850, 508, 350, 508)), fill="#D3EEF9")
    draw.polygon(xy((350, 508, 555, 382, 600, 438, 645, 382, 850, 508)), fill="#BFE4F3", outline="#6DBAD6")
    draw.polygon(xy((350, 300, 600, 438, 850, 300)), fill="#F4FCFF", outline="#6DBAD6")
    draw.line(xy((350, 508, 555, 382)), fill="#6DBAD6", width=sc(4))
    draw.line(xy((850, 508, 645, 382)), fill="#6DBAD6", width=sc(4))

    text = "情绪"
    text_font = font(58, bold=True)
    bbox = draw.textbbox((0, 0), text, font=text_font)
    draw.text(xy((600 - (bbox[2] - bbox[0]) / SCALE / 2, 378 - (bbox[3] - bbox[1]) / SCALE / 2)), text, fill=PALETTE["ink"], font=text_font)

    for x, y, r, color in [(320, 205, 10, PALETTE["teal"]), (885, 210, 8, PALETTE["red"]), (932, 430, 9, PALETTE["yellow"]), (268, 455, 7, PALETTE["lavender"])]:
        draw.ellipse(xy((x - r, y - r, x + r, y + r)), fill=color)

    return finish(base)


def finish(img):
    img = img.convert("RGB")
    return img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    images = [
        ("01_cover_emotion_release.png", draw_cover()),
        ("02_body_cup_emotion_accumulation.png", draw_cup()),
        ("03_body_pressure_gauge_limit.png", draw_pressure_gauge()),
        ("04_body_emotion_labels.png", draw_emotion_labels()),
        ("05_body_emotion_envelope_message.png", draw_emotion_envelope()),
    ]
    for name, img in images:
        img.save(OUT_DIR / name, "PNG", optimize=True)
        print(OUT_DIR / name)


if __name__ == "__main__":
    main()
