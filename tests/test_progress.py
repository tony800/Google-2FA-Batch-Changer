import unittest
from unittest.mock import patch

from desktop.core import parse_accounts
from desktop.runner import run_accounts
from desktop.storage import Vault

ACCOUNT = "owner@example.test----Demo password!----backup@example.test----JBSWY3DPEHPK3PXP"
KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class RunnerReasonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.accounts = parse_accounts(ACCOUNT)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Vault(Path(self.temp.name) / "vault.bin")
        self.events = []

    def make_events(self):
        self.events = []

    async def test_progress_tag_is_passsed_to_ui(self):
        self.make_events()

        async def execute(account, prepared, log):
            log("PROGRESS:已填写账号邮箱")
            return False, "无法登录"

        await run_accounts(self.accounts, self.vault, execute, self.events.append, None)
        messages = [e["message"] for e in self.events if e["type"] == "log"]
        self.assertTrue(any("已填写账号邮箱" in m for m in messages))

    async def test_result_reason_reaches_log_and_status_failed(self):
        self.make_events()

        async def execute(account, prepared, log):
            return False, "最终验证失败"

        await run_accounts(self.accounts, self.vault, execute, self.events.append, None)
        messages = [e["message"] for e in self.events if e["type"] == "log"]
        self.assertTrue(any("最终验证失败" in m for m in messages))
        self.assertEqual(self.vault.get(self.accounts[0].email)["status"], "failed")

    async def test_progress_and_result_lines_are_redacted(self):
        self.make_events()

        async def execute(account, prepared, log):
            log(f"PROGRESS:验证码 123456 已输入 {KEY}")
            log(f"RESULT:密码 {self.accounts[0].password} 泄漏测试")
            return False, "失败"

        await run_accounts(self.accounts, self.vault, execute, self.events.append, None)
        joined = " ".join(e.get("message", "") for e in self.events)
        self.assertNotIn(KEY, joined)
        self.assertNotIn("123456", joined)
        self.assertNotIn(self.accounts[0].password, joined)

    async def test_silent_raw_lines_never_pass_filter(self):
        self.make_events()

        async def execute(account, prepared, log):
            log(f"[Change2FA] raw key {KEY}")
            return False, "失败"

        await run_accounts(self.accounts, self.vault, execute, self.events.append, None)
        joined = " ".join(e.get("message", "") for e in self.events if e["type"] == "log")
        self.assertNotIn(KEY, joined)


class ExecutorReasonTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_failure_returns_reason_without_cleanup(self):
        from desktop.backend import BrowserExecutor

        class API:
            def __init__(self):
                self.calls = []

            def create_browser(self, **kwargs):
                return {"success": False, "msg": "token 失效，请检查登录状态"}

            def close_browser(self, bid):
                self.calls.append(("close", bid))

            def delete_browser(self, bid):
                self.calls.append(("delete", bid))

        api = API()
        success, message = await BrowserExecutor(api)(
            parse_accounts(ACCOUNT)[0], lambda key: None, lambda msg: None)
        self.assertFalse(success)
        self.assertIn("创建", message)
        self.assertEqual(api.calls, [])

    async def test_change_failure_message_is_logged(self):
        from desktop.backend import BrowserExecutor

        class Locator:
            @property
            def first(self):
                return self

            async def count(self):
                return 0

        class Context:
            pages = []

            async def new_page(self):
                return SimplePage()

        class SimplePage:
            url = "https://accounts.google.com/v3/signin/identifier?dsh=token"

        class Browser:
            contexts = []

            async def new_context(self):
                return Context()

            async def close(self):
                pass

        class Playwright:
            class chromium:
                @staticmethod
                async def connect_over_cdp(endpoint):
                    return Browser()

        class PWCM:
            async def __aenter__(self):
                return Playwright()

            async def __aexit__(self, *args):
                return False

        def fake_pw():
            return PWCM()

        class API:
            def create_browser(self, **kwargs):
                return {"success": True, "data": {"id": "owned"}}

            def open_browser(self, bid):
                return {"success": True, "data": {"ws": "ws://x"}}

            def close_browser(self, bid):
                return {"success": True}

            def delete_browser(self, bid):
                return {"success": True}

        logs = []

        async def fake_change(page, info, log_callback=None, key_prepared_callback=None):
            return False, "找不到更改按钮", None

        with (
            patch("playwright.async_api.async_playwright", fake_pw),
            patch("src.google.backend.change_2fa_service.change_2fa_for_account", fake_change),
        ):
            success, message = await BrowserExecutor(API())(
                parse_accounts(ACCOUNT)[0], lambda key: None, logs.append)
        self.assertFalse(success)
        self.assertEqual(message, "找不到更改按钮")
        self.assertTrue(any("找不到更改按钮" in m for m in logs))
        self.assertTrue(all("dsh=token" not in m for m in logs))

    async def test_cleanup_temp_sessions_removes_only_ours(self):
        from desktop.backend import cleanup_temp_sessions

        class API:
            def __init__(self):
                self.deleted = []

            def list_browsers(self, page, page_size):
                return {"success": True, "data": {"list": [
                    {"id": "ours", "remark": "Google 2FA Desktop temporary session"},
                    {"id": "theirs", "remark": "用户自己的窗口"},
                ]}}

            def delete_browser(self, bid):
                self.deleted.append(bid)
                return {"success": True}

        api = API()
        self.assertEqual(await cleanup_temp_sessions(api), 1)
        self.assertEqual(api.deleted, ["ours"])


if __name__ == "__main__":
    unittest.main()
