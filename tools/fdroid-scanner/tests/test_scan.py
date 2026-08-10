import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from scan import (
    DailyBudget,
    HostRateLimiter,
    advertised_mirror_urls,
    apk_candidates,
    apk_url,
    download_apk,
    latest_version,
    metadata_snapshot,
    metadata_urls,
    run_aapt2,
    write_json_atomic,
)


class FakeResponse:
    def __init__(self, body=b"apk", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self, _size):
        body, self.body = self.body, b""
        return body

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class ScannerTests(unittest.TestCase):
    def test_index_v2_mirrors_accept_strings_and_objects_but_only_https(self):
        index = {
            "repo": {
                "mirrors": [
                    "https://mirror.example/repo",
                    {"url": "https://mirror.example/repo/", "countryCode": "US"},
                    {"url": "http://insecure.example/repo"},
                    {"url": "not-a-url"},
                ]
            }
        }
        self.assertEqual(
            advertised_mirror_urls(index), ["https://mirror.example/repo"]
        )

    def test_apk_url_joins_index_v2_root_relative_filename_to_repo(self):
        version = {"file": {"name": "/org.example_1.apk"}}
        self.assertEqual(
            apk_url("https://f-droid.org/repo/index-v2.json", version)[0],
            "https://f-droid.org/repo/org.example_1.apk",
        )

    def test_mirrors_are_not_used_without_explicit_opt_in(self):
        index = {"repo": {"mirrors": ["https://mirror.example/repo"]}}
        version = {"file": {"name": "/org.example_1.apk"}}
        canonical, candidates = apk_candidates(
            index, "https://f-droid.org/repo/index-v2.json", version, False
        )
        self.assertEqual(candidates, [canonical])

    def test_retry_backoff_and_checksum_fallback(self):
        good = b"correct APK bytes"
        index = {"repo": {"mirrors": ["https://mirror.example/repo"]}}
        version = {
            "file": {"name": "/org.example_1.apk", "sha256": sha256(good).hexdigest()}
        }
        opener = FakeOpener(
            FakeResponse(body=b"wrong APK bytes"),
            URLError("temporary outage"),
            FakeResponse(body=good),
        )
        with tempfile.TemporaryDirectory() as directory:
            budget = DailyBudget(Path(directory) / "budget.json", 1024)
            limiter = HostRateLimiter(0)
            with patch("scan.time.sleep") as sleep:
                url, _, body, _, _ = download_apk(
                    index,
                    "https://f-droid.org/repo/index-v2.json",
                    version,
                    budget,
                    limiter,
                    1024,
                    use_mirrors=True,
                    retries=1,
                    retry_backoff=2,
                    opener=opener,
                )
        self.assertEqual(url, "https://f-droid.org/repo/org.example_1.apk")
        self.assertEqual(body, good)
        self.assertEqual(opener.urls, [
            "https://mirror.example/repo/org.example_1.apk",
            "https://f-droid.org/repo/org.example_1.apk",
            "https://f-droid.org/repo/org.example_1.apk",
        ])
        sleep.assert_called_once_with(2)

    def test_host_rate_limiter_is_per_host(self):
        limiter = HostRateLimiter(1)
        with patch("scan.time.monotonic", side_effect=[10, 10, 10.5, 10.5, 10.6, 10.6]):
            with patch("scan.time.sleep") as sleep:
                limiter.wait("mirror.example")
                limiter.wait("mirror.example")
                limiter.wait("other.example")
        sleep.assert_called_once_with(0.5)

    def test_latest_version_uses_manifest_version_code(self):
        record = {
            "versions": {
                "1": {"manifest": {"versionCode": 1}},
                "20": {"manifest": {"versionCode": 20}},
            }
        }
        self.assertEqual(latest_version(record)["manifest"]["versionCode"], 20)

    def test_metadata_urls_are_limited_to_upstream_links(self):
        record = {
            "metadata": {
                "sourceCode": "https://github.com/example/app",
                "webSite": "https://example.com",
                "unknown": "should not be copied",
            }
        }
        self.assertEqual(
            metadata_urls(record),
            {
                "sourceCode": "https://github.com/example/app",
                "webSite": "https://example.com",
            },
        )

    def test_metadata_snapshot_selects_english_metadata_and_bounds_assets(self):
        record = {
            "metadata": {
                "name": {"en-US": "Example Maps"},
                "summary": {"en-US": "Maps &amp; navigation"},
                "description": {"en-US": "<p>Find places.</p><ul><li>Offline</li></ul>"},
                "categories": ["Navigation"],
                "license": "Apache-2.0",
                "lastUpdated": 1_754_640_000_000,
                "icon": {"en-US": {"name": "/org.example/en-US/icon.png"}},
                "featureGraphic": {"en-US": {"name": "/org.example/en-US/feature.jpg"}},
                "screenshots": {
                    "phone": {
                        "en-US": [{"name": "/org.example/en-US/phoneScreenshots/1.png"}]
                    }
                },
            }
        }
        self.assertEqual(
            metadata_snapshot(record, "https://f-droid.org/repo/index-v2.json"),
            {
                "locale": "en-US",
                "display_name": "Example Maps",
                "summary": "Maps & navigation",
                "description": "Find places.\n\nOffline",
                "categories": ["Navigation"],
                "license": "Apache-2.0",
                "last_updated": "2025-08-08T08:00:00+00:00",
                "icon_url": "https://f-droid.org/repo/org.example/en-US/icon.png",
                "feature_graphic_url": "https://f-droid.org/repo/org.example/en-US/feature.jpg",
                "screenshot_urls": [
                    "https://f-droid.org/repo/org.example/en-US/phoneScreenshots/1.png"
                ],
            },
        )

    def test_atomic_json_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            write_json_atomic(path, {"bytes": 12})
            self.assertEqual(path.read_text(encoding="utf-8").strip(), '{\n  "bytes": 12\n}')

    def test_missing_aapt2_is_reported_without_crashing(self):
        status, exit_code, message, findings = run_aapt2("/does/not/exist/aapt2", Path("missing.apk"))
        self.assertEqual(status, "unavailable")
        self.assertEqual(exit_code, 1)
        self.assertIn("No such file", message)
        self.assertEqual(findings, {})


if __name__ == "__main__":
    unittest.main()
