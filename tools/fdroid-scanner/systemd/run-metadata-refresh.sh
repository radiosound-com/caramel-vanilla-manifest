#!/usr/bin/env bash
# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.

set -euo pipefail
umask 0007

state_dir="${CARAMEL_SCANNER_STATE_DIR:-/var/lib/caramel-store-scanner}"
bundle_dir="${CARAMEL_SCANNER_BUNDLE_DIR:-$state_dir/bundles}"
refresh_script="${CARAMEL_SCANNER_SCRIPT:-/opt/caramel-vanilla-manifest/tools/fdroid-scanner/refresh_metadata.py}"
python="${CARAMEL_SCANNER_PYTHON:-/usr/bin/python3}"
index_url="${CARAMEL_SCANNER_INDEX_URL:-https://f-droid.org/repo/index-v2.json}"
signing_key="${CARAMEL_SCANNER_SIGNING_KEY:-/etc/caramel-store/catalog-signing-key.pem}"
token_file="${CARAMEL_SCANNER_TOKEN_FILE:-/etc/caramel-store/import-token}"
upload_url="${CARAMEL_SCANNER_UPLOAD_URL:-https://caramel-vanilla-store.apps.radiosound.com/v1/import}"

latest_bundle="$(
    find "$bundle_dir" -maxdepth 1 -type f \
        -name 'catalog-import-*.json' \
        ! -name 'catalog-metadata-refresh-*.json' \
        -printf '%f\n' | sort | tail -n 1
)"
if [[ -z "$latest_bundle" ]]; then
    echo "metadata refresh: no scanner bundle found in $bundle_dir" >&2
    exit 2
fi

source_bundle="$bundle_dir/$latest_bundle"
if [[ ! -s "$source_bundle" || ! -s "$source_bundle.sig" ]]; then
    echo "metadata refresh: latest scanner bundle is incomplete" >&2
    exit 2
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
bundle="$bundle_dir/catalog-metadata-refresh-$stamp.json"
signature="$bundle.sig"
cp -- "$source_bundle" "$bundle"

exec "$python" "$refresh_script" \
    --index-url "$index_url" \
    --cache-dir "$state_dir" \
    --bundle "$bundle" \
    --signature "$signature" \
    --signing-key "$signing_key" \
    --upload-url "$upload_url" \
    --bearer-token-file "$token_file"
