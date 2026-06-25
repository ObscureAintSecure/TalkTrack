"""Create a Start Menu shortcut for TalkTrack.

Windows resolves taskbar icons by matching the process AppUserModelID to a
Start Menu shortcut that carries the same ID. Without the shortcut, the
taskbar falls back to the executable's embedded icon — which for MS Store
Python is the generic Python logo.

This module creates a .lnk in the user's Start Menu so that Windows picks
up TalkTrack's custom icon on the taskbar.
"""
import ctypes
import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_ID = "TalkTrack.TalkTrack.1"
SHORTCUT_NAME = "TalkTrack.lnk"


def _start_menu_dir():
    """Return the user's Start Menu Programs folder."""
    return Path(os.environ.get(
        "APPDATA", Path.home() / "AppData" / "Roaming"
    )) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _find_launch_target(app_dir):
    """Find the best executable to target in the shortcut.

    Prefer the project-local venv interpreter (``.venv\\Scripts\\pythonw.exe``).
    It's a real binary that works as a shortcut target AND keeps the app on its
    isolated dependencies — so the shortcut launches the same environment as
    start.bat, with the correct taskbar icon.

    Fall back to a system pythonw (note: MS Store's pythonw is an execution
    alias Windows can't resolve in shortcuts, which is exactly why the venv
    interpreter is preferred).
    """
    app_dir = Path(app_dir)

    venv_pythonw = app_dir / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.exists():
        return str(venv_pythonw), f'"{app_dir / "main.py"}"'

    # Fallback to pythonw
    found = shutil.which("pythonw")
    if found:
        return found, f'"{app_dir / "main.py"}"'
    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    if pythonw.exists():
        return str(pythonw), f'"{app_dir / "main.py"}"'
    return sys.executable, f'"{app_dir / "main.py"}"'


def shortcut_path():
    """Return the full path where the shortcut would be created."""
    return _start_menu_dir() / SHORTCUT_NAME


def needs_shortcut(app_dir):
    """Check if a Start Menu shortcut needs to be created or updated.

    Uses PowerShell to check because MS Store Python can't see the real
    Start Menu folder (it sees its own virtualized copy instead).
    """
    import subprocess

    app_dir = Path(app_dir)
    icon_path = app_dir / "resources" / "talktrack.ico"

    if not icon_path.exists() or not (app_dir / "main.py").exists():
        return False

    lnk = shortcut_path()

    # Use PowerShell to check the real filesystem
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Test-Path '{lnk}'"],
        capture_output=True, text=True,
    )
    if result.stdout.strip() != "True":
        return True

    # Shortcut exists — check if it points to the right target
    try:
        target, args, icon = _read_shortcut(lnk)
        target_ok = bool(target and args and str(app_dir / "main.py") in args)
        icon_ok = icon and str(icon_path) in icon
        if target_ok and icon_ok:
            return False
    except Exception:
        pass

    return True


def create_shortcut(app_dir):
    """Create or update the Start Menu shortcut.

    Uses PowerShell to create the .lnk because MS Store Python virtualizes
    file system writes to AppData, so files written by Python end up in a
    sandboxed location invisible to the real Start Menu.

    Args:
        app_dir: Path to the TalkTrack project root (where main.py lives).

    Raises:
        Exception: If shortcut creation fails.
    """
    import subprocess

    app_dir = Path(app_dir)
    icon_path = app_dir / "resources" / "talktrack.ico"
    lnk = shortcut_path()
    target_exe, arguments = _find_launch_target(app_dir)

    # PowerShell script to create the shortcut outside the MS Store sandbox
    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk}')
$sc.TargetPath = '{target_exe}'
$sc.Arguments = '{arguments}'
$sc.WorkingDirectory = '{app_dir}'
$sc.IconLocation = '{icon_path},0'
$sc.Description = 'TalkTrack - Call Recorder, Transcriber and AI Summary'
$sc.Save()
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell shortcut creation failed: {result.stderr.strip()}")

    # Set AppUserModelID property on the .lnk
    _set_shortcut_app_id_via_powershell(str(lnk), APP_ID)

    logger.info("Created Start Menu shortcut: %s", lnk)


