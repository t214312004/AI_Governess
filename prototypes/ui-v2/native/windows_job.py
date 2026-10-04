"""Launch a process suspended, assign it to a private job, then resume it.

No PID-based termination. Closing the job terminates only its members, including
nested Chromium jobs. Handles are non-inheritable. Windows 10/11 only.
See https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
"""
import ctypes
from ctypes import wintypes as w
import subprocess


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', w.DWORD), ('min_working', ctypes.c_size_t),
                ('max_working', ctypes.c_size_t), ('active_limit', w.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', ctypes.c_ulonglong * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class StartupInfo(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                ('title', w.LPWSTR), ('x', w.DWORD), ('y', w.DWORD),
                ('x_size', w.DWORD), ('y_size', w.DWORD), ('x_chars', w.DWORD),
                ('y_chars', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', ctypes.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


def win_api():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'IsProcessInJob': ([w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL,
                            w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo)], w.BOOL),
        'ResumeThread': ([w.HANDLE], w.DWORD),
        'CloseHandle': ([w.HANDLE], w.BOOL),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'GetExitCodeProcess': ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


class JobProcess:
    """The subset of Popen used by HtmlWhiteboardRenderer, with owned handles."""
    def __init__(self, api, handle, pid):
        self.api, self.handle, self.pid = api, handle, pid
        self.returncode = None

    def poll(self):
        if self.handle is None:
            return self.returncode
        result = self.api.WaitForSingleObject(self.handle, 0)
        if result == 258:
            return None
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = w.DWORD()
        checked(self.api.GetExitCodeProcess(self.handle, ctypes.byref(code)))
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        result = self.api.WaitForSingleObject(self.handle, 0xFFFFFFFF if timeout is None else int(timeout * 1000))
        if result == 258:
            raise subprocess.TimeoutExpired('owned browser', timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if self.poll() is None:
            checked(self.api.TerminateProcess(self.handle, 1))

    kill = terminate

    def close(self):
        if self.handle:
            checked(self.api.CloseHandle(self.handle))
            self.handle = None


class WindowsJob:
    def __init__(self):
        self.api = win_api()
        self.handle = checked(self.api.CreateJobObjectW(None, None))
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            checked(self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except Exception:
            self.close()
            raise

    def launch(self, command):
        startup, info = StartupInfo(), ProcessInfo()
        startup.cb = ctypes.sizeof(startup)
        line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        checked(self.api.CreateProcessW(command[0], line, None, None, False,
                                        0x00000004 | 0x08000000, None, None,
                                        ctypes.byref(startup), ctypes.byref(info)))
        process = JobProcess(self.api, info.process, info.pid)
        try:
            checked(self.api.AssignProcessToJobObject(self.handle, info.process))
            if self.api.ResumeThread(info.thread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return process
        except Exception:
            try:
                process.terminate()
                process.wait(2)
            finally:
                process.close()
            raise
        finally:
            self.api.CloseHandle(info.thread)

    def pids(self):
        capacity = 64
        while capacity <= 4096:
            class PidList(ctypes.Structure):
                _fields_ = [('assigned', w.DWORD), ('count', w.DWORD), ('ids', ctypes.c_size_t * capacity)]
            result = PidList()
            ok = self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(result), ctypes.sizeof(result), None)
            if ok and result.count <= capacity:
                return tuple(int(result.ids[index]) for index in range(result.count))
            if not ok and ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(ctypes.get_last_error())
            capacity *= 2
        raise RuntimeError('HTML process count exceeded safety bound')

    def owns(self, pid):
        # Revalidate membership using a handle before attaching a window. A PID
        # enumerated earlier might already have exited and been reused.
        handle = self.api.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            member = w.BOOL()
            return bool(self.api.IsProcessInJob(handle, self.handle, ctypes.byref(member)) and member.value)
        finally:
            self.api.CloseHandle(handle)

    def close(self):
        if self.handle:
            checked(self.api.CloseHandle(self.handle))
            self.handle = None
