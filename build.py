"""Build TalkTrack.exe — copy pythonw.exe and replace its icon.

The result is a ~170 KB exe that IS Python, just with the TalkTrack icon.
Launch with: TalkTrack.exe main.py

Usage: python build.py
"""
import ctypes
import ctypes.wintypes
import shutil
import struct
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
ICO_PATH = APP_DIR / "resources" / "talktrack.ico"
EXE_PATH = APP_DIR / "TalkTrack.exe"


def find_real_pythonw():
    """Find the real pythonw.exe (not the 0-byte MS Store alias)."""
    real = Path(sys.base_prefix) / "pythonw.exe"
    if real.exists() and real.stat().st_size > 0:
        return real
    # Fallback: check next to sys.executable
    alt = Path(sys.executable).parent / "pythonw.exe"
    if alt.exists() and alt.stat().st_size > 0:
        return alt
    return None


def replace_icon(exe_path, ico_path):
    """Replace the icon in an exe using Win32 UpdateResource API."""
    # Read ICO file
    ico_data = ico_path.read_bytes()
    # Parse ICO header
    _reserved, ico_type, num_images = struct.unpack_from("<HHH", ico_data, 0)
    if ico_type != 1:
        raise ValueError("Not a valid ICO file")

    # Parse ICO directory entries
    entries = []
    for i in range(num_images):
        offset = 6 + i * 16
        width, height, colors, _reserved, planes, bpp, data_size, data_offset = \
            struct.unpack_from("<BBBBHHII", ico_data, offset)
        png_data = ico_data[data_offset:data_offset + data_size]
        entries.append((width, height, colors, planes, bpp, data_size, png_data))

    # Win32 API functions
    BeginUpdateResource = ctypes.windll.kernel32.BeginUpdateResourceW
    UpdateResource = ctypes.windll.kernel32.UpdateResourceW
    EndUpdateResource = ctypes.windll.kernel32.EndUpdateResourceW

    BeginUpdateResource.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
    BeginUpdateResource.restype = ctypes.wintypes.HANDLE

    UpdateResource.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.wintypes.WORD, ctypes.c_void_p, ctypes.wintypes.DWORD
    ]
    UpdateResource.restype = ctypes.c_bool

    EndUpdateResource.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_bool]
    EndUpdateResource.restype = ctypes.c_bool

    RT_ICON = 3
    RT_GROUP_ICON = 14
    LANG_NEUTRAL = 0

    handle = BeginUpdateResource(str(exe_path), False)
    if not handle:
        raise OSError(f"BeginUpdateResource failed (error {ctypes.GetLastError()})")

    # Write each icon image as RT_ICON resource (IDs starting at 1)
    for i, (width, height, colors, planes, bpp, data_size, png_data) in enumerate(entries):
        icon_id = i + 1
        ok = UpdateResource(
            handle, RT_ICON, icon_id, LANG_NEUTRAL,
            png_data, len(png_data)
        )
        if not ok:
            EndUpdateResource(handle, True)
            raise OSError(f"UpdateResource RT_ICON failed (error {ctypes.GetLastError()})")

    # Build GRPICONDIR structure for RT_GROUP_ICON
    grp_header = struct.pack("<HHH", 0, 1, num_images)
    grp_entries = b""
    for i, (width, height, colors, planes, bpp, data_size, _) in enumerate(entries):
        # GRPICONDIRENTRY: same as ICONDIRENTRY but last field is ID not offset
        grp_entries += struct.pack("<BBBBHHIH",
            width, height, colors, 0, planes, bpp, data_size, i + 1)

    grp_data = grp_header + grp_entries
    ok = UpdateResource(
        handle, RT_GROUP_ICON, 1, LANG_NEUTRAL,
        grp_data, len(grp_data)
    )
    if not ok:
        EndUpdateResource(handle, True)
        raise OSError(f"UpdateResource RT_GROUP_ICON failed (error {ctypes.GetLastError()})")

    if not EndUpdateResource(handle, False):
        raise OSError(f"EndUpdateResource failed (error {ctypes.GetLastError()})")


def build():
    pythonw = find_real_pythonw()
    if not pythonw:
        print("Error: Cannot find pythonw.exe")
        sys.exit(1)

    print(f"Source: {pythonw} ({pythonw.stat().st_size // 1024} KB)")

    # Copy pythonw.exe -> TalkTrack.exe
    shutil.copy2(pythonw, EXE_PATH)

    # Replace the icon
    replace_icon(EXE_PATH, ICO_PATH)

    size_kb = EXE_PATH.stat().st_size / 1024
    print(f"Built: {EXE_PATH} ({size_kb:.0f} KB)")
    print(f"Launch with: TalkTrack.exe main.py")


if __name__ == "__main__":
    build()