def _set_shortcut_app_id_via_powershell(lnk_path, app_id):
    """Set System.AppUserModel.ID on a .lnk via PowerShell."""
    import subprocess

    # Use the Windows Shell COM to set the property
    ps_script = f"""
$shell = New-Object -ComObject Shell.Application
$dir = $shell.Namespace((Split-Path '{lnk_path}'))
$lnk = $dir.ParseName((Split-Path '{lnk_path}' -Leaf))
# Property System.AppUserModel.ID has column index that varies;
# set it via the ShellLinkObject approach instead
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public class ShortcutHelper {{
    [DllImport("shell32.dll")]
    static extern int SHGetPropertyStoreFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string pszPath,
        IntPtr pbc, int flags,
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid,
        out IPropertyStore ppv);

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {{
        int GetCount(out uint cProps);
        int GetAt(uint iProp, out PROPERTYKEY pkey);
        int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
        int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
        int Commit();
    }}

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPERTYKEY {{
        public Guid fmtid;
        public uint pid;
    }}

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPVARIANT {{
        public ushort vt;
        public ushort r1, r2, r3;
        public IntPtr val;
        public ulong pad;
    }}

    public static void SetAppId(string path, string appId) {{
        Guid IID = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore store;
        int hr = SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, IID, out store);
        if (hr != 0) throw new COMException("SHGetPropertyStoreFromParsingName", hr);

        PROPERTYKEY pk = new PROPERTYKEY();
        pk.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        pk.pid = 5;

        PROPVARIANT pv = new PROPVARIANT();
        pv.vt = 31; // VT_LPWSTR
        pv.val = Marshal.StringToCoTaskMemUni(appId);

        store.SetValue(ref pk, ref pv);
        store.Commit();
        Marshal.FreeCoTaskMem(pv.val);
        Marshal.ReleaseComObject(store);
    }}
}}
'@
[ShortcutHelper]::SetAppId('{lnk_path}', '{app_id}')
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Non-fatal: shortcut works without AppUserModelID, just won't match for icon
        logger.warning("Could not set AppUserModelID on shortcut: %s", result.stderr.strip())


def _set_shortcut_app_id(lnk_path, app_id):
    """Set System.AppUserModel.ID on a .lnk file via IPropertyStore."""
    from comtypes import GUID

    IID_IPropertyStore = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    GPS_READWRITE = 2

    SHGetPropertyStoreFromParsingName = ctypes.windll.shell32.SHGetPropertyStoreFromParsingName
    SHGetPropertyStoreFromParsingName.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    SHGetPropertyStoreFromParsingName.restype = ctypes.HRESULT

    ppv = ctypes.c_void_p()
    hr = SHGetPropertyStoreFromParsingName(
        lnk_path, None, GPS_READWRITE,
        ctypes.byref(IID_IPropertyStore), ctypes.byref(ppv),
    )
    if hr != 0:
        raise OSError(f"SHGetPropertyStoreFromParsingName failed: 0x{hr & 0xFFFFFFFF:08X}")

    try:
        _property_store_set_string(ppv.value, app_id)
    except Exception:
        _release_com(ppv.value)
        raise


def _property_store_set_string(pstore_ptr, value):
    """Set the AppUserModel.ID string on an IPropertyStore and commit."""
    from comtypes import GUID

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [
            ("fmtid", ctypes.c_byte * 16),
            ("pid", ctypes.c_ulong),
        ]

    pk = PROPERTYKEY()
    guid = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
    ctypes.memmove(pk.fmtid, bytes(guid), 16)
    pk.pid = 5

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("reserved1", ctypes.c_ushort),
            ("reserved2", ctypes.c_ushort),
            ("reserved3", ctypes.c_ushort),
            ("pwszVal", ctypes.c_wchar_p),
            ("padding", ctypes.c_ulonglong),
        ]

    pv = PROPVARIANT()
    pv.vt = 31  # VT_LPWSTR
    pv.pwszVal = value

    vtable = ctypes.cast(
        ctypes.c_void_p(
            ctypes.cast(ctypes.c_void_p(pstore_ptr),
                        ctypes.POINTER(ctypes.c_void_p))[0]
        ),
        ctypes.POINTER(ctypes.c_void_p * 8),
    ).contents

    SetValue = ctypes.CFUNCTYPE(
        ctypes.HRESULT, ctypes.c_void_p,
        ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT),
    )(vtable[6])
    hr = SetValue(pstore_ptr, ctypes.byref(pk), ctypes.byref(pv))
    if hr != 0:
        _release_com(pstore_ptr)
        raise OSError(f"IPropertyStore::SetValue failed: 0x{hr & 0xFFFFFFFF:08X}")

    Commit = ctypes.CFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
    hr = Commit(pstore_ptr)

    _release_com(pstore_ptr)

    if hr != 0:
        raise OSError(f"IPropertyStore::Commit failed: 0x{hr & 0xFFFFFFFF:08X}")


def _release_com(ptr):
    """Call Release on a COM pointer."""
    Release = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
        ctypes.cast(
            ctypes.c_void_p(
                ctypes.cast(ctypes.c_void_p(ptr),
                            ctypes.POINTER(ctypes.c_void_p))[0]
            ),
            ctypes.POINTER(ctypes.c_void_p * 3),
        ).contents[2]
    )
    Release(ptr)


def _read_shortcut(lnk_path):
    """Read target, arguments, and icon from an existing .lnk via PowerShell."""
    import subprocess

    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk_path}')
$sc.TargetPath
$sc.Arguments
$sc.IconLocation
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not read shortcut: {result.stderr.strip()}")
    lines = result.stdout.strip().splitlines()
    target = lines[0] if len(lines) > 0 else ""
    args = lines[1] if len(lines) > 1 else ""
    icon = lines[2] if len(lines) > 2 else ""
    return target, args, icon
