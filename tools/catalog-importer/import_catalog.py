#!/usr/bin/env python3
"""Validate and atomically import a Caramel Vanilla catalog bundle.

This is a small reference importer for the future staging service.  It keeps
the scanner outside the trust boundary: the importer validates the bundle,
optionally verifies an OpenSSL detached signature, replaces the SQLite catalog
inside one transaction, and writes a filtered read-only index atomically.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA = "https://caramel-vanilla.radiosound.com/schemas/catalog-import-v1.json"
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9_.]+$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
LOCALE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*$")


class ImportError(ValueError):
    """Raised when an import bundle is unsafe or malformed."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImportError(f"cannot read JSON bundle {path}: {error}") from error
    if not isinstance(value, dict):
        raise ImportError("bundle root must be an object")
    return value


def require_https(value: Any, field: str) -> str:
    parsed = urlparse(value) if isinstance(value, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ImportError(f"{field} must be an HTTPS URL")
    return value


def validate_metadata(value: Any, package_name: str) -> dict[str, Any]:
    if value is None:
        raise ImportError(f"{package_name}.metadata is required")
    if not isinstance(value, dict):
        raise ImportError(f"{package_name}.metadata must be an object")
    for key in ("display_name", "summary", "icon_url"):
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise ImportError(f"{package_name}.metadata.{key} is required")
    allowed = {
        "locale",
        "display_name",
        "summary",
        "description",
        "categories",
        "license",
        "icon_url",
        "feature_graphic_url",
        "screenshot_urls",
    }
    unknown = set(value) - allowed
    if unknown:
        raise ImportError(f"{package_name}.metadata has unsupported fields: {sorted(unknown)}")
    locale = value.get("locale")
    if locale is not None and (not isinstance(locale, str) or not LOCALE.fullmatch(locale)):
        raise ImportError(f"{package_name}.metadata.locale is invalid")
    for key, limit in (
        ("display_name", 240),
        ("summary", 500),
        ("description", 20000),
        ("license", 120),
    ):
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or not item.strip() or len(item) > limit):
            raise ImportError(f"{package_name}.metadata.{key} is invalid")
    categories = value.get("categories")
    if categories is not None:
        if (
            not isinstance(categories, list)
            or len(categories) > 12
            or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in categories)
        ):
            raise ImportError(f"{package_name}.metadata.categories is invalid")
    for key in ("icon_url", "feature_graphic_url"):
        if value.get(key) is not None:
            require_https(value[key], f"{package_name}.metadata.{key}")
    screenshots = value.get("screenshot_urls")
    if screenshots is not None:
        if not isinstance(screenshots, list) or len(screenshots) > 6:
            raise ImportError(f"{package_name}.metadata.screenshot_urls is invalid")
        for item in screenshots:
            require_https(item, f"{package_name}.metadata.screenshot_urls")
    return value


