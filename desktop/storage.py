import copy
import ctypes
import json
import os
import tempfile
import threading
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    """Windows DPAPI, current-user scope; no plaintext fallback."""
    if os.name != "nt":
        raise OSError("加密存储仅支持 Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("无法加密或解密恢复记录，请勿删除原文件；需使用原 Windows 用户核对")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def data_directory():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Google2FADesktop"


class Vault:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "recovery.bin"
        self.lock = threading.RLock()
        self.records = {}
        if self.path.exists():
            try:
                content = json.loads(protect(self.path.read_bytes(), decrypt=True))
                if content.get("version") != 1 or not isinstance(content.get("records"), dict):
                    raise ValueError()
                for entry in content["records"].values():
                    if not isinstance(entry, dict) or entry.get("status") not in {
                        "running", "review", "success", "failed",
                    }:
                        raise ValueError()
                self.records = content["records"]
            except (ValueError, TypeError, AttributeError):
                raise ValueError("恢复记录损坏或无法解密，请保留文件并使用原 Windows 用户核对") from None

    def get(self, email):
        with self.lock:
            return copy.deepcopy(self.records.get(email.lower()))

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.records)

    def put(self, email, status, key=None):
        if status not in {"running", "review", "success", "failed"}:
            raise ValueError("无效状态")
        with self.lock:
            records = copy.deepcopy(self.records)
            records[email.lower()] = {
                "status": status, "key": key,
                "updated": datetime.now(timezone.utc).isoformat(),
            }
            data = protect(json.dumps({"version": 1, "records": records}).encode("utf-8"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(prefix="recovery-", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
                self.records = records
            finally:
                if os.path.exists(name):
                    os.unlink(name)
