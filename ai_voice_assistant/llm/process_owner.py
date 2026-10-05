"""Start CLI trees suspended inside a private Windows Job, then resume them."""
import asyncio
import ctypes
from ctypes import wintypes as w
import os


def resume_owned_process(job, pid):
    from ui.windows_job import checked
    api = job.api
    process = checked(api.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid))
    try:
        checked(api.AssignProcessToJobObject(job.handle, process))
    finally:
        api.CloseHandle(process)

    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('tid', w.DWORD),
                    ('pid', w.DWORD), ('priority', w.LONG), ('delta', w.LONG), ('flags', w.DWORD)]
    api.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    api.CreateToolhelp32Snapshot.restype = w.HANDLE
    api.Thread32First.argtypes = api.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
    api.Thread32First.restype = api.Thread32Next.restype = w.BOOL
    api.OpenThread.argtypes, api.OpenThread.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    snapshot = api.CreateToolhelp32Snapshot(4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        more = api.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.pid == pid:
                thread = checked(api.OpenThread(2, False, entry.tid))
                try:
                    if api.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
                finally:
                    api.CloseHandle(thread)
            more = api.Thread32Next(snapshot, ctypes.byref(entry))
        raise RuntimeError('找不到 CLI 啟動執行緒')
    finally:
        api.CloseHandle(snapshot)


async def create_owned_subprocess(*command, **options):
    job = None
    process = None
    if os.name == 'nt':
        from ui.windows_job import WindowsJob
        job = WindowsJob()
        options['creationflags'] = options.get('creationflags', 0) | 4  # CREATE_SUSPENDED
    try:
        process = await asyncio.create_subprocess_exec(*command, **options)
        if job is not None:
            if type(process.pid) is int and isinstance(process, asyncio.subprocess.Process):
                resume_owned_process(job, process.pid)
            else:
                # Unit-test transports do not represent a native Windows process.
                job.close()
                job = None
        return process, job
    except BaseException:
        if job is not None:
            job.close()
        if process is not None and type(process.pid) is int and process.returncode is None:
            process.kill()  # If assignment failed, the suspended root has no children.
            await asyncio.wait_for(process.wait(), timeout=5)
        raise
