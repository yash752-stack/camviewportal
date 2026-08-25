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
# /data is a MOUNT POINT, not image content: SQLite db, uploaded workbooks and
# the evidence vault live there. On AWS attach an EBS volume (EC2 / ECS-on-EC2)
# or an EFS access point (Fargate) at /data -- anything written to the container
# filesystem dies with the task. Render overrides this to /tmp on purpose,
# because that platform has no persistent disk on the free plan.
ENV CAMVIEW_DATA_DIR=/data     CAMVIEW_CHROME_PATH=/usr/bin/chromium     CAMVIEW_CHROME_CONTAINER=1     PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1

# Run as a non-root user. The app only writes under CAMVIEW_DATA_DIR, so that is
# the one path it needs to own.
RUN useradd --create-home --uid 10001 camview     && mkdir -p /data     && chown -R camview:camview /data /app
VOLUME ["/data"]
USER camview

# The platform provides $PORT (Render, App Runner); default 8077 so a plain
# `docker run -p 8077:8077` works unchanged.
ENV PORT=8077
EXPOSE 8077

# Point the ALB / ECS target group at /healthz. This HEALTHCHECK is what
# `docker ps` and ECS container-level health report on.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3     CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8077')+'/healthz',timeout=4).status==200 else 1)"

# Bind to 0.0.0.0 so the platform can reach it. Shell form so $PORT expands.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --log-level warning
