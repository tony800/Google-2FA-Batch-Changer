import ctypes
import json
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from desktop.storage import Vault
from desktop.ui import App


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    smoke = len(sys.argv) == 3 and sys.argv[1] == "--smoke-test"
    handle = kernel.CreateMutexW(None, False, "Local\\Google2FADesktop-v1" if not smoke else None)
    already_open = ctypes.get_last_error() == 183
    root = tk.Tk()
    root.withdraw()
    if not handle or already_open:
        messagebox.showinfo("Google 2FA", "工具已运行，请切换到已有窗口。", parent=root)
        root.destroy()
        if handle:
            kernel.CloseHandle(handle)
        return
    try:
        if smoke:
            with tempfile.TemporaryDirectory() as directory:
                app = App(root, Vault(Path(directory) / "test.bin"))
                app.load_text("smoke@example.test----Dummy!----backup@example.test----JBSWY3DPEHPK3PXP")
                root.update()
                from playwright.async_api import async_playwright
                from pyotp import TOTP

                from desktop.backend import make_api
                make_api()
                report = {
                    "gui": root.winfo_exists() == 1,
                    "rows": len(app.table.get_children()),
                    "backend_imports": callable(async_playwright) and callable(TOTP),
                    "account_operations": 0,
                }
                Path(sys.argv[2]).write_text(json.dumps(report), encoding="utf-8")
                app.close()
        else:
            App(root)
            root.deiconify()
            root.mainloop()
    except Exception as error:
        if smoke:
            raise
        messagebox.showerror(
            "启动失败", f"无法启动（{type(error).__name__}）。\n"
            "请保留 %LOCALAPPDATA%\\Google2FADesktop 下的恢复文件；"
            "如为解密问题，请使用原 Windows 用户打开。", parent=root,
        )
        root.destroy()
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
