import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.google.backend import change_2fa_service as service
from src.google.backend import google_auth

KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class RotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_failure_prevents_submission(self):
        page = SimpleNamespace(goto=AsyncMock(), wait_for_load_state=AsyncMock())
        helpers = {
            "google_login": AsyncMock(return_value=(True, "ok", None)),
            "_extract_logged_in_email": AsyncMock(return_value="owner@example.test"),
            "_check_need_password": AsyncMock(return_value=False),
            "_check_need_2fa_verification": AsyncMock(return_value=False),
            "_click_change_authenticator_button": AsyncMock(return_value=True),
            "_click_cant_scan_button": AsyncMock(return_value=True),
            "_extract_new_2fa_key": AsyncMock(return_value=KEY),
            "_click_next_button": AsyncMock(return_value=True),
            "_verify_new_2fa": AsyncMock(return_value=(True, "123456")),
        }

        def cannot_save(key):
            raise OSError("disk full")

        with patch.multiple(service, **helpers):
            result = await service.change_2fa_for_account(
                page, {"email": "owner@example.test"}, key_prepared_callback=cannot_save,
            )
        self.assertFalse(result[0])
        helpers["_click_next_button"].assert_not_awaited()
        helpers["_verify_new_2fa"].assert_not_awaited()

    async def test_mismatched_identity_never_opens_change_dialog(self):
        page = SimpleNamespace(goto=AsyncMock(), wait_for_load_state=AsyncMock())
        change = AsyncMock(return_value=True)
        with (
            patch.object(service, "google_login", AsyncMock(return_value=(True, "ok", None))),
            patch.object(service, "_extract_logged_in_email", AsyncMock(return_value="other@example.test")),
            patch.object(service, "_click_change_authenticator_button", change),
        ):
            result = await service.change_2fa_for_account(page, {"email": "owner@example.test"})
        self.assertFalse(result[0])
        change.assert_not_awaited()

    async def test_disappearing_verify_button_is_not_success(self):
        class Locator:
            @property
            def first(self):
                return self

            async def count(self):
                return 0

            async def is_visible(self, **kwargs):
                return False

        class Page:
            def locator(self, *args, **kwargs):
                return Locator()

            def get_by_role(self, *args, **kwargs):
                return Locator()

            def get_by_text(self, *args, **kwargs):
                # Click is allowed but subsequent lack of evidence cannot
                # be interpreted as successful enrollment.
                return SimpleNamespace(count=AsyncMock(return_value=1), first=SimpleNamespace(click=AsyncMock()))

        with patch.object(service.asyncio, "sleep", AsyncMock()):
            result = await service._click_verify_button(Page(), KEY, lambda msg: None)
        self.assertEqual(result, (False, False))

    def test_raw_backend_debug_output_is_suppressed(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            service.print("sensitive sample")
            google_auth.print("sensitive sample")
        self.assertEqual(output.getvalue(), "")

    async def test_identity_confirmed_via_page_content_fallback(self):
        """Avatar extraction can fail on settings pages; content still names the account."""
        page = SimpleNamespace(content=AsyncMock(return_value="<html>mmoula0233@gmail.com …</html>"))
        with patch.object(service, "_extract_logged_in_email", AsyncMock(return_value=None)):
            confirmed = await service._confirm_target_account(page, "mmoula0233@gmail.com", lambda m: None)
        self.assertTrue(confirmed)

    async def test_identity_mismatch_fails_closed(self):
        page = SimpleNamespace(content=AsyncMock(return_value="<html>other-account here</html>"))
        with patch.object(service, "_extract_logged_in_email", AsyncMock(return_value="other@example.test")):
            confirmed = await service._confirm_target_account(page, "mmoula0233@gmail.com", lambda m: None)
        self.assertFalse(confirmed)

    async def test_identity_polls_before_giving_up(self):
        page = SimpleNamespace(content=AsyncMock(return_value="<html>loading</html>"))
        attempts = {"n": 0}

        async def extract(page):
            attempts["n"] += 1
            return "mmoula0233@gmail.com" if attempts["n"] >= 3 else None

        with patch.object(service, "_extract_logged_in_email", extract), patch.object(
            service.asyncio, "sleep", AsyncMock()
        ):
            confirmed = await service._confirm_target_account(page, "mmoula0233@gmail.com", lambda m: None)
        self.assertTrue(confirmed)
        self.assertEqual(attempts["n"], 3)
