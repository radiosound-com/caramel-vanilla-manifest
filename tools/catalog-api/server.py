#!/usr/bin/env python3
"""Small, dependency-free Caramel Store catalog API.

The service keeps the scanner outside the cluster trust boundary.  It accepts
only signed JSON import bundles on an authenticated staging endpoint, writes a
complete SQLite catalog and filtered index into an immutable revision, and
publishes that revision by atomically replacing a small active pointer.  Public
catalog reads never share the import credential.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

try:
    from import_catalog import (
        ImportError as CatalogImportError,
        PACKAGE_NAME,
        filtered_index,
        import_sqlite,
        parse_timestamp,
        read_json,
        validate_bundle,
        verify_signature,
        write_json_atomic,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "catalog-importer"))
    from import_catalog import (
        ImportError as CatalogImportError,
        PACKAGE_NAME,
        filtered_index,
        import_sqlite,
        parse_timestamp,
        read_json,
        validate_bundle,
        verify_signature,
        write_json_atomic,
    )


REVISION = re.compile(r"^[a-f0-9]{64}$")
DEFAULT_MAX_BUNDLE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class CatalogConfig:
    data_dir: Path
    verify_key: Path
    import_token: str
    max_age_hours: float = 48.0
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class CatalogState:
    """Persistent catalog state for one non-HA SQLite-backed API instance."""

    def __init__(self, config: CatalogConfig) -> None:
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.revisions_dir = self.config.data_dir / "revisions"
        self.revisions_dir.mkdir(parents=True, exist_ok=True)
        self.active_path = self.config.data_dir / "active.json"
        self.import_lock = threading.Lock()
        self.metrics_lock = threading.Lock()
        self.metrics: dict[str, int] = {
            "import_attempts": 0,
            "import_successes": 0,
            "import_replays": 0,
            "import_rejections": 0,
            "import_failures": 0,
        }

    def _active_record(self) -> dict[str, Any] | None:
        if not self.active_path.exists():
            return None
        try:
            value = read_json(self.active_path)
        except CatalogImportError:
            raise CatalogImportError("active catalog pointer is unreadable")
        revision = value.get("revision")
        if not isinstance(revision, str) or not REVISION.fullmatch(revision):
            raise CatalogImportError("active catalog pointer has an invalid revision")
        revision_dir = self.revisions_dir / revision
        if not (revision_dir / "catalog.sqlite3").is_file() or not (
            revision_dir / "catalog-index.json"
        ).is_file():
            raise CatalogImportError("active catalog revision is incomplete")
        return value

    def _active_index(self) -> dict[str, Any] | None:
        record = self._active_record()
        if record is None:
            return None
        return read_json(self.revisions_dir / record["revision"] / "catalog-index.json")

    def is_ready(self) -> bool:
        try:
            return self.config.verify_key.is_file() and self._active_index() is not None
        except CatalogImportError:
            return False

    def catalog_index(self) -> dict[str, Any] | None:
        return self._active_index()

    def package_entry(self, package_name: str) -> dict[str, Any] | None:
        index = self._active_index()
        if index is None:
            return None
        for entry in index.get("entries", []):
            if entry.get("package_name") == package_name:
                return entry
        return None

    def _metric_add(self, name: str) -> None:
        with self.metrics_lock:
            self.metrics[name] += 1

    def import_bundle(self, payload: bytes, signature: bytes) -> dict[str, Any]:
        """Verify, validate, and publish one bundle revision."""

        self._metric_add("import_attempts")
        try:
            if not self.config.verify_key.is_file():
                raise CatalogImportError("catalog verification key is unavailable")
            bundle_sha256 = hashlib.sha256(payload).hexdigest()
            with tempfile.TemporaryDirectory(prefix="caramel-store-import-") as directory:
                bundle_path = Path(directory) / "catalog-import.json"
                signature_path = Path(directory) / "catalog-import.json.sig"
                bundle_path.write_bytes(payload)
                signature_path.write_bytes(signature)
                verify_signature(bundle_path, signature_path, self.config.verify_key)
                bundle = read_json(bundle_path)
                validate_bundle(bundle, self.config.max_age_hours)

            with self.import_lock:
                active = self._active_record()
                if active and active.get("bundle_sha256") == bundle_sha256:
                    self._metric_add("import_replays")
                    return {
                        "status": "already_imported",
                        "bundle_sha256": bundle_sha256,
                        "generated_at": bundle["generated_at"],
                        "entries": len(filtered_index(bundle)["entries"]),
                    }
                if active:
                    active_time = parse_timestamp(active["generated_at"])
                    bundle_time = parse_timestamp(bundle["generated_at"])
                    if bundle_time <= active_time:
                        raise CatalogImportError(
                            "catalog bundle is not newer than the active revision"
                        )

                index = filtered_index(bundle)
                revision_dir = self.revisions_dir / bundle_sha256
                if not revision_dir.exists():
                    with tempfile.TemporaryDirectory(
                        prefix=".catalog-revision-", dir=self.revisions_dir
                    ) as directory:
                        staging_dir = Path(directory)
                        import_sqlite(
                            staging_dir / "catalog.sqlite3", bundle, bundle_sha256
                        )
                        write_json_atomic(staging_dir / "catalog-index.json", index)
                        os.replace(staging_dir, revision_dir)
                elif not (
                    (revision_dir / "catalog.sqlite3").is_file()
                    and (revision_dir / "catalog-index.json").is_file()
                ):
                    raise CatalogImportError("matching catalog revision is incomplete")

                write_json_atomic(
                    self.active_path,
                    {
                        "revision": bundle_sha256,
                        "bundle_sha256": bundle_sha256,
                        "generated_at": bundle["generated_at"],
                        "published_at": utc_now(),
                    },
                )
                self._metric_add("import_successes")
                return {
                    "status": "imported",
                    "bundle_sha256": bundle_sha256,
                    "generated_at": bundle["generated_at"],
                    "entries": len(index["entries"]),
                }
        except CatalogImportError:
            self._metric_add("import_rejections")
            raise
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self._metric_add("import_failures")
            raise

    def metrics_text(self) -> str:
        with self.metrics_lock:
            values = dict(self.metrics)
        lines = [
            "# HELP caramel_store_import_attempts_total Import bundle attempts.",
            "# TYPE caramel_store_import_attempts_total counter",
            f"caramel_store_import_attempts_total {values['import_attempts']}",
            "# HELP caramel_store_import_successes_total Successfully published bundles.",
            "# TYPE caramel_store_import_successes_total counter",
            f"caramel_store_import_successes_total {values['import_successes']}",
            "# HELP caramel_store_import_replays_total Idempotent replayed bundles.",
            "# TYPE caramel_store_import_replays_total counter",
            f"caramel_store_import_replays_total {values['import_replays']}",
            "# HELP caramel_store_import_rejections_total Rejected bundles.",
            "# TYPE caramel_store_import_rejections_total counter",
            f"caramel_store_import_rejections_total {values['import_rejections']}",
            "# HELP caramel_store_import_failures_total Unexpected import failures.",
            "# TYPE caramel_store_import_failures_total counter",
            f"caramel_store_import_failures_total {values['import_failures']}",
        ]
        return "\n".join(lines) + "\n"


class CatalogHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(
        self, address: tuple[str, int], state: CatalogState, metrics_only: bool = False
    ) -> None:
        super().__init__(address, CatalogRequestHandler)
        self.state = state
        self.metrics_only = metrics_only
        self.daemon_threads = True


class CatalogRequestHandler(BaseHTTPRequestHandler):
    server: CatalogHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), format % args)
        )

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _send_json(self, status: int, value: dict[str, Any]) -> None:
        self._send_bytes(
            status,
            "application/json; charset=utf-8",
            (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"),
        )

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        state = self.server.state
        if self.server.metrics_only:
            if path == "/metrics":
                self._send_bytes(
                    HTTPStatus.OK,
                    "text/plain; version=0.0.4; charset=utf-8",
                    state.metrics_text().encode("utf-8"),
                )
            else:
                self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/readyz":
            if state.is_ready():
                self._send_json(HTTPStatus.OK, {"status": "ready"})
            else:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, "catalog is not ready")
            return
        if path == "/metrics":
            self._send_bytes(
                HTTPStatus.OK,
                "text/plain; version=0.0.4; charset=utf-8",
                state.metrics_text().encode("utf-8"),
            )
            return
        if path == "/v1/catalog":
            try:
                index = state.catalog_index()
            except CatalogImportError as error:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
                return
            if index is None:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, "catalog is not populated")
            else:
                self._send_json(HTTPStatus.OK, index)
            return
        prefix = "/v1/catalog/"
        if path.startswith(prefix):
            package_name = unquote(path[len(prefix) :])
            if not PACKAGE_NAME.fullmatch(package_name):
                self._send_error(HTTPStatus.NOT_FOUND, "package not found")
                return
            try:
                entry = state.package_entry(package_name)
            except CatalogImportError as error:
                self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
                return
            if entry is None:
                self._send_error(HTTPStatus.NOT_FOUND, "package not found")
            else:
                self._send_json(HTTPStatus.OK, entry)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def _authorized_import(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.state.config.import_token}"
        return secrets.compare_digest(supplied, expected)

    def _read_body(self) -> bytes:
        value = self.headers.get("Content-Length")
        try:
            length = int(value) if value is not None else -1
        except ValueError as error:
            raise CatalogImportError("Content-Length must be an integer") from error
        if length < 0:
            raise CatalogImportError("Content-Length is required")
        if length > self.server.state.config.max_bundle_bytes:
            raise CatalogImportError("import bundle exceeds the request size limit")
        body = bytearray()
        while len(body) < length:
            chunk = self.rfile.read(min(1024 * 1024, length - len(body)))
            if not chunk:
                raise CatalogImportError("request body ended before Content-Length")
            body.extend(chunk)
        return bytes(body)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/v1/import":
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self._authorized_import():
            self._send_error(HTTPStatus.UNAUTHORIZED, "valid import credentials are required")
            return
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            self._send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "application/json is required")
            return
        signature_header = self.headers.get("X-Catalog-Signature")
        if not signature_header:
            self._send_error(HTTPStatus.UNPROCESSABLE_ENTITY, "X-Catalog-Signature is required")
            return
        try:
            signature = base64.b64decode(signature_header, validate=True)
            if not signature or len(signature) > 16 * 1024:
                raise ValueError("invalid signature size")
            payload = self._read_body()
            result = self.server.state.import_bundle(payload, signature)
        except (binascii.Error, ValueError, CatalogImportError) as error:
            self._send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
            return
        except (OSError, sqlite3.Error) as error:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return
        self._send_json(HTTPStatus.OK, result)


def read_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not token or any(character.isspace() for character in token):
        raise ValueError("import token file must contain one non-empty token")
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("CARAMEL_STORE_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("CARAMEL_STORE_PORT", "8080"))
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("CARAMEL_STORE_DATA_DIR", "/data/catalog")),
    )
    parser.add_argument(
        "--verify-key",
        type=Path,
        default=Path(os.environ.get("CARAMEL_STORE_VERIFY_KEY", "/etc/caramel-store/catalog-public.pem")),
    )
    parser.add_argument(
        "--import-token-file",
        type=Path,
        default=Path(
            os.environ.get(
                "CARAMEL_STORE_IMPORT_TOKEN_FILE", "/etc/caramel-store/import-token"
            )
        ),
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=float(os.environ.get("CARAMEL_STORE_MAX_AGE_HOURS", "48")),
    )
    parser.add_argument(
        "--max-bundle-bytes",
        type=int,
        default=int(
            os.environ.get("CARAMEL_STORE_MAX_BUNDLE_BYTES", str(DEFAULT_MAX_BUNDLE_BYTES))
        ),
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=int(os.environ.get("CARAMEL_STORE_METRICS_PORT", "9090")),
        help="optional separate Prometheus endpoint port; use 0 to disable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        token = read_token(args.import_token_file)
        config = CatalogConfig(
            data_dir=args.data_dir,
            verify_key=args.verify_key,
            import_token=token,
            max_age_hours=args.max_age_hours,
            max_bundle_bytes=args.max_bundle_bytes,
        )
        state = CatalogState(config)
        server = CatalogHTTPServer((args.host, args.port), state)
        metrics_server = None
        if args.metrics_port and args.metrics_port != args.port:
            metrics_server = CatalogHTTPServer(
                (args.host, args.metrics_port), state, metrics_only=True
            )
            threading.Thread(
                target=metrics_server.serve_forever, name="catalog-metrics", daemon=True
            ).start()
    except (OSError, ValueError) as error:
        print(f"catalog API: {error}", file=sys.stderr)
        return 2
    print(f"catalog API listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if metrics_server is not None:
            metrics_server.shutdown()
            metrics_server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
