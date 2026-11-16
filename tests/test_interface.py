import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.core import parse_accounts
from desktop.storage import Vault

TEXT = "owner@example.test----Dummy password!----backup@example.test----JBSWY3DPEHPK3PXP"
KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class ExportTests(unittest.TestCase):
    def setUp(self):
        try:
            self.exports = importlib.import_module("desktop.exports")
        except ModuleNotFoundError:
            self.fail("desktop.exports has not been implemented")
        self.accounts = parse_accounts(TEXT)

    def test_summary_contains_no_secrets(self):
        result = self.exports.render_export(
            "summary", self.accounts, {"owner@example.test": {"status": "success", "key": KEY}}
        )
        self.assertIn("owner@example.test", result)
        self.assertNotIn(KEY, result)
        self.assertNotIn("Dummy password!", result)

    def test_full_export_uses_new_key(self):
        result = self.exports.render_export(
            "full", self.accounts, {"owner@example.test": {"status": "success", "key": KEY}}
        )
        self.assertIn("Dummy password!", result)
        self.assertIn(KEY, result)
        self.assertNotIn("JBSWY3DPEHPK3PXP", result)

    def test_full_export_rejects_unknown_state(self):
        for status in ("review", "running"):
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    self.exports.render_export(
                        "full", self.accounts, {"owner@example.test": {"status": status, "key": KEY}}
                    )

    def test_candidate_export_includes_review_label(self):
        result = self.exports.render_export(
            "recovery", [], {"owner@example.test": {"status": "review", "key": KEY}}
        )
        self.assertIn(KEY, result)
        self.assertIn("待人工核对", result)

    def test_success_export_excludes_unconfirmed_keys(self):
        result = self.exports.render_export(
            "keys", [], {"owner@example.test": {"status": "review", "key": KEY}}
        )
        self.assertNotIn(KEY, result)


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def test_describe_url_strips_query_and_fragment(self):
        from desktop.backend import describe_url

        url = "https://accounts.google.com/v3/signin/identifier?dsh=secret&x=1#frag"
        self.assertEqual(describe_url(url), "https://accounts.google.com/v3/signin/identifier")
        self.assertEqual(describe_url("not a url"), "not a url")
        self.assertEqual(describe_url(None), "None")

    async def test_failure_log_includes_page_context(self):
        from desktop.backend import BrowserExecutor

        class API:
            def create_browser(self, **kwargs):
                return {"success": True, "data": {"id": "owned"}}

            def open_browser(self, bid):
                return {"success": True, "data": {"ws": "ws://x"}}

            def close_browser(self, bid):
                return {"success": True}

            def delete_browser(self, bid):
                return {"success": True}

        class Page:
            url = "https://accounts.google.com/v3/signin/identifier?dsh=secret"

        class Context:
            pages = [Page()]

        class Browser:
            contexts = [Context()]

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

        logs = []

        async def fake_change(page, info, log_callback=None, key_prepared_callback=None):
            return False, "密码错误", None

        with (
            patch("playwright.async_api.async_playwright", lambda: PWCM()),
            patch("src.google.backend.change_2fa_service.change_2fa_for_account", fake_change),
        ):
            success, message = await BrowserExecutor(API())(
                parse_accounts(TEXT)[0], lambda key: None, logs.append)
        self.assertFalse(success)
        self.assertEqual(message, "密码错误")
        self.assertTrue(
            any("dsh=secret" not in m and "页面：https://accounts.google.com/v3/signin/identifier" in m
                for m in logs)
        )


class UITests(unittest.TestCase):
    def setUp(self):
        try:
            self.ui = importlib.import_module("desktop.ui")
        except ModuleNotFoundError:
            self.fail("desktop.ui has not been implemented")
        import tkinter as tk
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = self.ui.App(self.root, Vault(Path(self.temp.name) / "vault.bin"))
        self.root.update()

    def test_import_displays_only_email_and_status(self):
        self.app.load_text(TEXT)
        rows = self.app.table.get_children()
        self.assertEqual(len(rows), 1)
        display = str(self.app.table.item(rows[0]))
        self.assertIn("owner@example.test", display)
        self.assertNotIn("Dummy password!", display)
        self.assertNotIn("JBSWY3DPEHPK3PXP", display)

    def test_result_event_updates_table(self):
        self.app.load_text(TEXT)
        self.app.events.put({"type": "status", "email": "owner@example.test", "status": "success"})
        self.app.poll()
        self.assertIn("已成功", str(self.app.table.item(self.app.table.get_children()[0])))

    def test_finished_event_reenables_buttons(self):
        self.app.set_busy(True)
        self.app.events.put({"type": "finished"})
        self.app.poll()
        self.assertFalse(self.app.busy)
        self.assertEqual(str(self.app.start_button["state"]), "normal")

    def test_log_lines_are_persisted_to_run_log(self):
        import desktop.ui as ui_module

        log_path = Path(self.temp.name) / "data" / "run.log"
        with patch.object(ui_module, "data_directory", return_value=log_path.parent):
            self.app.append_log("diagnostic marker")
        self.assertIn("diagnostic marker", log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
