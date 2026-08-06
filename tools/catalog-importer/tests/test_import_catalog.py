import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from import_catalog import filtered_index, import_sqlite, validate_bundle


def bundle(*packages):
    return {
        "$schema": "https://caramel-vanilla.radiosound.com/schemas/catalog-import-v1.json",
        "bundle_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "name": "F-Droid",
            "index_url": "https://f-droid.org/repo/index-v2.json",
            "index": {"sha256": "index"},
            "advertised_mirrors": ["https://mirror.example/repo"],
        },
        "policy": {
            "daily_byte_budget": 100,
            "bytes_used": 20,
            "max_apk_bytes": 100,
            "selected_packages": [item["package_name"] for item in packages],
        },
        "packages": list(packages),
    }


def inspected(name="org.example.app", automotive=True):
    digest = "a" * 64
    return {
        "package_name": name,
        "status": "inspected",
        "version_code": 1,
        "sha256": digest,
        "hash_matches_index": True,
        "downloaded_size": 5,
        "apk_url": "https://f-droid.org/repo/org.example.app_1.apk",
        "canonical_apk_url": "https://f-droid.org/repo/org.example.app_1.apk",
        "provenance": {
            "index_url": "https://f-droid.org/repo/index-v2.json",
            "index_sha256": "b" * 64,
            "download_url": "https://f-droid.org/repo/org.example.app_1.apk",
        },
        "manifest_findings": {
            "version_name": "1.0",
            "automotive_candidate": automotive,
            "automotive_feature": automotive,
            "car_app_service": False,
        },
        "upstream_urls": {},
        "metadata": {
            "locale": "en-US",
            "display_name": "Example App",
            "summary": "A test application",
            "categories": ["Navigation"],
            "license": "Apache-2.0",
            "icon_url": "https://f-droid.org/repo/org.example/en-US/icon.png",
        },
    }


class ImporterTests(unittest.TestCase):
    def test_validation_and_filtered_index(self):
        value = bundle(inspected(), inspected("org.example.other", False))
        validate_bundle(value)
        result = filtered_index(value)
        self.assertEqual(["org.example.app"], [item["package_name"] for item in result["entries"]])
        self.assertEqual("Example App", result["entries"][0]["metadata"]["display_name"])

    def test_rejects_duplicate_package(self):
        value = bundle(inspected(), inspected())
        with self.assertRaises(ValueError):
            validate_bundle(value)

    def test_sqlite_import_is_readable(self):
        value = bundle(inspected(), {"package_name": "org.missing", "status": "not_in_index"})
        validate_bundle(value)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            import_sqlite(database, value)
            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    "SELECT package_name, status, metadata FROM packages ORDER BY package_name"
                ).fetchall()
            finally:
                connection.close()
        self.assertEqual(
            rows,
            [
                ("org.example.app", "inspected", '{"categories": ["Navigation"], "display_name": "Example App", "icon_url": "https://f-droid.org/repo/org.example/en-US/icon.png", "license": "Apache-2.0", "locale": "en-US", "summary": "A test application"}'),
                ("org.missing", "not_in_index", "{}"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
