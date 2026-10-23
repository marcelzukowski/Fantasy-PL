"""Make a Windows venv redirector's child exit when its owning process is cancelled."""

import ctypes
import os
import sys
import threading


def watch_parent():
    if sys.platform != "win32":
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, os.getppid())
    if not handle:
        # The launcher may already have been cancelled while Python was starting.
        if ctypes.get_last_error() == 87:
            os._exit(0)
        raise OSError(
            ctypes.get_last_error(), "Cannot monitor the owning comparator worker process"
        )

    def wait():
        try:
            if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
                os._exit(0)
        finally:
            kernel.CloseHandle(handle)

    threading.Thread(target=wait, daemon=True, name="manual-worker-parent").start()
