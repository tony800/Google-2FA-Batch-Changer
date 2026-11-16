import importlib
import tempfile
import threading
import unittest
from pathlib import Path

ACCOUNT = "owner@example.test----Demo password!----backup@example.test----JBSWY3DPEHPK3PXP"
NEW_KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class CoreTests(unittest.TestCase):
    def setUp(self):
        try:
            self.core = importlib.import_module("desktop.core")
        except ModuleNotFoundError:
            self.fail("desktop.core has not been implemented")

    def test_parse_preserves_password_and_normalizes_key(self):
        account = self.core.parse_accounts(ACCOUNT)[0]
        self.assertEqual(account.password, "Demo password!")
        self.assertEqual(account.secret, "JBSWY3DPEHPK3PXP")
        self.assertNotIn(account.password, repr(account))
        self.assertNotIn(account.secret, repr(account))

    def test_rejects_malformed_without_echoing_credentials(self):
        for text in ("bad----sensitive-password", ACCOUNT + "----extra",
                     ACCOUNT.replace("JBSWY3DPEHPK3PXP", "not-a-key")):
            with self.subTest(text_length=len(text)):
                with self.assertRaises(ValueError) as error:
                    self.core.parse_accounts(text)
                self.assertNotIn("sensitive-password", str(error.exception))
                self.assertNotIn("Demo password!", str(error.exception))

    def test_rejects_duplicate_accounts(self):
        with self.assertRaises(ValueError):
            self.core.parse_accounts(ACCOUNT + "\n" + ACCOUNT.upper())

    def test_allows_empty_recovery_and_comments(self):
        text = "# Example\n\n" + ACCOUNT.replace("backup@example.test", "")
        self.assertEqual(len(self.core.parse_accounts(text)), 1)

    def test_redacts_password_keys_codes_urls_and_prefixes(self):
        account = self.core.parse_accounts(ACCOUNT)[0]
        redact = self.core.Redactor([account])
        text = f"{account.password} {account.secret} {NEW_KEY} 123456 https://example.test/?token=abcdef"
        safe = redact(text)
        for sensitive in (account.password, account.secret, NEW_KEY, "123456", "token=abcdef"):
            self.assertNotIn(sensitive, safe)


