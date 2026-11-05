# Discogs Backup (cloud agnostic)
#
# どのクラウドでも同じイメージを使い、保存先だけ BACKUP_DEST で切り替える。
#   docker build --build-arg STORAGE_BACKEND=gcs -t discogs-backup .
#   STORAGE_BACKEND: gcs | s3 | azure | none
FROM python:3.15-slim

ARG STORAGE_BACKEND=gcs

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MODE=http \
    PORT=8080

WORKDIR /app

COPY requirements.txt requirements-gcs.txt requirements-s3.txt requirements-azure.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    case "${STORAGE_BACKEND}" in \
      gcs)   pip install --no-cache-dir -r requirements-gcs.txt ;; \
      s3)    pip install --no-cache-dir -r requirements-s3.txt ;; \
      azure) pip install --no-cache-dir -r requirements-azure.txt ;; \
      none)  echo "skip storage backend" ;; \
      *)     echo "unknown STORAGE_BACKEND: ${STORAGE_BACKEND}" >&2; exit 1 ;; \
    esac

COPY discogs_backup.py storage.py worker.py ./

RUN useradd --create-home --shell /usr/sbin/nologin app && chown -R app:app /app
USER app

EXPOSE 8080

# クラウド側のタイムアウトより短くならないよう余裕を持たせる
CMD exec gunicorn --bind ":${PORT}" --workers 1 --threads 4 --timeout 600 worker:app