def parse_timestamp(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise ImportError("generated_at must be an RFC 3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ImportError("generated_at must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ImportError("generated_at must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_bundle(bundle: dict[str, Any], max_age_hours: float = 48.0) -> None:
    if bundle.get("$schema") != SCHEMA or bundle.get("bundle_version") != 1:
        raise ImportError("unsupported catalog bundle schema or version")

    generated_at = parse_timestamp(bundle.get("generated_at"))
    age = dt.datetime.now(dt.timezone.utc) - generated_at
    if age.total_seconds() < -300 or age > dt.timedelta(hours=max_age_hours):
        raise ImportError("catalog bundle is outside the freshness window")

    source = bundle.get("source")
    policy = bundle.get("policy")
    packages = bundle.get("packages")
    if not isinstance(source, dict) or not isinstance(policy, dict):
        raise ImportError("source and policy must be objects")
    if not isinstance(packages, list):
        raise ImportError("packages must be an array")
    if source.get("name") != "F-Droid":
        raise ImportError("unsupported catalog source")
    require_https(source.get("index_url"), "source.index_url")
    if not isinstance(source.get("index"), dict):
        raise ImportError("source.index must be an object")

    budget = policy.get("daily_byte_budget")
    bytes_used = policy.get("bytes_used")
    if not isinstance(budget, int) or budget < 1:
        raise ImportError("policy.daily_byte_budget must be a positive integer")
    if not isinstance(bytes_used, int) or bytes_used < 0 or bytes_used > budget:
        raise ImportError("policy.bytes_used exceeds the daily byte budget")
    max_apk_bytes = policy.get("max_apk_bytes")
    if not isinstance(max_apk_bytes, int) or max_apk_bytes < 1:
        raise ImportError("policy.max_apk_bytes must be a positive integer")
    selected = policy.get("selected_packages")
    if not isinstance(selected, list) or any(
        not isinstance(item, str) or not PACKAGE_NAME.fullmatch(item) for item in selected
    ):
        raise ImportError("policy.selected_packages contains an invalid package name")
    if len(selected) != len(set(selected)):
        raise ImportError("policy.selected_packages contains duplicates")

    mirrors = source.get("advertised_mirrors", [])
    if not isinstance(mirrors, list):
        raise ImportError("source.advertised_mirrors must be an array")
    for mirror in mirrors:
        require_https(mirror, "source.advertised_mirrors")

    seen: set[str] = set()
    selected_set = set(selected)
    for package in packages:
        if not isinstance(package, dict):
            raise ImportError("each package must be an object")
        name = package.get("package_name")
        if not isinstance(name, str) or not PACKAGE_NAME.fullmatch(name):
            raise ImportError("package_name is invalid")
        if name in seen:
            raise ImportError(f"duplicate package: {name}")
        seen.add(name)
        status = package.get("status")
        if status not in {"inspected", "not_in_index"}:
            raise ImportError(f"unsupported status for {name}")
        if status == "not_in_index":
            continue
        digest = package.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ImportError(f"{name} has no valid SHA-256")
        require_https(package.get("apk_url"), f"{name}.apk_url")
        require_https(package.get("canonical_apk_url"), f"{name}.canonical_apk_url")
        if package.get("hash_matches_index") is not True:
            raise ImportError(f"{name} did not match the F-Droid index checksum")
        downloaded_size = package.get("downloaded_size")
        if (
            not isinstance(downloaded_size, int)
            or downloaded_size < 1
            or downloaded_size > max_apk_bytes
        ):
            raise ImportError(f"{name} has an invalid downloaded APK size")
        mirror = package.get("mirror_used")
        if mirror is not None:
            require_https(mirror, f"{name}.mirror_used")
        findings = package.get("manifest_findings", {})
        if not isinstance(findings, dict):
            raise ImportError(f"{name}.manifest_findings must be an object")
        validate_metadata(package.get("metadata"), name)
        provenance = package.get("provenance")
        if not isinstance(provenance, dict):
            raise ImportError(f"{name}.provenance must be an object")
        require_https(provenance.get("index_url"), f"{name}.provenance.index_url")
        require_https(provenance.get("download_url"), f"{name}.provenance.download_url")
        index_sha256 = provenance.get("index_sha256")
        if not isinstance(index_sha256, str) or not SHA256.fullmatch(index_sha256):
            raise ImportError(f"{name}.provenance.index_sha256 is invalid")
        upstream_urls = package.get("upstream_urls", {})
        if not isinstance(upstream_urls, dict):
            raise ImportError(f"{name}.upstream_urls must be an object")
    if seen != selected_set:
        raise ImportError("packages must exactly match policy.selected_packages")


def verify_signature(bundle_path: Path, signature_path: Path, public_key: Path) -> None:
    result = subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-verify",
            str(public_key),
            "-signature",
            str(signature_path),
            str(bundle_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode or result.stdout.strip() != "Verified OK":
        detail = result.stderr.strip() or result.stdout.strip() or "signature verification failed"
        raise ImportError(detail)


def filtered_index(bundle: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for package in bundle["packages"]:
        if package.get("status") != "inspected":
            continue
        findings = package.get("manifest_findings", {})
        if not findings.get("automotive_candidate"):
            continue
        entries.append(
            {
                "package_name": package["package_name"],
                "version_code": package.get("version_code"),
                "version_name": findings.get("version_name"),
                "apk_url": package["canonical_apk_url"],
                "sha256": package["sha256"],
                "metadata": package.get("metadata", {}),
                "upstream_urls": package.get("upstream_urls", {}),
                "manifest_findings": {
                    "automotive_candidate": True,
                    "automotive_feature": bool(findings.get("automotive_feature")),
                    "car_app_service": bool(findings.get("car_app_service")),
                },
            }
        )
    entries.sort(key=lambda item: item["package_name"])
    return {
        "catalog_version": 1,
        "generated_at": bundle["generated_at"],
        "source": bundle["source"]["name"],
        "entries": entries,
        "release_signing": "separate_controlled_step",
    }


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def import_sqlite(path: Path, bundle: dict[str, Any], bundle_sha256: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS packages (
                package_name TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                version_code INTEGER,
                version_name TEXT,
                apk_url TEXT,
                sha256 TEXT,
                metadata TEXT NOT NULL,
                manifest_findings TEXT NOT NULL,
                upstream_urls TEXT NOT NULL
            )
            """
        )
        connection.execute("DELETE FROM packages")
        connection.execute("DELETE FROM catalog_meta")
        metadata = [
            ("bundle_version", str(bundle["bundle_version"])),
            ("generated_at", bundle["generated_at"]),
            ("source", bundle["source"]["name"]),
            ("source_index_url", bundle["source"]["index_url"]),
        ]
        if bundle_sha256 is not None:
            metadata.append(("bundle_sha256", bundle_sha256))
        connection.executemany(
            "INSERT INTO catalog_meta(key, value) VALUES(?, ?)",
            metadata,
        )
        rows = []
        for package in bundle["packages"]:
            rows.append(
                (
                    package["package_name"],
                    package["status"],
                    package.get("version_code"),
                    package.get("manifest_findings", {}).get("version_name"),
                    package.get("canonical_apk_url"),
                    package.get("sha256"),
                    json.dumps(package.get("metadata", {}), sort_keys=True),
                    json.dumps(package.get("manifest_findings", {}), sort_keys=True),
                    json.dumps(package.get("upstream_urls", {}), sort_keys=True),
                )
            )
        connection.executemany(
            """
            INSERT INTO packages(
                package_name, status, version_code, version_name, apk_url,
                sha256, metadata, manifest_findings, upstream_urls
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--signature", type=Path)
    parser.add_argument("--verify-key", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=48.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle = read_json(args.bundle)
        validate_bundle(bundle, args.max_age_hours)
        if bool(args.signature) != bool(args.verify_key):
            raise ImportError("--signature and --verify-key must be supplied together")
        if args.signature and args.verify_key:
            verify_signature(args.bundle, args.signature, args.verify_key)
        import_sqlite(args.database, bundle)
        write_json_atomic(args.index, filtered_index(bundle))
    except (ImportError, OSError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"catalog importer: {error}", file=sys.stderr)
        return 2
    print(f"imported {args.bundle} into {args.database} and {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
