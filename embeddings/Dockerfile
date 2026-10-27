FROM python:3.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1
WORKDIR /opt/embeddings
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY embeddings/requirements.lock ./requirements.lock
COPY scripts/download_asset.py scripts/install_locked.py ./
RUN python install_locked.py requirements.lock
COPY embeddings/download.py embeddings/model.lock.json ./
# Fetch only while building. For offline deploy, copy the prepared /model or mirror this image in Russia.
RUN python download.py --directory /model
COPY embeddings/ ./
USER 65532:65532
ENV MODEL_DIRECTORY=/model EMBEDDING_THREADS=2
EXPOSE 8011
HEALTHCHECK --interval=20s --timeout=3s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8011/health',timeout=2)"
CMD ["python", "server.py", "--host", "0.0.0.0"]
