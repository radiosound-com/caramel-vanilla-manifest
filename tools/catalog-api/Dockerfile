FROM python:3.12-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 caramel \
    && useradd --system --uid 10001 --gid caramel --home-dir /nonexistent --shell /usr/sbin/nologin caramel

WORKDIR /app
COPY tools/catalog-importer/import_catalog.py /app/import_catalog.py
COPY tools/catalog-api/server.py /app/server.py

RUN mkdir -p /data/catalog /etc/caramel-store \
    && chown -R caramel:caramel /data/catalog /app

ENV PYTHONUNBUFFERED=1 \
    CARAMEL_STORE_DATA_DIR=/data/catalog \
    CARAMEL_STORE_VERIFY_KEY=/etc/caramel-store/catalog-public.pem \
    CARAMEL_STORE_IMPORT_TOKEN_FILE=/etc/caramel-store/import-token \
    CARAMEL_STORE_PORT=8080 \
    CARAMEL_STORE_METRICS_PORT=9090

USER 10001:10001
EXPOSE 8080 9090
ENTRYPOINT ["python3", "/app/server.py"]
