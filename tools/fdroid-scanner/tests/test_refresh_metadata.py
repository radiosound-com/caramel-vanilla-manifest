import datetime as dt
import unittest

from refresh_metadata import refresh_bundle


class MetadataRefreshTests(unittest.TestCase):
    def test_refresh_updates_metadata_without_touching_apk_evidence(self):
        bundle = {
            "generated_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(),
            "source": {"index_url": "https://f-droid.org/repo/index-v2.json"},
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


if __name__ == "__main__":
    unittest.main()
