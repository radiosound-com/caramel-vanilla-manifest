# Caramel Store catalog API

This is the small external-import and public-read service for the Caramel
Vanilla catalog. It has no third-party Python dependencies and is designed for
one non-HA SQLite-backed instance with persistent storage.

The scanner uploads a signed JSON bundle to `POST /v1/import`:

* `Authorization: Bearer <scoped-import-token>` authenticates the staging path.
* `X-Catalog-Signature` contains the base64-encoded detached SHA-256 OpenSSL
  signature sent by `tools/fdroid-scanner/scan.py`.
* The body must be `application/json` and is bounded by
  `CARAMEL_STORE_MAX_BUNDLE_BYTES`.
* The service verifies the signature, validates freshness/provenance/checksums
  and the scanner byte policy, then publishes a complete SQLite database and
  filtered index as an immutable revision.
* `active.json` is replaced only after the revision is complete, so a failed
  import leaves the previous catalog available. Repeating the same bundle is
  idempotent; older revisions are rejected.

Public reads require no import credential:

* `GET /healthz` — process health.
* `GET /readyz` — verification key and an active catalog revision are present.
* `GET /v1/catalog` — automotive-filtered catalog index.
* `GET /v1/catalog/<package-name>` — one catalog entry.
* `GET /metrics` on the optional metrics port — Prometheus text metrics.

The import endpoint and public reads should be exposed through separate OKD
Routes or network policies. TLS, VPN/mTLS, upload credentials, the catalog
verification key, and persistent storage are deployment concerns; the scanner
must not receive a kubeconfig or database credential.

## Local run

```sh
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out /tmp/catalog-key.pem
openssl rsa -in /tmp/catalog-key.pem -pubout -out /tmp/catalog-public.pem
printf '%s\n' replace-me > /tmp/catalog-token
mkdir -p /tmp/catalog-data
python3 server.py \
  --data-dir /tmp/catalog-data \
  --verify-key /tmp/catalog-public.pem \
  --import-token-file /tmp/catalog-token \
  --metrics-port 0
```

## Container build

From the repository root:

```sh
docker build -f tools/catalog-api/Dockerfile -t caramel-store-catalog:dev .
```

The image runs as UID/GID `10001`, listens on HTTP port 8080, and exposes the
optional Prometheus endpoint on port 9090. The OKD deployment must mount the
catalog PVC at `/data/catalog`, the public verification key at
`/etc/caramel-store/catalog-public.pem`, and the scoped import token at
`/etc/caramel-store/import-token`.
