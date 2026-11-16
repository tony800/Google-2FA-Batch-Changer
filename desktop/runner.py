import asyncio
import re
import threading

from .core import Redactor, normalize_key

TAGGED = re.compile(r"(?:PROGRESS|RESULT):(.*)", re.S)


async def run_accounts(accounts, vault, execute, emit, stop=None, concurrency=1, batch_size=10):
    if not 1 <= concurrency <= 5 or not 1 <= batch_size <= 100:
        raise ValueError("并发数须为 1–5，每批数量须为 1–100")
    if stop is None:
        stop = threading.Event()
    redact = Redactor(accounts)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(account):
        async with semaphore:
            if stop.is_set():
                emit({"type": "status", "email": account.email, "status": "stopped"})
                return
            previous = vault.get(account.email)
            if previous and previous["status"] in {"success", "review", "running"}:
                status = "skipped" if previous["status"] == "success" else "blocked"
                emit({"type": "status", "email": account.email, "status": status})
                return
            key = None
            checkpoint_failed = False

            def prepared(value):
                nonlocal key, checkpoint_failed
                try:
                    value = normalize_key(value)
                    vault.put(account.email, "review", key=value)
                    key = value
                except Exception:
                    checkpoint_failed = True
                    stop.set()
                    raise

            def log(message):
                # Only curated tagged lines and stage markers leave the
                # automation layer, and tagged text goes through the redactor
                # so an accidental credential never reaches the UI.
                tagged = TAGGED.search(str(message))
                match = re.search(r"\bStep (\d+):", str(message))
                if tagged:
                    emit({"type": "log", "message": redact(f"{account.email} · {tagged.group(1).strip()}")})
                elif match:
                    emit({"type": "log", "message": f"{account.email} · 自动化步骤 {match[1]}"})
                elif message in {
                    "浏览器连接关闭失败",
                    "本任务临时窗口清理失败，请在 BitBrowser 手动核对",
                }:
                    emit({"type": "log", "message": f"{account.email} · {message}"})

            try:
                vault.put(account.email, "running")
                emit({"type": "status", "email": account.email, "status": "running"})
                log("Step 1:")
                success, message = await execute(account, prepared, log)
                if checkpoint_failed:
                    raise OSError("恢复记录保存失败")
                status = "success" if success and key else ("review" if key else "failed")
                vault.put(account.email, status, key=key)
                emit({"type": "status", "email": account.email, "status": status})
                if not success:
                    emit({"type": "log", "message": redact(f"{account.email} · {message or '原因未知，请人工核对'}")})
            except Exception as error:
                # Keep running/review on disk if the persistence outcome is
                # unknown. Never replace a prepared key with a failure record.
                stop.set()
                emit({"type": "status", "email": account.email, "status": "review"})
                emit({"type": "log", "message": redact(
                    f"{account.email} · 发生 {type(error).__name__}，已停止后续调度；请核对恢复记录"
                )})

    for start in range(0, len(accounts), batch_size):
        if stop.is_set():
            for account in accounts[start:]:
                emit({"type": "status", "email": account.email, "status": "stopped"})
            break
        await asyncio.gather(*(one(account) for account in accounts[start:start + batch_size]))
