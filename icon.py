"""Shared icon artwork (radar scope) used for the tray icon and the exe icon."""
from PIL import Image, ImageDraw


def make_image(size: int = 64):
    """Render the radar-scope icon at the given square size and return a PIL Image."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (0, 220, 120, 255)
    s = size / 64.0
    # Outer scope ring
    d.ellipse((6 * s, 6 * s, 58 * s, 58 * s), outline=color, width=max(1, int(3 * s)))
    # Inner ring
    d.ellipse((18 * s, 18 * s, 46 * s, 46 * s), outline=color, width=max(1, int(2 * s)))
    # Crosshairs
    d.line((32 * s, 8 * s, 32 * s, 56 * s), fill=color, width=max(1, int(2 * s)))
    d.line((8 * s, 32 * s, 56 * s, 32 * s), fill=color, width=max(1, int(2 * s)))
    # Sweep line (a single radar spoke) + a blip
    d.line((32 * s, 32 * s, 50 * s, 16 * s), fill=color, width=max(1, int(2 * s)))
    d.ellipse((40 * s, 22 * s, 47 * s, 29 * s), fill=color)
    return img


def write_ico(path: str):
    """Write a multi-resolution Windows .ico file at `path`."""
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    make_image(256).save(path, format='ICO', sizes=sizes)
