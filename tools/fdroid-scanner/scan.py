#!/usr/bin/env python3
"""Bounded F-Droid candidate scanner for the Caramel Vanilla catalog.

The scanner deliberately does not mirror an app store.  It fetches the F-Droid
index conditionally, downloads only explicitly selected package IDs, inspects
those APKs with a supplied Android ``aapt2``, and emits a signed-import-ready
JSON bundle.  It is intended to run on a dedicated external scanner host
outside the Kubernetes cluster.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import os
import random
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
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_BACKOFF = 1.0
RETRYABLE_HTTP_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
DEFAULT_METADATA_LOCALE = "en-US"
MAX_METADATA_NAME = 240
MAX_METADATA_SUMMARY = 500
MAX_METADATA_DESCRIPTION = 20_000
MAX_METADATA_CATEGORIES = 12
MAX_METADATA_SCREENSHOTS = 6


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
        self.minimum_interval = max(0.0, minimum_interval)
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
    retries: int = DEFAULT_RETRY_COUNT,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ScanError(f"refusing non-HTTPS URL: {url}")
    if retries < 0 or retry_backoff < 0:
        raise ScanError("retry count and backoff must not be negative")

    host = parsed.hostname.lower()
    request = Request(url, headers=headers)
    for attempt in range(retries + 1):
        limiter.wait(host)
        response = None
        retry_reason: str | None = None
        retry_after = 0.0
        try:
            response = opener.open(request, timeout=60)
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError as error:
                    raise ScanError(
                        f"refusing {url}: invalid Content-Length {content_length!r}"
                    ) from error
                if declared_size > max_bytes:
                    raise ScanError(
                        f"refusing {url}: {content_length} bytes exceeds limit"
                    )
            chunks: list[bytes] = []
            received = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes:
                    raise ScanError(f"refusing {url}: response exceeds limit")
                budget.consume(len(chunk))
                chunks.append(chunk)
            return response.status, dict(response.headers.items()), b"".join(chunks)
        except HTTPError as error:
            if error.code == 304:
                return 304, dict(error.headers.items()), b""
            if error.code in RETRYABLE_HTTP_CODES:
                retry_reason = f"HTTP {error.code} fetching {url}"
                retry_after = _retry_after_seconds(error.headers)
            else:
                raise ScanError(f"HTTP {error.code} fetching {url}") from error
        except (OSError, TimeoutError, URLError) as error:
            retry_reason = f"fetching {url}: {getattr(error, 'reason', error)}"
        finally:
            if response is not None:
                response.close()

        if attempt >= retries:
            raise ScanError(retry_reason or f"fetching {url} failed")
        delay = max(retry_backoff * (2**attempt), retry_after)
        if delay:
            time.sleep(delay)

    raise AssertionError("request retry loop did not return or raise")


def _retry_after_seconds(headers: Any) -> float:
    value = headers.get("Retry-After") if headers else None
    try:
        return max(0.0, float(value)) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def fetch_index(
    index_url: str,
    cache_dir: Path,
    budget: DailyBudget,
    limiter: HostRateLimiter,
    max_bytes: int,
    retries: int = DEFAULT_RETRY_COUNT,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    opener: Any | None = None,
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
        opener or build_opener(),
        index_url,
        headers,
        budget,
        limiter,
        max_bytes,
        retries,
        retry_backoff,
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


class _DescriptionText(HTMLParser):
    """Convert F-Droid's small HTML descriptions into safe display text."""

    BREAK_TAGS = frozenset({"br", "div", "h1", "h2", "h3", "li", "p"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _DescriptionText()
    parser.feed(value)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    result = "\n\n".join(line for line in lines if line)
    return result[:limit].rstrip() or None


def _localized_value(value: Any, locale: str) -> Any:
    if not isinstance(value, dict):
        return value
    for key in (locale, "en-US", "en-GB", "en"):
        if key in value:
            return value[key]
    for key in sorted(value):
        return value[key]
    return None


def _localized_asset_name(value: Any, locale: str) -> str | None:
    selected = _localized_value(value, locale)
    if isinstance(selected, dict):
        selected = selected.get("name")
    return selected if isinstance(selected, str) and selected else None


def repository_base_url(index_url: str) -> str:
    parsed = urlparse(index_url)
    path = parsed.path if parsed.path.endswith("/") else parsed.path.rsplit("/", 1)[0] + "/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def _join_repository_file(repository_url: str, filename: str) -> str:
    parsed = urlparse(filename)
    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ScanError(f"refusing non-HTTPS APK URL: {filename}")
        return filename
    if filename.startswith("//"):
        raise ScanError(f"refusing network-path APK URL: {filename}")
    return urljoin(repository_url.rstrip("/") + "/", filename.lstrip("/"))


def metadata_snapshot(
    record: dict[str, Any], index_url: str, locale: str = DEFAULT_METADATA_LOCALE
) -> dict[str, Any]:
    """Return bounded public metadata from one verified F-Droid index record."""

    metadata = record.get("metadata", record)
    if not isinstance(metadata, dict):
        return {"locale": locale}
    snapshot: dict[str, Any] = {"locale": locale}
    for source_key, public_key, limit in (
        ("name", "display_name", MAX_METADATA_NAME),
        ("summary", "summary", MAX_METADATA_SUMMARY),
        ("description", "description", MAX_METADATA_DESCRIPTION),
    ):
        value = _plain_text(_localized_value(metadata.get(source_key), locale), limit)
        if value:
            snapshot[public_key] = value
    if "display_name" not in snapshot:
        package_name = record.get("packageName")
        if isinstance(package_name, str) and package_name.strip():
            snapshot["display_name"] = package_name.strip()[:MAX_METADATA_NAME]
    if "summary" not in snapshot and "display_name" in snapshot:
        snapshot["summary"] = snapshot["display_name"]
    categories = metadata.get("categories")
    if isinstance(categories, list):
        snapshot["categories"] = [
            item.strip()[:80]
            for item in categories[:MAX_METADATA_CATEGORIES]
            if isinstance(item, str) and item.strip()
        ]
    license_name = metadata.get("license")
    if isinstance(license_name, str) and license_name.strip():
        snapshot["license"] = license_name.strip()[:120]

    base_url = repository_base_url(index_url)
    for source_key, public_key in (("icon", "icon_url"), ("featureGraphic", "feature_graphic_url")):
        asset_name = _localized_asset_name(metadata.get(source_key), locale)
        if asset_name:
            snapshot[public_key] = _join_repository_file(base_url, asset_name)

    screenshots = metadata.get("screenshots")
    phone_screenshots = screenshots.get("phone") if isinstance(screenshots, dict) else None
    selected_screenshots = _localized_value(phone_screenshots, locale)
    if isinstance(selected_screenshots, list):
        snapshot["screenshot_urls"] = [
            _join_repository_file(base_url, item["name"])
            for item in selected_screenshots[:MAX_METADATA_SCREENSHOTS]
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
    return snapshot


def apk_url(index_url: str, version: dict[str, Any]) -> tuple[str, int | None, str | None]:
    file_info = version.get("file", {})
    if not isinstance(file_info, dict):
        raise ScanError("indexed version has no file object")
    name = file_info.get("name") or file_info.get("url")
    if not isinstance(name, str) or not name:
        raise ScanError("indexed version has no APK filename")
    url = _join_repository_file(repository_base_url(index_url), name)
    size = file_info.get("size")
    expected_hash = file_info.get("sha256")
    try:
        indexed_size = int(size) if size is not None else None
    except (TypeError, ValueError) as error:
        raise ScanError(f"indexed APK has invalid size: {size!r}") from error
    return url, indexed_size, expected_hash


def advertised_mirror_urls(index: dict[str, Any]) -> list[str]:
    repo = index.get("repo", {})
    mirrors = repo.get("mirrors") if isinstance(repo, dict) else None
    if isinstance(mirrors, (str, dict)):
        mirrors = [mirrors]
    if not isinstance(mirrors, list):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for mirror in mirrors:
        if isinstance(mirror, str):
            url = mirror
        elif isinstance(mirror, dict):
            url = mirror.get("url")
        else:
            continue
        if not isinstance(url, str) or not url:
            continue
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            continue
        normalized = url.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def apk_candidates(
    index: dict[str, Any],
    index_url: str,
    version: dict[str, Any],
    use_mirrors: bool,
) -> tuple[str, list[str]]:
    canonical_url, _, _ = apk_url(index_url, version)
    if not use_mirrors:
        return canonical_url, [canonical_url]

    file_info = version.get("file", {})
    name = file_info.get("name") or file_info.get("url")
    if not isinstance(name, str) or not name:
        raise ScanError("indexed version has no APK filename")
    canonical_base = repository_base_url(index_url).rstrip("/")
    mirror_candidates: list[str] = []
    seen = {canonical_url}
    for mirror_base in advertised_mirror_urls(index):
        if mirror_base.rstrip("/") == canonical_base:
            continue
        try:
            candidate = _join_repository_file(mirror_base, name)
        except ScanError:
            continue
        if candidate not in seen:
            seen.add(candidate)
            mirror_candidates.append(candidate)
    random.SystemRandom().shuffle(mirror_candidates)
    mirror_candidates.append(canonical_url)
    return canonical_url, mirror_candidates


def download_apk(
    index: dict[str, Any],
    index_url: str,
    version: dict[str, Any],
    budget: DailyBudget,
    limiter: HostRateLimiter,
    max_bytes: int,
    use_mirrors: bool = False,
    retries: int = DEFAULT_RETRY_COUNT,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    opener: Any | None = None,
) -> tuple[str, dict[str, str], bytes, int | None, str | None]:
    canonical_url, candidates = apk_candidates(index, index_url, version, use_mirrors)
    _, indexed_size, expected_hash = apk_url(index_url, version)
    opener = opener or build_opener()
    errors: list[str] = []
    headers = {"User-Agent": "CaramelVanillaCatalogScanner/1.0"}
    for candidate in candidates:
        try:
            status, response_headers, body = request_bytes(
                opener,
                candidate,
                headers,
                budget,
                limiter,
                max_bytes,
                retries,
                retry_backoff,
            )
            if status != 200:
                raise ScanError(f"unexpected HTTP status {status} downloading APK")
            actual_hash = hashlib.sha256(body).hexdigest()
            if expected_hash and actual_hash != expected_hash:
                raise ScanError(
                    f"SHA-256 mismatch (expected {expected_hash}, got {actual_hash})"
                )
            return candidate, response_headers, body, indexed_size, expected_hash
        except BudgetExceeded:
            raise
        except ScanError as error:
            errors.append(f"{candidate}: {error}")
    detail = "; ".join(errors)
    raise ScanError(f"all APK URLs failed for {canonical_url}: {detail}")


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
    opener = build_opener()
    index, index_state = fetch_index(
        args.index_url,
        cache_dir,
        budget,
        limiter,
        args.max_index_bytes,
        args.retry_count,
        args.retry_backoff,
        opener,
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
        canonical_url, indexed_size, expected_hash = apk_url(args.index_url, version)
        temporary_apk = work_dir / f"{package_name.replace('/', '_')}.apk"
        url, response_headers, body, indexed_size, expected_hash = download_apk(
            index,
            args.index_url,
            version,
            budget,
            limiter,
            args.max_apk_bytes,
            args.use_mirrors,
            args.retry_count,
            args.retry_backoff,
            opener,
        )
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
            "canonical_apk_url": canonical_url,
            "provenance": {
                "index_url": args.index_url,
                "index_sha256": index_state.get("sha256"),
                "response_etag": response_headers.get("ETag"),
                "download_url": url,
            },
            "metadata": metadata_snapshot(record, args.index_url),
            "upstream_urls": metadata_urls(record),
            "manifest_findings": findings,
            "aapt2": {"status": aapt_status, "exit_code": aapt_exit},
        }
        if url != canonical_url:
            package_result["mirror_used"] = url
            package_result["provenance"]["mirror_used"] = url
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
        "source": {
            "name": "F-Droid",
            "index_url": args.index_url,
            "index": index_state,
            "advertised_mirrors": advertised_mirror_urls(index),
        },
        "policy": {
            "daily_byte_budget": args.daily_byte_budget,
            "bytes_used": budget.used,
            "max_apk_bytes": args.max_apk_bytes,
            "host_interval_seconds": args.host_interval,
            "mirrors_enabled": args.use_mirrors,
            "retry_count": args.retry_count,
            "retry_backoff_seconds": args.retry_backoff,
            "selected_packages": selected,
        },
        "packages": packages,
        "import": {
            "apk_mirroring": "inspection_only" if args.use_mirrors else "disabled",
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
    except HTTPError as error:
        detail = f"HTTP {error.code} {error.reason}"
        with contextlib.suppress(OSError, UnicodeDecodeError):
            body = error.read(4096).decode("utf-8", errors="replace").strip()
            if body:
                detail += f": {body[:500]}"
        raise ScanError(f"catalog import upload failed: {detail}") from error
    except URLError as error:
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
    parser.add_argument(
        "--retry-count",
        "--retries",
        dest="retry_count",
        type=int,
        default=DEFAULT_RETRY_COUNT,
        help="additional attempts after a transient fetch failure",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF,
        help="initial exponential retry delay in seconds",
    )
    parser.add_argument(
        "--use-mirrors",
        action="store_true",
        help="opt in to HTTPS mirrors advertised by index-v2 for APK downloads",
    )
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
