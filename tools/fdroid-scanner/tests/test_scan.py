import tempfile
import unittest
from pathlib import Path

from scan import latest_version, metadata_urls, run_aapt2, write_json_atomic


class ScannerTests(unittest.TestCase):
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
