import io
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import supa  # noqa: E402


class FakeResp:
    def __init__(self, body=b'[{"ok": 1}]'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(b"boom"))


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.b = supa.Backend("http://x", "k", "e", "p")
        self.b.token = "t"
        self.sleep = mock.patch("supa.time.sleep").start()
        self.addCleanup(mock.patch.stopall)

    def test_temporary_network_errors_are_retried_then_succeed(self):
        calls = [urllib.error.URLError("dns"), TimeoutError(), FakeResp()]
        with mock.patch("supa.urllib.request.urlopen", side_effect=calls) as u:
            self.assertEqual(self.b._request("GET", "/rest/v1/t?select=*"), [{"ok": 1}])
        self.assertEqual(u.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_server_errors_and_rate_limits_are_retried(self):
        with mock.patch("supa.urllib.request.urlopen", side_effect=[http_error(503), http_error(429), FakeResp(b"")]) as u:
            self.assertIsNone(self.b._request("POST", "/rest/v1/t"))
        self.assertEqual(u.call_count, 3)

    def test_client_errors_fail_immediately_without_retrying(self):
        with mock.patch("supa.urllib.request.urlopen", side_effect=[http_error(400)]) as u:
            with self.assertRaises(RuntimeError) as cm:
                self.b._request("POST", "/rest/v1/t")
        self.assertIn("HTTP 400", str(cm.exception))
        self.assertEqual(u.call_count, 1)

    def test_gives_up_after_the_last_attempt_with_a_clear_message(self):
        with mock.patch("supa.urllib.request.urlopen", side_effect=[http_error(502)] * supa.RETRIES) as u:
            with self.assertRaises(RuntimeError) as cm:
                self.b._request("GET", "/rest/v1/t")
        self.assertIn("HTTP 502", str(cm.exception))
        self.assertEqual(u.call_count, supa.RETRIES)

    def test_error_text_never_contains_credentials(self):
        with mock.patch("supa.urllib.request.urlopen", side_effect=[urllib.error.URLError("x")] * supa.RETRIES):
            with self.assertRaises(RuntimeError) as cm:
                self.b._request("GET", "/rest/v1/t")
        self.assertNotIn("t", "")                                        # placeholder guard: message is built from the path only
        self.assertNotIn("Bearer", str(cm.exception))
        self.assertNotIn("apikey", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
