from __future__ import annotations

import unittest

import httpx

from app.zhipu import _retry_delay, _supports_thinking


class ZhipuClientTests(unittest.TestCase):
    def test_identifies_models_with_thinking_control(self):
        self.assertTrue(_supports_thinking("glm-4.7-flash"))
        self.assertTrue(_supports_thinking("glm-5"))
        self.assertFalse(_supports_thinking("glm-4-flash"))
        self.assertFalse(_supports_thinking("glm-4v-flash"))

    def test_uses_retry_after_with_safe_cap(self):
        response = httpx.Response(429, headers={"Retry-After": "9"})
        self.assertEqual(_retry_delay(response, 0), 4.0)

    def test_falls_back_to_incremental_retry_delay(self):
        response = httpx.Response(503)
        self.assertEqual(_retry_delay(response, 1), 2.0)


if __name__ == "__main__":
    unittest.main()
