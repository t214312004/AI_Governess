"""Native visibility checks; no Tk calls on keyboard-hook threads."""
import ctypes
from ctypes import wintypes as w


def desktop_available():
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenInputDesktop.restype = w.HANDLE
    api.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    api.GetUserObjectInformationW.restype = w.BOOL
    api.CloseDesktop.argtypes = [w.HANDLE]
    api.CloseDesktop.restype = w.BOOL
    desktop = api.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return False
    try:
        name, needed = ctypes.create_unicode_buffer(256), w.DWORD()
        return bool(api.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)) and name.value.casefold() == 'default')
    finally:
        api.CloseDesktop(desktop)
