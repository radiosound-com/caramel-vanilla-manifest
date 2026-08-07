import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from refresh_metadata import ScanError, main, refresh_bundle


class MetadataRefreshTests(unittest.TestCase):
    def _bundle(self):
        return {
            "generated_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(),
            "source": {"index_url": "https://f-droid.org/repo/index-v1.jar"},
            "policy": {"bytes_used": 10},
            "packages": [
                {
                    "package_name": "org.example.app",
                    "status": "inspected",
                    "sha256": "a" * 64,
                    "provenance": {"index_sha256": "b" * 64},
                }
            ],
        }

    def test_refresh_updates_metadata_without_touching_apk_evidence(self):
        bundle = self._bundle()
        index = {
            "packages": {
                "org.example.app": {
                    "metadata": {
                        "name": {"en-US": "Example App"},
                        "summary": {"en-US": "A test application"},
                    }
                }
            }
        }
        refreshed = refresh_bundle(
            bundle,
            index,
            {"sha256": "c" * 64},
            "https://f-droid.org/repo/index-v2.json",
            "en-US",
            42,
        )
        package = refreshed["packages"][0]
        self.assertEqual("a" * 64, package["sha256"])
        self.assertEqual("Example App", package["metadata"]["display_name"])
        self.assertEqual("c" * 64, package["provenance"]["index_sha256"])
        self.assertEqual(42, refreshed["policy"]["bytes_used"])
        self.assertTrue(refreshed["policy"]["metadata_refresh"])

    def test_cli_reads_and_writes_a_bundle(self):
        index = {
            "packages": {
                "org.example.app": {
                    "metadata": {
                        "name": {"en-US": "Example App"},
                        "summary": {"en-US": "A test application"},
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            bundle_path = Path(directory) / "bundle.json"
            bundle_path.write_text(json.dumps(self._bundle()), encoding="utf-8")
            with patch(
                "refresh_metadata.fetch_index",
                return_value=(index, {"sha256": "c" * 64}),
            ):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--cache-dir",
                            str(Path(directory) / "cache"),
                            "--bundle",
                            str(bundle_path),
                        ]
                    ),
                )
            result = json.loads(bundle_path.read_text(encoding="utf-8"))
        self.assertEqual("Example App", result["packages"][0]["metadata"]["display_name"])

    def test_refresh_rejects_a_selected_package_missing_from_current_index(self):
        with self.assertRaisesRegex(ScanError, "missing from the current F-Droid index"):
            refresh_bundle(
                self._bundle(),
                {"packages": {}},
                {"sha256": "c" * 64},
                "https://f-droid.org/repo/index-v2.json",
                "en-US",
                0,
            )


if __name__ == "__main__":
    unittest.main()
