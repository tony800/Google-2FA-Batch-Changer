import asyncio
from urllib.parse import urlsplit
from uuid import uuid4

TEMP_REMARK = "Google 2FA Desktop temporary session"


def describe_url(url):
    """scheme://host/path only — query strings may carry session tokens."""
    try:
        parts = urlsplit(str(url))
        if not parts.netloc:
            return str(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")
    except Exception:
        return ""


def make_api(port=54345):
    from src.bit_api import BitBrowserAPI
    return BitBrowserAPI(f"http://127.0.0.1:{int(port)}")


async def cleanup_temp_sessions(api, remark=TEMP_REMARK):
    """Delete only leftover windows this tool created, never user profiles."""
    removed, page, seen = 0, 0, set()
    while page <= 10:
        listing = await asyncio.to_thread(api.list_browsers, page, 100)
        rows = ((listing or {}).get("data") or {}).get("list") or []
        if not rows or all(row.get("id") in seen for row in rows):
            break
        for row in rows:
            seen.add(row.get("id"))
            if (row.get("remark") or "").strip() == remark:
                result = await asyncio.to_thread(api.delete_browser, row.get("id"))
                if (result or {}).get("success"):
                    removed += 1
        page += 1
    return removed


async def check_connection(api):
    result = await asyncio.to_thread(api.health_check)
    if not isinstance(result, dict) or result.get("success") is not True:
        raise ConnectionError("无法连接 BitBrowser，请先启动、登录并开启 Local API")
    return True


class BrowserExecutor:
    def __init__(self, api):
        self.api = api

    async def __call__(self, account, prepared, log):
        from playwright.async_api import async_playwright

        from src.google.backend.change_2fa_service import change_2fa_for_account
        result = await asyncio.to_thread(
            self.api.create_browser, name=f"2FA-{uuid4().hex[:12]}",
            remark="Google 2FA Desktop temporary session",
            syncCookies=False, syncLocalStorage=False, syncIndexedDb=False,
            syncAuthorization=False, credentialsEnableService=False,
        )
        if not result.get("success"):
            return False, f"创建浏览器窗口失败：{result.get('msg') or '未知错误'}"
        bid = result.get("data", {}).get("id")
        if not bid:
            return False, "创建浏览器窗口失败：接口未返回窗口 ID"
        try:
            opened = await asyncio.to_thread(self.api.open_browser, bid)
            if not opened.get("success"):
                return False, f"打开浏览器窗口失败：{opened.get('msg') or '未知错误'}"
            endpoint = opened.get("data", {}).get("ws")
            if isinstance(endpoint, dict):
                endpoint = endpoint.get("puppeteer")
            if not isinstance(endpoint, str):
                return False, "无法获取浏览器调试连接，请重试或检查 BitBrowser 版本"
            async with async_playwright() as playwright:
                try:
                    browser = await playwright.chromium.connect_over_cdp(endpoint)
                except Exception:
                    return False, "连接浏览器调试端口失败，请重试该账号"
                try:
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    page = context.pages[0] if context.pages else await context.new_page()
                    success, message, _ = await change_2fa_for_account(
                        page, account.backend_info(), log_callback=log,
                        key_prepared_callback=prepared,
                    )
                    if not success:
                        log(f"RESULT:{message}｜失败时页面：{describe_url(page.url)}")
                    return success, message
                finally:
                    # Closing this connection never targets other profiles.
                    try:
                        await browser.close()
                    except Exception:
                        log("浏览器连接关闭失败")
        finally:
            for index, action in enumerate((self.api.close_browser, self.api.delete_browser)):
                for attempt in range(3):
                    try:
                        result = await asyncio.to_thread(action, bid)
                        if result.get("success") or attempt == 2:
                            break
                        # Deletion can race the window process shutting down.
                        await asyncio.sleep(1 + attempt)
                    except Exception:
                        if attempt == 2:
                            break
                        await asyncio.sleep(1 + attempt)
                else:
                    continue
                if not result.get("success"):
                    log("本任务临时窗口清理失败，请在 BitBrowser 手动核对")
