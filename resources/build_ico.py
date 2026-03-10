"""Build a multi-size Windows .ico from individual PNG files."""
import struct
from pathlib import Path

RESOURCES = Path(__file__).parent
SIZES = [16, 32, 48, 64, 128, 256]

def build_ico():
    # Collect PNG data for each size, resizing from nearest larger source
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QImage
    from PyQt6.QtCore import Qt
    import sys

    app = QApplication(sys.argv)

    # Available source PNGs
    sources = {}
    for f in RESOURCES.glob("TT_icon_*.png"):
        name = f.stem  # e.g. TT_icon_256x256
        sz = int(name.split("_")[-1].split("x")[0])
        sources[sz] = f

    images = []
    for target_size in SIZES:
        if target_size in sources:
            img = QImage(str(sources[target_size]))
        else:
            # Find nearest larger source and scale down
            larger = sorted(s for s in sources if s >= target_size)
            if larger:
                img = QImage(str(sources[larger[0]]))
            else:
                img = QImage(str(sources[max(sources)]))
            img = img.scaled(target_size, target_size,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)

        # Save to PNG bytes
        import io
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img.save(tmp.name, "PNG")
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            png_data = f.read()
        Path(tmp_path).unlink()
        images.append((target_size, png_data))

    # Write ICO file
    out_path = RESOURCES / "talktrack.ico"
    header = struct.pack("<HHH", 0, 1, len(images))

    dir_size = 16 * len(images)
    offset = 6 + dir_size

    entries = []
    for sz, png_data in images:
        w = sz if sz < 256 else 0
        h = sz if sz < 256 else 0
        entry = struct.pack("<BBBBHHII",
            w, h, 0, 0,
            1, 32,
            len(png_data), offset
        )
        entries.append(entry)
        offset += len(png_data)

    with open(out_path, "wb") as f:
        f.write(header)
        for entry in entries:
            f.write(entry)
        for _, png_data in images:
            f.write(png_data)

    print(f"Created {out_path} with sizes: {', '.join(f'{s}x{s}' for s in SIZES)}")


if __name__ == "__main__":
    build_ico()
