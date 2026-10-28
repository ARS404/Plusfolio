FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm test && npm run build

FROM python:3.14-slim-bookworm AS prepared
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg age fonts-dejavu-core fontconfig libfontconfig1 libfreetype6 \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements*.lock ./
COPY scripts/download_asset.py scripts/install_locked.py scripts/
RUN python scripts/install_locked.py requirements-server.lock
COPY scripts/setup_tex.py scripts/setup_tex.py
COPY backend/core/tex_templates/ backend/core/tex_templates/
RUN --mount=type=cache,id=plusfolio-tectonic-0.17.0-v33,target=/var/cache/plusfolio-tex,sharing=locked \
    PLUSFOLIO_TEX_SHARED_CACHE=/var/cache/plusfolio-tex python scripts/setup_tex.py

FROM prepared AS application
COPY backend/ backend/
COPY scripts/ scripts/
COPY data/ data/
COPY docs/ docs/
COPY embeddings/ embeddings/
COPY frontend/ frontend/
COPY deploy/ deploy/
COPY README.md requirements.txt compose.yml .dockerignore .gitignore ./
COPY .github/ .github/
COPY --from=frontend /src/frontend/dist frontend/dist
RUN mkdir -p /run/plusfolio-tex /backups /deployment \
 && chown -R 65532:65532 /app/.local /run/plusfolio-tex /backups
RUN printf 'plusfolio:x:65532:65532:Plusfolio:/tmp:/usr/sbin/nologin\n' >> /etc/passwd && printf 'plusfolio:x:65532:\n' >> /etc/group
USER 65532:65532
ENV PLUSFOLIO_DEMO=0
EXPOSE 8000
CMD ["gunicorn", "--chdir", "backend", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "/dev/null", "--error-logfile", "-"]


# The compiler contains no database/application sources, fixtures or credentials.
FROM python:3.14-slim-bookworm AS compiler
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8
WORKDIR /app
COPY --from=prepared /usr/share/fonts /usr/share/fonts
COPY --from=prepared /etc/fonts /etc/fonts
COPY --from=prepared /usr/share/fontconfig /usr/share/fontconfig
COPY --from=prepared /app/backend/core/tex_templates backend/core/tex_templates
COPY --from=prepared /app/.local/tools .local/tools
COPY --from=prepared /app/.local/tectonic-cache .local/tectonic-cache
COPY scripts/tex_service.py scripts/tex_service.py
COPY backend/core/tex_worker.py backend/core/tex_worker.py
RUN mkdir -p /run/plusfolio-tex && chown -R 65532:65532 /run/plusfolio-tex && chmod -R a+rX /app/.local
RUN printf 'plusfolio:x:65532:65532:Plusfolio:/tmp:/usr/sbin/nologin\n' >> /etc/passwd && printf 'plusfolio:x:65532:\n' >> /etc/group
USER 65532:65532
ENV PLUSFOLIO_ISOLATED_TEX=1 PLUSFOLIO_TEX_SOCKET=/run/plusfolio-tex/compiler.sock
CMD ["python","scripts/tex_service.py"]
