import base64
import datetime as dt
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.client import HTTPConnection

from server import CatalogConfig, CatalogHTTPServer, CatalogState


SCHEMA = "https://caramel-vanilla.radiosound.com/schemas/catalog-import-v1.json"


def inspected(name: str = "org.example.app", automotive: bool = True) -> dict:
    return {
        "package_name": name,
        "status": "inspected",
        "version_code": 1,
        "downloaded_size": 5,
        "sha256": "a" * 64,
        "hash_matches_index": True,
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
        "upstream_urls": {"sourceCode": "https://github.com/example/app"},
        "metadata": {
            "locale": "en-US",
            "display_name": "Example App",
            "summary": "A test application",
            "icon_url": "https://f-droid.org/repo/org.example/en-US/icon.png",
        },
    }


def bundle(*packages: dict, generated_at: str | None = None) -> dict:
    return {
        "$schema": SCHEMA,
        "bundle_version": 1,
        "generated_at": generated_at
        or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
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


class CatalogStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.public_key = root / "catalog-public.pem"
        self.public_key.write_text("test key\n", encoding="utf-8")
        self.state = CatalogState(
            CatalogConfig(
                data_dir=root / "data",
                verify_key=self.public_key,
                import_token="test-token",
            )
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_import_is_atomic_and_idempotent(self) -> None:
        payload = (json.dumps(bundle(inspected()), sort_keys=True) + "\n").encode()
        with patch("server.verify_signature"):
            result = self.state.import_bundle(payload, b"signature")
            replay = self.state.import_bundle(payload, b"signature")

        self.assertEqual("imported", result["status"])
        self.assertEqual("already_imported", replay["status"])
        self.assertTrue(self.state.is_ready())
        self.assertEqual("org.example.app", self.state.catalog_index()["entries"][0]["package_name"])
        self.assertEqual(1, self.state.metrics["import_successes"])
        self.assertEqual(1, self.state.metrics["import_replays"])

    def test_older_revision_is_rejected_without_changing_active_catalog(self) -> None:
        current = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        first = (json.dumps(bundle(inspected(), generated_at=current.isoformat())) + "\n").encode()
        older = (
            json.dumps(
                bundle(
                    inspected("org.example.other"),
                    generated_at=(current - dt.timedelta(minutes=1)).isoformat(),
                )
            )
            + "\n"
        ).encode()
        with patch("server.verify_signature"):
            self.state.import_bundle(first, b"signature")
            with self.assertRaises(ValueError):
                self.state.import_bundle(older, b"signature")
        self.assertIsNotNone(self.state.package_entry("org.example.app"))
        self.assertIsNone(self.state.package_entry("org.example.other"))


class CatalogHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        public_key = root / "catalog-public.pem"
        public_key.write_text("test key\n", encoding="utf-8")
        self.state = CatalogState(
            CatalogConfig(
                data_dir=root / "data",
                verify_key=public_key,
                import_token="test-token",
            )
        )
        self.server = CatalogHTTPServer(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def request(self, method: str, path: str, body: bytes = b"", **headers: str):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_import_requires_authentication_and_serves_public_catalog(self) -> None:
        payload = (json.dumps(bundle(inspected()), sort_keys=True) + "\n").encode()
        with patch("server.verify_signature"):
            status, _ = self.request(
                "POST",
                "/v1/import",
                payload,
                **{
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                    "X-Catalog-Signature": base64.b64encode(b"signature").decode(),
                },
            )
            self.assertEqual(401, status)
            status, body = self.request(
                "POST",
                "/v1/import",
                payload,
                **{
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                    "X-Catalog-Signature": base64.b64encode(b"signature").decode(),
                },
            )
            self.assertEqual(200, status)
            self.assertEqual("imported", json.loads(body)["status"])

        status, body = self.request("GET", "/v1/catalog")
        self.assertEqual(200, status)
        self.assertEqual("org.example.app", json.loads(body)["entries"][0]["package_name"])
        self.assertEqual("Example App", json.loads(body)["entries"][0]["metadata"]["display_name"])
        status, body = self.request("GET", "/v1/catalog/org.example.app")
        self.assertEqual(200, status)
        self.assertEqual("org.example.app", json.loads(body)["package_name"])


if __name__ == "__main__":
    unittest.main()
