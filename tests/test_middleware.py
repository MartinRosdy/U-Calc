import unittest
from types import SimpleNamespace

from u_calc.config import Settings
from u_calc.middleware import PublicSafetyMiddleware


class FakeEvent:
    def __init__(self, text: str, user_id: int = 1) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append((text, kwargs))


class PublicSafetyMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_message_is_rejected_before_handler(self) -> None:
        middleware = PublicSafetyMiddleware(Settings(bot_token="secret", max_message_length=100))
        event = FakeEvent("x" * 101)
        called = False

        async def handler(_event, _data):
            nonlocal called
            called = True

        await middleware(handler, event, {})
        self.assertFalse(called)
        self.assertIn("слишком длинное", event.answers[0][0])

    async def test_rate_limit_is_per_user(self) -> None:
        middleware = PublicSafetyMiddleware(Settings(bot_token="secret", rate_limit_per_minute=5))
        calls = 0

        async def handler(_event, _data):
            nonlocal calls
            calls += 1

        for _ in range(6):
            event = FakeEvent("ok", user_id=10)
            await middleware(handler, event, {})
        await middleware(handler, FakeEvent("ok", user_id=20), {})
        self.assertEqual(calls, 6)
        self.assertIn("Слишком много", event.answers[0][0])