class StorageTests(unittest.TestCase):
    def setUp(self):
        try:
            self.storage = importlib.import_module("desktop.storage")
        except ModuleNotFoundError:
            self.fail("desktop.storage has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "vault.bin"

    def test_dpapi_roundtrip_and_ciphertext_contains_no_secret(self):
        store = self.storage.Vault(self.path)
        store.put("owner@example.test", "review", key=NEW_KEY)
        self.assertNotIn(NEW_KEY.encode(), self.path.read_bytes())
        reopened = self.storage.Vault(self.path)
        self.assertEqual(reopened.get("owner@example.test")["key"], NEW_KEY)

    def test_corrupt_vault_fails_closed(self):
        self.path.write_bytes(b"not a valid DPAPI vault")
        with self.assertRaises(ValueError):
            self.storage.Vault(self.path)

    def test_failed_write_leaves_memory_and_disk_unchanged(self):
        from unittest.mock import patch
        store = self.storage.Vault(self.path)
        store.put("owner@example.test", "review", key=NEW_KEY)
        before = self.path.read_bytes()
        with patch("desktop.storage.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                store.put("owner@example.test", "success", key=NEW_KEY)
        self.assertEqual(store.get("owner@example.test")["status"], "review")
        self.assertEqual(self.path.read_bytes(), before)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.core = importlib.import_module("desktop.core")
            self.runner = importlib.import_module("desktop.runner")
            self.storage = importlib.import_module("desktop.storage")
        except ModuleNotFoundError:
            self.fail("desktop runner has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = self.storage.Vault(Path(self.temp.name) / "vault.bin")
        self.accounts = self.core.parse_accounts(ACCOUNT + "\n" + ACCOUNT.replace("owner@", "second@"))
        self.events = []
        self.stop = threading.Event()

    async def test_saves_each_account_before_starting_next(self):
        async def execute(account, prepared, log):
            if account.email.startswith("second"):
                self.assertEqual(self.vault.get(self.accounts[0].email)["status"], "success")
            prepared(NEW_KEY)
            self.assertEqual(self.vault.get(account.email)["status"], "review")
            return True, "ok"
        await self.runner.run_accounts(self.accounts, self.vault, execute, self.events.append, self.stop)
        self.assertEqual(self.vault.get(self.accounts[1].email)["status"], "success")

    async def test_unknown_result_retains_key_and_blocks_rerun(self):
        calls = []
        async def execute(account, prepared, log):
            calls.append(account.email)
            prepared(NEW_KEY)
            return False, "结果未知"
        await self.runner.run_accounts(self.accounts, self.vault, execute, self.events.append, self.stop)
        self.assertEqual(self.vault.get(self.accounts[0].email)["key"], NEW_KEY)
        await self.runner.run_accounts(self.accounts, self.vault, execute, self.events.append, self.stop)
        self.assertEqual(len(calls), 2)

    async def test_stop_finishes_current_and_skips_queued_accounts(self):
        calls = []
        async def execute(account, prepared, log):
            calls.append(account.email)
            prepared(NEW_KEY)
            self.stop.set()
            return True, "ok"
        await self.runner.run_accounts(self.accounts, self.vault, execute, self.events.append, self.stop)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.vault.get(self.accounts[0].email)["status"], "success")
        self.assertIsNone(self.vault.get(self.accounts[1].email))

    async def test_restart_running_requires_manual_review(self):
        self.vault.put(self.accounts[0].email, "running")
        calls = []
        async def execute(account, prepared, log):
            calls.append(account.email)
            return False, "需人工核对"
        await self.runner.run_accounts(self.accounts[:1], self.vault, execute, self.events.append, self.stop)
        self.assertEqual(calls, [])

    async def test_pending_write_failure_never_submits_key(self):
        from unittest.mock import patch
        submitted = []
        async def execute(account, prepared, log):
            with patch.object(self.vault, "put", side_effect=OSError("disk full")):
                prepared(NEW_KEY)
            submitted.append(True)
            return True, "ok"
        await self.runner.run_accounts(self.accounts[:1], self.vault, execute, self.events.append, self.stop)
        self.assertEqual(submitted, [])
        self.assertTrue(self.stop.is_set())

    async def test_invalid_concurrency_rejected(self):
        with self.assertRaises(ValueError):
            await self.runner.run_accounts([], self.vault, None, self.events.append, self.stop, concurrency=0)


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_failure_is_not_success(self):
        try:
            backend = importlib.import_module("desktop.backend")
        except ModuleNotFoundError:
            self.fail("desktop.backend has not been implemented")
        class API:
            def health_check(self):
                return {"success": False, "msg": "unavailable"}
        with self.assertRaises(ConnectionError):
            await backend.check_connection(API())

    async def test_only_created_browser_is_closed_and_deleted(self):
        try:
            backend = importlib.import_module("desktop.backend")
            core = importlib.import_module("desktop.core")
        except ModuleNotFoundError:
            self.fail("desktop.backend has not been implemented")
        class API:
            def __init__(self):
                self.closed = []
                self.deleted = []
                self.options = {}
            def create_browser(self, **kwargs):
                self.options = kwargs
                return {"success": True, "data": {"id": "owned"}}
            def open_browser(self, bid):
                return {"success": False}
            def close_browser(self, bid):
                self.closed.append(bid)
                return {"success": True}
            def delete_browser(self, bid):
                self.deleted.append(bid)
                return {"success": True}
        api = API()
        success, message = await backend.BrowserExecutor(api)(
            core.parse_accounts(ACCOUNT)[0], lambda key: None, lambda msg: None)
        self.assertFalse(success)
        self.assertIn("打开", message)
        self.assertEqual(api.closed, ["owned"])
        self.assertEqual(api.deleted, ["owned"])
        self.assertNotIn("Demo password!", str(api.options))
        self.assertNotIn("JBSWY3DPEHPK3PXP", str(api.options))


if __name__ == "__main__":
    unittest.main()
