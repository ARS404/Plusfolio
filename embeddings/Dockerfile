FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1
WORKDIR /opt/embeddings
COPY embeddings/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY embeddings/ ./
# Fetch only while building. For offline deploy, copy the prepared /model or mirror this image in Russia.
RUN python download.py --directory /model
USER 65532:65532
ENV MODEL_DIRECTORY=/model EMBEDDING_THREADS=2
EXPOSE 8011
HEALTHCHECK --interval=20s --timeout=3s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8011/health',timeout=2)"
CMD ["python", "server.py", "--host", "0.0.0.0"]
