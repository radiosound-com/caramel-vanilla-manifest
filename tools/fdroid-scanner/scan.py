#!/usr/bin/env python3
"""Bounded F-Droid candidate scanner for the Caramel Vanilla catalog.

The scanner deliberately does not mirror an app store.  It fetches the F-Droid
index conditionally, downloads only explicitly selected package IDs, inspects
those APKs with a supplied Android ``aapt2``, and emits a signed-import-ready
JSON bundle.  It is intended to run on littleboy outside the Kubernetes
cluster.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener


SCHEMA = "https://caramel-vanilla.radiosound.com/schemas/catalog-import-v1.json"
DEFAULT_INDEX_URL = "https://f-droid.org/repo/index-v2.json"
DEFAULT_MAX_INDEX_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_APK_BYTES = 512 * 1024 * 1024


class ScanError(RuntimeError):
    pass


class BudgetExceeded(ScanError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ScanError(f"another scanner run holds {path}") from error
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class DailyBudget:
    def __init__(self, state_path: Path, limit: int) -> None:
        self.state_path = state_path
        self.limit = limit
        self.state = read_json(state_path, {})
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        if self.state.get("date") != today:
            self.state = {"date": today, "bytes": 0}

    @property
    def used(self) -> int:
        return int(self.state.get("bytes", 0))

    def consume(self, amount: int) -> None:
        if amount < 0 or self.used + amount > self.limit:
            raise BudgetExceeded(
                f"daily byte budget exceeded ({self.used} + {amount} > {self.limit})"
            )
        self.state["bytes"] = self.used + amount
        write_json_atomic(self.state_path, self.state)


class HostRateLimiter:
    def __init__(self, minimum_interval: float) -> None:
        self.minimum_interval = minimum_interval
        self.last_request: dict[str, float] = {}

    def wait(self, host: str) -> None:
        elapsed = time.monotonic() - self.last_request.get(host, 0.0)
        if elapsed < self.minimum_interval:
            time.sleep(self.minimum_interval - elapsed)
        self.last_request[host] = time.monotonic()


def request_bytes(
    opener: Any,
    url: str,
    headers: dict[str, str],
    budget: DailyBudget,
    limiter: HostRateLimiter,
    max_bytes: int,
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ScanError(f"refusing non-HTTPS URL: {url}")
    limiter.wait(parsed.netloc)
    request = Request(url, headers=headers)
    try:
        response = opener.open(request, timeout=60)
    except HTTPError as error:
        if error.code == 304:
            return 304, dict(error.headers.items()), b""
        raise ScanError(f"HTTP {error.code} fetching {url}") from error
    except URLError as error:
        raise ScanError(f"fetching {url}: {error.reason}") from error

    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > max_bytes:
        raise ScanError(f"refusing {url}: {content_length} bytes exceeds limit")
    chunks: list[bytes] = []
    received = 0
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > max_bytes:
                raise ScanError(f"refusing {url}: response exceeds limit")
            budget.consume(len(chunk))
            chunks.append(chunk)
    finally:
        response.close()
    return response.status, dict(response.headers.items()), b"".join(chunks)


def fetch_index(
    index_url: str,
    cache_dir: Path,
    budget: DailyBudget,
    limiter: HostRateLimiter,
    max_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_path = cache_dir / "index-state.json"
    state = read_json(state_path, {})
    headers = {"User-Agent": "CaramelVanillaCatalogScanner/1.0"}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]

    index_path = cache_dir / "index-v2.json"
    status, response_headers, body = request_bytes(
        build_opener(), index_url, headers, budget, limiter, max_bytes
    )
    if status == 304:
        if not index_path.exists():
            raise ScanError("F-Droid returned 304 but the local index cache is absent")
        body = index_path.read_bytes()
    else:
        index_path.write_bytes(body)
        state = {
            "url": index_url,
            "etag": response_headers.get("ETag"),
            "last_modified": response_headers.get("Last-Modified"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "fetched_at": utc_now(),
        }
        write_json_atomic(state_path, state)
    try:
        index = json.loads(body)
    except json.JSONDecodeError as error:
        raise ScanError(f"invalid F-Droid index JSON: {error}") from error
    return index, state


def package_records(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    packages = index.get("packages", {})
    if not isinstance(packages, dict):
        raise ScanError("F-Droid index has no packages object")
    return {str(key): value for key, value in packages.items() if isinstance(value, dict)}


def version_code(version_id: str, version: dict[str, Any]) -> int:
    manifest = version.get("manifest", {})
    for value in (manifest.get("versionCode"), version.get("versionCode"), version_id):
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return -1


def latest_version(record: dict[str, Any]) -> dict[str, Any]:
    versions = record.get("versions", {})
    if isinstance(versions, list):
        candidates = [item for item in versions if isinstance(item, dict)]
    elif isinstance(versions, dict):
        candidates = [item for item in versions.values() if isinstance(item, dict)]
    else:
        candidates = []
    if not candidates:
        raise ScanError("package has no indexed versions")
    return max(candidates, key=lambda item: version_code("", item))


def metadata_urls(record: dict[str, Any]) -> dict[str, str]:
    metadata = record.get("metadata", record)
    if not isinstance(metadata, dict):
        return {}
    result: dict[str, str] = {}
    for key in ("sourceCode", "webSite", "issueTracker", "changelog", "donate"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            result[key] = value
    return result


def apk_url(index_url: str, version: dict[str, Any]) -> tuple[str, int | None, str | None]:
    file_info = version.get("file", {})
    if not isinstance(file_info, dict):
        raise ScanError("indexed version has no file object")
    name = file_info.get("name") or file_info.get("url")
    if not isinstance(name, str) or not name:
        raise ScanError("indexed version has no APK filename")
    url = name if name.startswith("https://") else urljoin(index_url, name)
    size = file_info.get("size")
    expected_hash = file_info.get("sha256")
    return url, int(size) if size is not None else None, expected_hash


def run_aapt2(aapt2: str, apk: Path) -> tuple[str, int, str, dict[str, Any]]:
    try:
        result = subprocess.run(
            [aapt2, "dump", "badging", str(apk)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return "unavailable", 1, str(error), {}
    output = result.stdout
    package_match = re.search(
        r"package: name='([^']+)' versionCode='([^']*)' versionName='([^']*)'", output
    )
    features = sorted(set(re.findall(r"uses-feature: name='([^']+)'", output)))
    permissions = sorted(set(re.findall(r"uses-permission: name='([^']+)'", output)))
    car_permissions = [item for item in permissions if ".car." in item or item.startswith("android.car.")]
    findings = {
        "package_name": package_match.group(1) if package_match else None,
        "version_code": int(package_match.group(2)) if package_match and package_match.group(2).isdigit() else None,
        "version_name": package_match.group(3) if package_match else None,
        "features": features,
        "permissions": permissions,
        "car_permissions": car_permissions,
        "automotive_feature": "android.hardware.type.automotive" in features,
        "car_permission": bool(car_permissions),
        "car_app_service": "androidx.car.app.CarAppService" in output or "CarAppService" in output,
    }
    findings["automotive_candidate"] = bool(
        findings["automotive_feature"]
        or findings["car_permission"]
        or findings["car_app_service"]
    )
    return "ok", 0, output, findings


def read_selection(args: argparse.Namespace) -> list[str]:
    selected = list(args.package)
    if args.selection_file:
        for line in Path(args.selection_file).read_text(encoding="utf-8").splitlines():
            package = line.split("#", 1)[0].strip()
            if package:
                selected.append(package)
    return sorted(set(selected))


def scan(args: argparse.Namespace) -> dict[str, Any]:
    cache_dir = Path(args.cache_dir)
    work_dir = cache_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    budget = DailyBudget(cache_dir / "budget.json", args.daily_byte_budget)
    limiter = HostRateLimiter(args.host_interval)
    index, index_state = fetch_index(
        args.index_url, cache_dir, budget, limiter, args.max_index_bytes
    )
    records = package_records(index)
    selected = read_selection(args)
    if not selected:
        raise ScanError("refusing an unbounded scan; use --package or --selection-file")

    packages: list[dict[str, Any]] = []
    for package_name in selected:
        record = records.get(package_name)
        if record is None:
            packages.append({"package_name": package_name, "status": "not_in_index"})
            continue
        version = latest_version(record)
        url, indexed_size, expected_hash = apk_url(args.index_url, version)
        temporary_apk = work_dir / f"{package_name.replace('/', '_')}.apk"
        headers = {"User-Agent": "CaramelVanillaCatalogScanner/1.0"}
        status, response_headers, body = request_bytes(
            build_opener(), url, headers, budget, limiter, args.max_apk_bytes
        )
        if status != 200:
            raise ScanError(f"unexpected HTTP status {status} downloading {package_name}")
        temporary_apk.write_bytes(body)
        actual_hash = sha256_file(temporary_apk)
        aapt_status, aapt_exit, aapt_output, findings = run_aapt2(args.aapt2, temporary_apk)
        package_result: dict[str, Any] = {
            "package_name": package_name,
            "status": "inspected",
            "version_code": version_code("", version),
            "indexed_size": indexed_size,
            "downloaded_size": len(body),
            "sha256": actual_hash,
            "expected_sha256": expected_hash,
            "hash_matches_index": expected_hash in (None, actual_hash),
            "apk_url": url,
            "provenance": {
                "index_url": args.index_url,
                "index_sha256": index_state.get("sha256"),
                "response_etag": response_headers.get("ETag"),
            },
            "upstream_urls": metadata_urls(record),
            "manifest_findings": findings,
            "aapt2": {"status": aapt_status, "exit_code": aapt_exit},
        }
        if aapt_status != "ok":
            package_result["aapt2"]["error"] = aapt_output
        packages.append(package_result)
        if not args.keep_apks:
            temporary_apk.unlink(missing_ok=True)

    bundle = {
        "$schema": SCHEMA,
        "bundle_version": 1,
        "generated_at": utc_now(),
        "scanner": {"name": "caramel-vanilla-fdroid-scanner", "version": "1.0"},
        "source": {"name": "F-Droid", "index_url": args.index_url, "index": index_state},
        "policy": {
            "daily_byte_budget": args.daily_byte_budget,
            "bytes_used": budget.used,
            "max_apk_bytes": args.max_apk_bytes,
            "host_interval_seconds": args.host_interval,
            "selected_packages": selected,
        },
        "packages": packages,
        "import": {
            "apk_mirroring": "disabled",
            "release_signing": "separate_controlled_step",
        },
    }
    return bundle


def canonical_bundle(bundle: dict[str, Any]) -> bytes:
    return (json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sign_bundle(bundle_path: Path, signature_path: Path, signing_key: Path) -> None:
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(signing_key), "-out", str(signature_path), str(bundle_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ScanError(result.stderr.strip() or "openssl failed to sign bundle")


def upload_bundle(args: argparse.Namespace, bundle_path: Path, signature_path: Path) -> None:
    parsed = urlparse(args.upload_url)
    if parsed.scheme != "https":
        raise ScanError("catalog import upload must use HTTPS")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "CaramelVanillaCatalogScanner/1.0",
        "X-Catalog-Signature": base64.b64encode(signature_path.read_bytes()).decode("ascii"),
    }
    if args.bearer_token_file:
        token = Path(args.bearer_token_file).read_text(encoding="utf-8").strip()
        headers["Authorization"] = f"Bearer {token}"
    request = Request(args.upload_url, data=bundle_path.read_bytes(), headers=headers, method="POST")
    try:
        with build_opener().open(request, timeout=60) as response:
            if response.status < 200 or response.status >= 300:
                raise ScanError(f"catalog import endpoint returned HTTP {response.status}")
    except (HTTPError, URLError) as error:
        raise ScanError(f"catalog import upload failed: {error}") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--cache-dir", default="./fdroid-cache")
    parser.add_argument("--selection-file")
    parser.add_argument("--package", action="append", default=[])
    parser.add_argument("--aapt2", default="aapt2")
    parser.add_argument("--daily-byte-budget", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--max-index-bytes", type=int, default=DEFAULT_MAX_INDEX_BYTES)
    parser.add_argument("--max-apk-bytes", type=int, default=DEFAULT_MAX_APK_BYTES)
    parser.add_argument("--host-interval", type=float, default=2.0)
    parser.add_argument("--keep-apks", action="store_true")
    parser.add_argument("--bundle", default="catalog-import.json")
    parser.add_argument("--signing-key")
    parser.add_argument("--signature", default="catalog-import.json.sig")
    parser.add_argument("--upload-url")
    parser.add_argument("--bearer-token-file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache_dir = Path(args.cache_dir)
    try:
        with exclusive_lock(cache_dir / "scanner.lock"):
            bundle = scan(args)
            bundle_path = Path(args.bundle)
            bundle_path.write_bytes(canonical_bundle(bundle))
            if args.signing_key:
                signature_path = Path(args.signature)
                sign_bundle(bundle_path, signature_path, Path(args.signing_key))
                if args.upload_url:
                    upload_bundle(args, bundle_path, signature_path)
            elif args.upload_url:
                raise ScanError("--upload-url requires --signing-key")
    except ScanError as error:
        print(f"scanner: {error}", file=sys.stderr)
        return 2
    print(f"wrote {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
