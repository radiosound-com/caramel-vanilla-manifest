# Caramel Vanilla F-Droid scanner

This is the littleboy-side companion for the Caramel Vanilla catalog. It is
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
* Upload is restricted to HTTPS and uses a scoped bearer token. The endpoint
  should validate the signature and schema before atomically importing the
  bundle; it must not be a Kubernetes API or database credential.

The scanner uses the Android build-tree `aapt2` binary, so it can run against
the existing Android checkout on littleboy:

```sh
cd ~/android/16
python3 ~/caramel-vanilla-manifest/tools/fdroid-scanner/scan.py \
  --cache-dir ~/var/caramel-vanilla-fdroid \
  --aapt2 "$PWD/out/host/linux-x86/bin/aapt2" \
  --selection-file ~/var/caramel-vanilla-fdroid/selected.txt \
  --bundle ~/var/caramel-vanilla-fdroid/catalog-import.json \
  --signing-key /secure/path/catalog-import-signing-key.pem
```

The selection file is one package ID per line. Comments beginning with `#`
are ignored. Keep it curated; automotive compatibility is a manifest finding,
not a claim that every F-Droid app is safe to run while driving.

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

Run the offline tests with:

```sh
python3 -m unittest discover -s tests
```

