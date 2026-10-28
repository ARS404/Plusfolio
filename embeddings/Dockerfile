FROM python:3.14-slim-bookworm AS model
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/model-build
COPY scripts/download_asset.py ./
COPY embeddings/download.py embeddings/model.lock.json ./
# Model preparation depends only on immutable artifacts and their downloader.
RUN --mount=type=cache,id=plusfolio-embedding-artifacts,target=/var/cache/plusfolio-model,sharing=locked \
    python download.py --directory /var/cache/plusfolio-model \
 && mkdir -p /model && cp -a /var/cache/plusfolio-model/. /model/

FROM python:3.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1
WORKDIR /opt/embeddings
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY embeddings/requirements.lock ./requirements.lock
COPY scripts/download_asset.py scripts/install_locked.py ./
RUN --mount=type=cache,id=plusfolio-wheels,target=/var/cache/plusfolio-wheels,sharing=locked \
    python install_locked.py requirements.lock --cache-dir /var/cache/plusfolio-wheels
COPY embeddings/download.py embeddings/model.lock.json ./
# Runtime package changes do not invalidate model preparation.
COPY --from=model /model /model
COPY embeddings/ ./
USER 65532:65532
ENV MODEL_DIRECTORY=/model EMBEDDING_THREADS=2
EXPOSE 8011
HEALTHCHECK --interval=20s --timeout=3s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8011/health',timeout=2)"
CMD ["python", "server.py", "--host", "0.0.0.0"]

ARG APP_VERSION=unknown
ARG RELEASE_STATUS=unknown
ARG VCS_REF=unknown
LABEL org.opencontainers.image.version=$APP_VERSION \
      io.plusfolio.release-status=$RELEASE_STATUS \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.source="https://github.com/ARS404/Plusfolio"
