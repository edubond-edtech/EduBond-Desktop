"""Draws the EduKit app icon (stylised Kaaba on a green route badge) -> icon.png / .ico / .icns.

Run once:  python packaging/make_icon.py   (needs Pillow). The generated files are committed,
so building the app does not require running this again.
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S = 1024


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # badge: green gradient rounded square
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / S
        gd.line([(0, y), (S, y)], fill=(int(24 + 20 * t), int(150 - 50 * t), int(90 - 30 * t), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=210, fill=255)
    img.paste(grad, (0, 0), mask)
    # golden route of dots curving to the Kaaba
    pts = [(860, 800), (760, 840), (640, 830), (530, 790), (440, 740)]
    for i, (x, y) in enumerate(pts):
        r = 34 - i * 3
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 196, 40, 255))
    # Kaaba: black cube in light perspective with a gold band and door
    front = [(250, 360), (560, 330), (560, 700), (250, 680)]
    side = [(560, 330), (760, 380), (760, 690), (560, 700)]
    top = [(250, 360), (450, 300), (760, 380), (560, 330)]
    d.polygon(top, fill=(45, 45, 45, 255))
    d.polygon(front, fill=(20, 20, 20, 255))
    d.polygon(side, fill=(34, 34, 34, 255))
    d.polygon([(250, 425), (560, 397), (560, 437), (250, 463)], fill=(232, 178, 40, 255))
    d.polygon([(560, 397), (760, 445), (760, 482), (560, 437)], fill=(205, 155, 30, 255))
    d.polygon([(440, 515), (520, 508), (520, 625), (440, 628)], fill=(205, 155, 30, 255))
    return img


def main() -> None:
    img = draw()
    img.save(HERE / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(HERE / "icon.icns")
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
