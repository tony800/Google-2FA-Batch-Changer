import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.google.backend import google_auth


class FakeLocator:
    """Locator stub keyed by selector so tests control what 'exists'."""

    counts = {}

    def __init__(self, selector, children=None):
        self.selector = selector
        self.children = children or ()
        self.first = self

    def or_(self, other):
        return FakeLocator("combined", children=(self, other))

    async def count(self):
        if self.children:
            return max([await child.count() for child in self.children])
        return max(
            [FakeLocator.counts.get(part.strip(), 0) for part in self.selector.split(",")],
            default=0,
        )

    async def is_visible(self, **kwargs):
        return await self.count() > 0


class IdentifierPageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeLocator.counts = {
            'input[name="identifier"]': 1,
            "#identifierId": 1,
            'input[type="email"]': 0,
        }
        page = SimpleNamespace(
            url="https://accounts.google.com/v3/signin/identifier",
            get_by_role=lambda *a, **k: FakeLocator("role"),
            locator=lambda selector: FakeLocator(selector),
        )
        self.page = page
        expect_stub = SimpleNamespace(to_be_visible=AsyncMock(return_value=None))
        patcher = patch.object(google_auth, "expect", lambda *_: expect_stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        FakeLocator.counts = {}

    async def test_identifier_text_input_is_recognized_as_signin_page(self):
        status, _ = await google_auth.get_login_state(self.page)
        self.assertEqual(status, google_auth.GoogleLoginStatus.NOT_LOGGED_IN)

    async def test_email_type_selector_is_no_longer_the_only_check(self):
        source = open(google_auth.__file__, encoding="utf-8").read()
        email_only = re.findall(r"locator\(['\"]input\[type=.email.\]'\)", source)
        self.assertTrue(
            any('name="identifier"' in m or "#identifierId" in m
                for m in re.findall(r"locator\((.*?)\)", source)),
            "登录代码应使用 name=identifier / #identifierId 选择器",
        )
        self.assertEqual(email_only, [])


if __name__ == "__main__":
    unittest.main()
