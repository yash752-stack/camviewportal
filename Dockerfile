# CamView Compliance Portal — container image for Render (or any Docker host).
#
# Python 3.12 (matches the app's supported version) + Chromium (so PDF report
# export works headlessly in the container). Data lives in an ephemeral /tmp
# directory that is wiped on every restart — nothing persists.

FROM python:3.12-slim

# --- system deps: Chromium for headless PDF printing ------------------------
# The 'chromium' package declares its own runtime dependencies, so apt pulls
# the right versions automatically — we don't list libnss3/libasound2/etc by
# hand, because those names drift between Debian releases (e.g. libasound2 ->
# libasound2t64) and would break the build. We add font packages so printed
# PDFs render text correctly.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- python deps first (better layer caching) --------------------------------
# We install straight from PyPI here (the container has internet), NOT from the
# bundled Windows wheels — those are win_amd64 and won't install on Linux.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# --- app code ----------------------------------------------------------------
COPY backend /app/backend
COPY config  /app/config
COPY assets  /app/assets

WORKDIR /app/backend

# --- runtime configuration ---------------------------------------------------
# Ephemeral storage: SQLite db + uploads + evidence all under /tmp, wiped on
# restart. Chromium lives at a known path and needs container-safe flags.
ENV CAMVIEW_DATA_DIR=/tmp/camview_data \
    CAMVIEW_CHROME_PATH=/usr/bin/chromium \
    CAMVIEW_CHROME_CONTAINER=1 \
    PYTHONUNBUFFERED=1

# Render provides $PORT; default to 8077 for local `docker run`.
ENV PORT=8077
EXPOSE 8077

# Bind to 0.0.0.0 so the platform can reach it. Shell form so $PORT expands.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --log-level warning
