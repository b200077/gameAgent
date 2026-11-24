r"""Move a finished run's screenshots and the core log to the Recycle Bin.

Only touches files next to this script:
  _screenshot\*.png   (all, or only those modified since --since)
  _core_messages.log
Nothing else can be passed in, so it is safe to allow without review.

  python clean_run.py                      # all screenshots + log
  python clean_run.py --since "2026-11-23 23:50"
  python clean_run.py --since "2026-11-23 23:50" --until "2026-11-24 00:01" --keep-log
  python clean_run.py --dry-run
"""
import argparse
import ctypes
import os
import sys
from ctypes import wintypes
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.join(ROOT, "_screenshot")
LOG = os.path.join(ROOT, "_core_messages.log")


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400


def recycle(paths):
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(paths) + "\0\0"
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help='only screenshots modified at/after "YYYY-MM-DD HH:MM"')
    ap.add_argument("--until", help='only screenshots modified before "YYYY-MM-DD HH:MM"')
    ap.add_argument("--keep-log", action="store_true", help="leave _core_messages.log")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    since = datetime.strptime(a.since, "%Y-%m-%d %H:%M").timestamp() if a.since else None
    until = datetime.strptime(a.until, "%Y-%m-%d %H:%M").timestamp() if a.until else None
    files = []
    if os.path.isdir(SHOT_DIR):
        for name in sorted(os.listdir(SHOT_DIR)):
            p = os.path.join(SHOT_DIR, name)
            if name.lower().endswith(".png") and os.path.isfile(p):
                t = os.path.getmtime(p)
                if (since is None or t >= since) and (until is None or t < until):
                    files.append(p)
    if not a.keep_log and os.path.isfile(LOG):
        files.append(LOG)

    for p in files:
        print(os.path.relpath(p, ROOT))
    if not files:
        print("nothing to clean")
        return 0
    if a.dry_run:
        print(f"(dry run) {len(files)} file(s)")
        return 0
    rc = recycle(files)
    print(f"moved {len(files)} file(s) to Recycle Bin" if rc == 0 else f"failed, code {rc}")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
