"""Fit the owned Tk window to its monitor in native desktop coordinates.

Tk 8.6 fullscreen can use DPI-virtualized screen dimensions on Windows. CTk's
geometry scaling cannot correct that native transition. Keep fullscreen enabled
and fit the actual HWND to rcMonitor (including the taskbar area), not rcWork.
"""
import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass


class MonitorInfo(ctypes.Structure):
    _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def from_rect(cls,rect):
        return cls(rect.left,rect.top,rect.right,rect.bottom)

    @property
    def width(self):
        return self.right-self.left

    @property
    def height(self):
        return self.bottom-self.top


class FullscreenHost:
    def __init__(self,tk_hwnd):
        self.api=ctypes.WinDLL('user32',use_last_error=True)
        signatures={
            'GetAncestor': ([w.HWND,w.UINT],w.HWND),
            'MonitorFromWindow': ([w.HWND,w.DWORD],w.HANDLE),
            'GetMonitorInfoW': ([w.HANDLE,ctypes.POINTER(MonitorInfo)],w.BOOL),
            'GetWindowRect': ([w.HWND,ctypes.POINTER(w.RECT)],w.BOOL),
            'GetClientRect': ([w.HWND,ctypes.POINTER(w.RECT)],w.BOOL),
            'SetWindowPos': ([w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT],w.BOOL),
        }
        for name,(args,result) in signatures.items():
            function=getattr(self.api,name)
            function.argtypes,function.restype=args,result
        self.hwnd=self._checked(self.api.GetAncestor(tk_hwnd,2))

    @staticmethod
    def _checked(value):
        if not value: raise ctypes.WinError(ctypes.get_last_error())
        return value

    def monitor_bounds(self,work_area=False):
        monitor=self._checked(self.api.MonitorFromWindow(self.hwnd,2))
        info=MonitorInfo();info.size=ctypes.sizeof(info)
        self._checked(self.api.GetMonitorInfoW(monitor,ctypes.byref(info)))
        bounds=Bounds.from_rect(info.work if work_area else info.monitor)
        if bounds.width<=0 or bounds.height<=0: raise RuntimeError('Monitor bounds invalid')
        return bounds

    def window_bounds(self):
        rect=w.RECT()
        self._checked(self.api.GetWindowRect(self.hwnd,ctypes.byref(rect)))
        return Bounds.from_rect(rect)

    def client_bounds(self):
        rect=w.RECT()
        self._checked(self.api.GetClientRect(self.hwnd,ctypes.byref(rect)))
        return Bounds.from_rect(rect)

    def fit(self):
        target=self.monitor_bounds()
        if self.window_bounds()!=target:
            # Preserve z-order/focus. SetWindowPos receives native coordinates;
            # running them through CTk.geometry would apply DPI scaling again.
            self._checked(self.api.SetWindowPos(self.hwnd,None,target.left,target.top,
                target.width,target.height,0x0004|0x0010|0x0020))
        return target
