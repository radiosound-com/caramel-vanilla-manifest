#!/usr/bin/env python3
"""Refresh F-Droid metadata without downloading or inspecting APKs.

This runs on the external scanner host. It reads the last complete signed
bundle, refreshes the selected packages' metadata from the current verified
F-Droid index, and emits a new bundle that can be signed and uploaded through
the existing authenticated import path. APK checksums and manifest findings
are never changed by this command.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from scan import (
    DEFAULT_INDEX_URL,
    DEFAULT_MAX_INDEX_BYTES,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_COUNT,
    DailyBudget,
    HostRateLimiter,
    ScanError,
    build_opener,
    canonical_bundle,
    exclusive_lock,
    fetch_index,
    metadata_snapshot,
    package_records,
    read_json,
    sign_bundle,
    upload_bundle,
    utc_now,
)


def write_canonical_atomic(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(canonical_bundle(bundle))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def refresh_bundle(
    bundle: dict[str, Any],
    index: dict[str, Any],
    index_state: dict[str, Any],
    index_url: str,
    metadata_locale: str,
    bytes_used: int,
) -> dict[str, Any]:
    packages = bundle.get("packages")
    source = bundle.get("source")
    if not isinstance(packages, list) or not isinstance(source, dict):
        raise ScanError("existing bundle has no packages/source objects")
    records = package_records(index)
    for package in packages:
        if not isinstance(package, dict) or package.get("status") != "inspected":
            continue
        package_name = package.get("package_name")
        record = records.get(package_name)
        if record is None:
            raise ScanError(f"selected package is missing from the current F-Droid index: {package_name}")
        package["metadata"] = metadata_snapshot(record, index_url, metadata_locale)
        provenance = package.setdefault("provenance", {})
        if isinstance(provenance, dict):
            provenance["index_url"] = index_url
            provenance["index_sha256"] = index_state.get("sha256")

    bundle["generated_at"] = utc_now()
    source["index_url"] = index_url
    source["index"] = index_state
    policy = bundle.get("policy")
    if isinstance(policy, dict):
        policy["bytes_used"] = bytes_used
        policy["metadata_refresh"] = True
    return bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--cache-dir", default="./fdroid-cache")
    parser.add_argument("--bundle", default="catalog-import.json")
    parser.add_argument("--metadata-locale", default="en-US")
    parser.add_argument("--daily-byte-budget", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--max-index-bytes", type=int, default=DEFAULT_MAX_INDEX_BYTES)
    parser.add_argument("--host-interval", type=float, default=2.0)
    parser.add_argument("--retry-count", type=int, default=DEFAULT_RETRY_COUNT)
    parser.add_argument("--retry-backoff", type=float, default=DEFAULT_RETRY_BACKOFF)
    parser.add_argument("--signing-key")
    parser.add_argument("--signature", default="catalog-import.json.sig")
    parser.add_argument("--upload-url")
    parser.add_argument("--bearer-token-file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache_dir = Path(args.cache_dir)
    bundle_path = Path(args.bundle)
    try:
        with exclusive_lock(cache_dir / "scanner.lock"):
            bundle = read_json(bundle_path)
            budget = DailyBudget(cache_dir / "budget.json", args.daily_byte_budget)
            limiter = HostRateLimiter(args.host_interval)
            index, index_state = fetch_index(
                args.index_url,
                cache_dir,
                budget,
                limiter,
                args.max_index_bytes,
                args.retry_count,
                args.retry_backoff,
                build_opener(),
            )
            bundle = refresh_bundle(
                bundle,
                index,
                index_state,
                args.index_url,
                args.metadata_locale,
                budget.used,
            )
            write_canonical_atomic(bundle_path, bundle)
            if args.signing_key:
                signature_path = Path(args.signature)
                sign_bundle(bundle_path, signature_path, Path(args.signing_key))
                if args.upload_url:
                    upload_bundle(args, bundle_path, signature_path)
            elif args.upload_url:
                raise ScanError("--upload-url requires --signing-key")
    except (OSError, ScanError, ValueError, TypeError) as error:
        print(f"metadata refresh: {error}", file=sys.stderr)
        return 2
    print(f"refreshed metadata in {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
