# Caramel Vanilla F-Droid scanner

This is the build-independent companion for the Caramel Vanilla catalog. It is
intentionally bounded and does not become an APK mirror:

* F-Droid's `index-v2.json` is fetched with `ETag`/`If-Modified-Since`.
* A local lock permits one run at a time; a daily byte budget and per-host
  delay prevent accidental bulk downloads.
* APK inspection is opt-in by package ID or selection file. The scanner never
  attempt to download the whole F-Droid catalog.
* APKs are removed after inspection unless `--keep-apks` is supplied.
* The result records package metadata, manifest findings, SHA-256, index
  provenance, and upstream URLs. It can be signed with an offline-controlled
  OpenSSL signing key.
* Mirroring is disabled by default. To opt in for APK inspection, add
  `--use-mirrors`; the scanner accepts only HTTPS mirrors advertised in
  `repo.mirrors`, retries transient failures with exponential backoff, and
  falls back to the canonical HTTPS APK URL.
* Upload is restricted to HTTPS and uses a scoped bearer token. The endpoint
  should validate the signature and schema before atomically importing the
  bundle; it must not be a Kubernetes API or database credential.

The scanner uses the Android build-tree `aapt2` binary, so it can run against
any completed Android checkout. Set paths appropriate to your workstation:

```sh
export ANDROID_TOP=/path/to/caramel-vanilla-android-16
export CARAMEL_MANIFEST=/path/to/caramel-vanilla-manifest
export FDROID_CACHE=/path/to/caramel-vanilla-fdroid
cd "$ANDROID_TOP"
python3 "$CARAMEL_MANIFEST/tools/fdroid-scanner/scan.py" \
  --cache-dir "$FDROID_CACHE" \
  --aapt2 "$PWD/out/host/linux-x86/bin/aapt2" \
  --selection-file "$FDROID_CACHE/selected.txt" \
  --bundle "$FDROID_CACHE/catalog-import.json" \
  --signing-key /secure/path/catalog-import-signing-key.pem
```

The selection file is one package ID per line. Comments beginning with `#`
are ignored. Keep it curated; automotive compatibility is a manifest finding,
not a claim that every F-Droid app is safe to run while driving.

Mirror-enabled inspection is still bounded to the explicitly selected package
IDs. For example:

```sh
python3 scan.py ... \
  --use-mirrors \
  --retry-count 3 \
  --retry-backoff 1
```

The scanner ignores non-HTTPS mirror entries, including onion URLs, and keeps
the canonical HTTPS URL as the last fallback. The bundle records the
advertised HTTPS mirrors, canonical APK URL, selected download URL, and mirror
used when one succeeds. See [issue #1](https://github.com/radiosound-com/caramel-vanilla-manifest/issues/1)
for the scope and acceptance criteria.

The optional upload form is:

```sh
python3 scan.py ... \
  --upload-url https://catalog-import.example.invalid/v1/import \
  --bearer-token-file /secure/path/import-token
```

The importer should verify the detached signature from the
`X-Catalog-Signature` header, validate `bundle.schema.json`, reject stale or
duplicate index revisions, and commit the catalog transaction atomically.
Public catalog reads should use a separate endpoint and credential.

For local or staging validation, the repository includes a dependency-free
reference importer. It replaces the SQLite catalog in one transaction and
writes an automotive-filtered read index with an atomic rename:

```sh
python3 ../catalog-importer/import_catalog.py \
  --bundle "$FDROID_CACHE/catalog-import.json" \
  --database "$FDROID_CACHE/catalog.sqlite3" \
  --index "$FDROID_CACHE/catalog-index.json"
```

The reference importer is not the production OKD API; it defines the safe
bundle-to-catalog behavior that the staging service must preserve.

Run the offline tests with:

```sh
python3 -m unittest discover -s tests
```
