"""Generate TalkTrack app icon as .ico file.

Run once: python resources/generate_icon.py
"""
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QIcon, QPixmap, QLinearGradient
from PyQt6.QtCore import Qt, QRect, QPoint


def create_icon_pixmap(size):
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))  # transparent

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.06
    s = size - 2 * margin

    # Background: rounded square with gradient
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#1e1e2e"))  # Catppuccin base
    grad.setColorAt(1.0, QColor("#11111b"))  # Catppuccin crust
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    radius = size * 0.18
    p.drawRoundedRect(int(margin), int(margin), int(s), int(s), radius, radius)

    cx = size / 2
    cy = size / 2

    # Draw microphone body (rounded rect)
    mic_color = QColor("#89b4fa")  # Catppuccin blue
    p.setBrush(mic_color)
    p.setPen(Qt.PenStyle.NoPen)
    mic_w = size * 0.22
    mic_h = size * 0.32
    mic_x = cx - mic_w / 2
    mic_y = cy - mic_h / 2 - size * 0.08
    mic_radius = mic_w / 2
    p.drawRoundedRect(int(mic_x), int(mic_y), int(mic_w), int(mic_h), mic_radius, mic_radius)

    # Mic grille lines
    p.setPen(QPen(QColor("#1e1e2e"), max(1, size * 0.02)))
    for i in range(1, 4):
        ly = mic_y + mic_h * 0.25 * i
        p.drawLine(int(mic_x + mic_w * 0.25), int(ly), int(mic_x + mic_w * 0.75), int(ly))

    # Draw mic arc (U-shape under the mic)
    arc_color = QColor("#a6e3a1")  # Catppuccin green
    pen_w = max(2, size * 0.04)
    p.setPen(QPen(arc_color, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    arc_w = size * 0.38
    arc_h = size * 0.28
    arc_rect = QRect(
        int(cx - arc_w / 2), int(mic_y + mic_h * 0.3),
        int(arc_w), int(arc_h)
    )
    p.drawArc(arc_rect, 0, -180 * 16)  # bottom half arc

    # Mic stand (vertical line + base)
    stand_top = mic_y + mic_h * 0.3 + arc_h / 2
    stand_bottom = stand_top + size * 0.12
    p.drawLine(int(cx), int(stand_top), int(cx), int(stand_bottom))

    base_w = size * 0.18
    p.drawLine(int(cx - base_w / 2), int(stand_bottom), int(cx + base_w / 2), int(stand_bottom))

    # Draw waveform bars on sides
    wave_color = QColor("#f9e2af")  # Catppuccin yellow
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(wave_color)
    bar_w = max(2, size * 0.035)

    # Left side bars
    left_heights = [0.10, 0.18, 0.25, 0.15, 0.08]
    for i, h_frac in enumerate(left_heights):
        bx = cx - size * 0.32 - i * size * 0.055
        bh = s * h_frac
        by = cy - bh / 2
        p.drawRoundedRect(int(bx), int(by), int(bar_w), int(bh), bar_w / 2, bar_w / 2)

    # Right side bars (mirror)
    right_heights = [0.10, 0.18, 0.25, 0.15, 0.08]
    for i, h_frac in enumerate(right_heights):
        bx = cx + size * 0.28 + i * size * 0.055
        bh = s * h_frac
        by = cy - bh / 2
        p.drawRoundedRect(int(bx), int(by), int(bar_w), int(bh), bar_w / 2, bar_w / 2)

    p.end()
    return pixmap


def main():
    app = QApplication(sys.argv)

    # Generate multiple sizes for .ico
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icon = QIcon()
    for s in sizes:
        icon.addPixmap(create_icon_pixmap(s))

    # Save as .ico
    out_path = Path(__file__).parent / "talktrack.ico"

    # QIcon can't save directly to .ico, so save the largest as .png
    # and use it. For Windows .ico, we write a proper multi-size ICO file.
    _write_ico(out_path, sizes)
    print(f"Icon saved to {out_path}")

    # Also save a PNG for other uses
    png_path = Path(__file__).parent / "talktrack.png"
    pixmap = create_icon_pixmap(256)
    pixmap.save(str(png_path), "PNG")
    print(f"PNG saved to {png_path}")


def _write_ico(path, sizes):
    """Write a proper Windows ICO file with multiple sizes."""
    import struct
    import io

    app = QApplication.instance()
    images = []
    for s in sizes:
        pixmap = create_icon_pixmap(s)
        buf = io.BytesIO()
        ba = pixmap.toImage()
        # Save each size as PNG data within the ICO
        qbuf = io.BytesIO()
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pixmap.save(tmp.name, "PNG")
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            png_data = f.read()
        Path(tmp_path).unlink()
        images.append((s, png_data))

    # ICO header: 0x00 reserved, 0x01 = ICO type, count
    header = struct.pack("<HHH", 0, 1, len(images))

    # Calculate offsets
    dir_size = 16 * len(images)
    offset = 6 + dir_size  # header(6) + directory entries

    entries = []
    for s, png_data in images:
        w = s if s < 256 else 0
        h = s if s < 256 else 0
        entry = struct.pack("<BBBBHHII",
            w, h, 0, 0,  # width, height, color count, reserved
            1, 32,       # color planes, bits per pixel
            len(png_data), offset
        )
        entries.append(entry)
        offset += len(png_data)

    with open(path, "wb") as f:
        f.write(header)
        for entry in entries:
            f.write(entry)
        for _, png_data in images:
            f.write(png_data)


if __name__ == "__main__":
    main()
