import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.google.backend import google_auth

KEY = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class FakeLocator:
    def __init__(self, page, selector, has_text=None, children=None):
        self.page = page
        self.selector = selector
        self.has_text = has_text
        self.children = children or ()
        self.first = self

    def or_(self, other):
        return FakeLocator(self.page, "combined", children=(self, other))

    def filter(self, has_text=None, **kwargs):
        return FakeLocator(self.page, self.selector, has_text=has_text)

    async def count(self):
        if self.children:
            return max([await child.count() for child in self.children])
        if self.has_text is not None and "authenticator" not in str(self.has_text.pattern).lower():
            return 0
        return max(
            [self.page.locator_counts.get(part.strip(), 0) for part in self.selector.split(",")],
            default=0,
        )

    async def is_visible(self, **kwargs):
        return await self.count() > 0

    async def inner_text(self):
        return "sample"

    async def get_attribute(self, name):
        return None

    async def fill(self, value):
        self.page.filled[self.selector] = value

    async def click(self, **kwargs):
        if self.children:
            for child in self.children:
                if await child.count() > 0:
                    await child.click(**kwargs)
                    return
        self.page.clicks.append(self.selector)
        if self.page.on_click:
            self.page.on_click(self.selector)

    async def press(self, key):
        self.page.clicks.append(f"press:{key}")


class ChallengeSwitchTests(unittest.IsolatedAsyncioTestCase):
    def make_page(self):
        page = SimpleNamespace(
            url="https://accounts.google.com/v3/signin/challenge/bc",
            locator_counts={},
            clicks=[],
            filled={},
            on_click=None,
        )
        page.locator = lambda selector: FakeLocator(page, selector)
        page.get_by_role = lambda role, name=None: FakeLocator(page, f"role:{role}")
        page.get_by_text = lambda *_a, **_k: FakeLocator(page, "text:never")
        page.title = AsyncMock(return_value="2-Step Verification")

        def expect_stub(*_args, **_kwargs):
            return SimpleNamespace(to_be_visible=AsyncMock(return_value=None))

        self.patcher = patch.object(google_auth, "expect", expect_stub)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        def on_click(selector):
            if selector == "role:link":  # Try another way → challenge picker
                page.url = "https://accounts.google.com/v3/signin/challenge/picker"
                page.locator_counts["[data-challengeid]"] = 1
            elif "[data-challengeid]" in selector:  # Authenticator option → TOTP page
                page.url = "https://accounts.google.com/v3/signin/challenge/totp"
                page.locator_counts["[data-challengeid]"] = 0
                page.locator_counts['input[id="totpPin"]'] = 1
                page.locator_counts['#totpNext >> button'] = 1
            elif selector.startswith("press:") or "totp" in selector:
                page.url = "https://myaccount.google.com/"
        page.on_click = on_click
        return page

    async def test_backup_code_challenge_switches_to_authenticator(self):
        page = self.make_page()
        page.locator_counts["role:link"] = 1  # "Try another way" is present
        page.messages = []
        success, message, _ = await google_auth._handle_post_password_verification(
            page, {"email": "owner@example.test", "secret": KEY}, log=page.messages.append,
        )
        self.assertTrue(success, message)
        self.assertIn("myaccount.google.com", page.url)
        self.assertTrue(any("备用码" in m for m in page.messages))
        self.assertTrue(any("role:link" in c for c in page.clicks))  # Try another way clicked
        self.assertTrue(any("[data-challengeid]" in c for c in page.clicks))  # Authenticator chosen
        self.assertTrue(page.filled.get('input[id="totpPin"]'))  # TOTP code entered

    async def test_unknown_challenge_names_the_challenge_and_waits(self):
        page = self.make_page()
        page.url = "https://accounts.google.com/v3/signin/challenge/xyz"
        page.messages = []
        # Nothing recognizable ever appears: the helper must keep waiting for
        # manual completion while naming the challenge type.
        with patch.object(google_auth.asyncio, "sleep", AsyncMock()):
            success, message, _ = await google_auth._handle_post_password_verification(
                page, {"email": "owner@example.test", "secret": KEY}, log=page.messages.append,
            )
        self.assertIsNone(success)
        self.assertIn("验证超时", message)
        self.assertTrue(any("xyz" in m for m in page.messages))


if __name__ == "__main__":
    unittest.main()
