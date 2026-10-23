"""HTTP/cache behavior with mocked responses and no actual network access."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from pyEPW.client import APIClient
from pyEPW.exceptions import APIError


class ClientTests(unittest.TestCase):
    def setUp(self):
        project = Path(__file__).resolve().parents[1]
        self.directory = tempfile.TemporaryDirectory(prefix=".epw-test-", dir=project)
        self.root = Path(self.directory.name)
        self.assertEqual(self.root.resolve().parent, project)
        self.addCleanup(self.directory.cleanup)

    def test_second_identical_request_uses_disk_cache(self):
        client = APIClient(self.root)
        response = io.BytesIO(json.dumps({"answer": 42}).encode())
        with patch("pyEPW.client.urlopen", return_value=response) as request:
            self.assertEqual(client.get("https://example.invalid", {"query": "Dublin"}), {"answer": 42})
            self.assertEqual(client.get("https://example.invalid", {"query": "Dublin"}), {"answer": 42})
        self.assertEqual(request.call_count, 1)

    def test_rate_limit_retries_then_succeeds(self):
        error = HTTPError("https://example.invalid", 429, "Rate limited", {"Retry-After": "1"}, io.BytesIO())
        with patch("pyEPW.client.urlopen", side_effect=[error, io.BytesIO(b'{"ok": true}')]) as request:
            with patch("pyEPW.client.time.sleep") as sleep:
                result = APIClient(self.root).get("https://example.invalid", {})
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_invalid_json_raises_typed_api_error(self):
        with patch("pyEPW.client.urlopen", return_value=io.BytesIO(b"not json")):
            with self.assertRaises(APIError):
                APIClient(self.root).get("https://example.invalid", {})

    def test_successful_download_is_not_retried_for_cache_permission_failure(self):
        with patch("pyEPW.client.urlopen", return_value=io.BytesIO(b'{"ok": true}')) as request:
            with patch("pyEPW.client.atomic_text", side_effect=PermissionError("read-only cache")):
                with self.assertRaises(PermissionError):
                    APIClient(self.root).get("https://example.invalid", {})
        self.assertEqual(request.call_count, 1)

    def test_refresh_ignores_a_valid_cache(self):
        with patch("pyEPW.client.urlopen", return_value=io.BytesIO(b'{"value": 1}')):
            APIClient(self.root).get("https://example.invalid", {})
        with patch("pyEPW.client.urlopen", return_value=io.BytesIO(b'{"value": 2}')):
            self.assertEqual(APIClient(self.root, refresh=True).get("https://example.invalid", {}), {"value": 2})


if __name__ == "__main__":
    unittest.main()
