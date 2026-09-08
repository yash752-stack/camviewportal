# CamView Portal — Environment Configuration Reference

**Audience:** DevOps / platform engineers deploying the CamView Examination
Compliance Portal.
**Scope:** every environment variable the application reads, its purpose,
type, default and constraints; the `.env` file format; reference `.env` files
for production, staging and a workstation; and the pre-flight checklist.
**Applies to:** repository `yash752-stack/camviewportal`, `main` branch, from
commit `794caee` (8 September 2026) onwards.

---

## 1. How configuration is loaded

The application is a single FastAPI process. All configuration is read once at
start-up by `backend/app/settings.py` (pydantic-settings) from, in order of
precedence:

1. **Real environment variables** — what Docker Compose `env_file`, ECS task
   definitions, systemd `EnvironmentFile` and Render/App Runner inject.
2. **A `.env` file in the process working directory.** Inside the container the
   working directory is `/app/backend`; on a bare-metal install it is
   `backend/`. With the supplied `docker-compose.aws.yml` the `.env` at the
   repository root is injected as environment variables, so no file needs to
   be placed inside the container.

Every application variable carries the prefix **`CAMVIEW_`**. Names are
case-insensitive to the loader; the canonical form below is upper-case.
Unknown variables are ignored. A variable that is set but empty is treated as
"unset" for the string settings and falls back to the default.

A change to any variable requires a process restart. Nothing is re-read at
runtime.

---

## 2. Variable reference

### 2.1 Runtime identity

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CAMVIEW_ENVIRONMENT` | `local` \| `staging` \| `production` | `local` | No | Label only; appears in logs. Set to `production` on any internet-facing host. |
| `PORT` | integer | `8077` | No | TCP port the container process listens on. The compose file publishes it on 80. Platforms that inject `PORT` (Render, App Runner) are honoured. |

### 2.2 Working directory and database

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CAMVIEW_DATA_DIR` | absolute path | `backend/data` (image: `/data`) | **Yes** in production | The application's only writable location: uploaded alert workbooks, report render workspace and thumbnails, the trunk-window store, the evidence cache, client marks added from the portal, and — only when no database URL is set — the SQLite database. Must be a mounted volume (EBS/EFS). When evidence is on S3 and rows are on RDS, nothing durable lives here and 20–50 GB is enough. |
| `CAMVIEW_DATABASE_URL` | SQLAlchemy URL | empty → SQLite at `$CAMVIEW_DATA_DIR/camview.db` | **Yes** in production | Postgres connection: `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME`. The `+psycopg` driver is bundled in the image. Leave empty only for a single-instance evaluation on a durable volume. |
| `CAMVIEW_DB_SSLMODE` | `require` \| `verify-full` \| `prefer` | `require` | No | TLS to Postgres. `require` encrypts without verifying the server certificate; use `verify-full` once the RDS CA bundle is on the host and `PGSSLROOTCERT` points at it. Never `disable` on a hosted database. Ignored for SQLite. |
| `CAMVIEW_DB_POOL_SIZE` | integer | `5` | No | Connections kept open **per worker process**. |
| `CAMVIEW_DB_MAX_OVERFLOW` | integer | `10` | No | Extra connections a worker may open under load. Ceiling per instance = workers × (pool + overflow); keep it under the RDS `max_connections` (~80 on `db.t4g.micro`). |
| `CAMVIEW_DB_STATEMENT_TIMEOUT_MS` | integer (ms) | `30000` | No | Server-side ceiling on any single statement. Raise rather than remove if a very large report legitimately needs longer. |

### 2.3 Evidence storage

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CAMVIEW_STORAGE_BACKEND` | `local` \| `s3` | `local` | **Set `s3` in production** | Where alert evidence frames live. `local`: under `$CAMVIEW_DATA_DIR/uploads/<exam>/evidence`, which must then be durable and sized for the whole vault (~1 MB per alert). `s3`: each frame is uploaded to the bucket at ingest, the row stores `s3://bucket/key`, the portal streams it back on demand and deletes it with the examination. |
| `CAMVIEW_S3_BUCKET` | string | empty | Yes when backend is `s3` | Bucket name. Private, default encryption on, public access blocked. Created and configured per `DEPLOY_AWS.md` §7. |
| `CAMVIEW_S3_REGION` | AWS region | `ap-south-1` | Yes when backend is `s3` | The bucket's region. |
| `CAMVIEW_S3_PREFIX` | string | empty | No | Optional key prefix, e.g. `portal` → `portal/evidence/<exam>/<alarm>.jpg`. Lets one bucket serve several environments. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | strings | unset | **Not on AWS** | Standard AWS credential chain. On EC2/ECS attach an **instance role** with the policy in `DEPLOY_AWS.md` §7 and leave these unset. Only a workstation or a non-AWS host needs keys. |

The boot log prints one line, `evidence storage: s3://<bucket> (<region>) reachable`
or `... NOT reachable: <reason>`. Treat `NOT reachable` as a failed deploy:
uploads will error rather than silently write to disk.

### 2.4 PDF export

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CAMVIEW_CHROME_PATH` | absolute path | auto-detected | Yes in the container | Chromium/Chrome/Edge binary used for headless PDF printing. The image installs Chromium at `/usr/bin/chromium`. |
| `CAMVIEW_CHROME_CONTAINER` | `1` \| `0` | `0` | **`1` in any container** | Adds `--no-sandbox --disable-dev-shm-usage --disable-setuid-sandbox`, without which Chromium fails to launch as a non-root container user. Leave `0` on a desktop. |

### 2.5 Retention

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CAMVIEW_RETENTION_MINUTES` | integer | `0` | No | `0` keeps every examination until deleted by hand — the setting for a real deployment. A positive value purges each examination (rows, frames in S3 or on disk, renders, trunk windows) that many minutes after upload; used only for a throw-away demo host. |

### 2.6 Optional integrations

| Variable | Type | Default | Required | Purpose |
|---|---|---|---|---|
| `CAMVIEW_GOOGLE_MAPS_KEY` | string | empty | No | Google Maps Platform key for centre imagery. When empty, no external request is ever made. |
| `CAMVIEW_MODALITIES_PATH` | path | `config/modalities.json` | No | Alarm-type catalogue. Override only for a customised catalogue. |
| `CAMVIEW_ASSETS_DIR` | path | `assets/` | No | Brand assets, fonts, report photographs, the client-mark library. Override only if the repository layout is changed. |
| `CAMVIEW_ALLOW_SYNTHETIC_CONFIDENCE` | `true` \| `false` | `true` | No | Alert exports carry no confidence score; the ingest derives a deterministic stand-in and flags it as synthetic in the UI. |

### 2.7 Not configurable by environment (by design)

- **Authentication.** `backend/app/auth.py` ships three demo accounts in plain
  text and a session cookie signed with a per-installation secret written to
  `$CAMVIEW_DATA_DIR/.session_secret` on first start. This is a placeholder:
  put an authenticating proxy (ALB with OIDC, or an SSO gateway) in front of
  any internet-facing deployment, or replace the module. See `DEPLOY_AWS.md` §5.
- **Client marks** (the conducting body's logo on report covers and in the
  header) are data, not configuration: the shipped library is
  `assets/clients/clients.json`; marks added from the portal are stored under
  `$CAMVIEW_DATA_DIR/clients/`. See `docs/REPORT_STANDARD.md`.

---

## 3. `.env` file format

- One `KEY=VALUE` per line; no spaces around `=`; no quotes needed unless the
  value contains `#` or leading/trailing spaces.
- Lines starting with `#` are comments. Blank lines are ignored.
- Passwords containing `@`, `:` or `/` inside `CAMVIEW_DATABASE_URL` must be
  URL-encoded (`@` → `%40`, `:` → `%3A`, `/` → `%2F`).
- The file is a secret. It is git-ignored (`.env`, `.env.*`, `*.env`; only
  `.env.example` is tracked). Restrict it to the deploying user:
  `chmod 600 .env`.

---

## 4. Reference `.env` files

### 4.1 Production — EC2 + RDS Postgres + S3 (recommended)

```dotenv
CAMVIEW_ENVIRONMENT=production
CAMVIEW_DATA_DIR=/data
PORT=8077

CAMVIEW_DATABASE_URL=postgresql+psycopg://camview:CHANGE_ME@camview-prod.abcdefgh1234.ap-south-1.rds.amazonaws.com:5432/camview
CAMVIEW_DB_SSLMODE=require
CAMVIEW_DB_POOL_SIZE=5
CAMVIEW_DB_MAX_OVERFLOW=10
CAMVIEW_DB_STATEMENT_TIMEOUT_MS=30000

CAMVIEW_STORAGE_BACKEND=s3
CAMVIEW_S3_BUCKET=camview-evidence-prod
CAMVIEW_S3_REGION=ap-south-1
CAMVIEW_S3_PREFIX=

CAMVIEW_CHROME_PATH=/usr/bin/chromium
CAMVIEW_CHROME_CONTAINER=1
CAMVIEW_RETENTION_MINUTES=0
```

Credentials for S3 come from the instance role; no `AWS_*` keys in the file.

### 4.2 Staging — same shape, separate bucket prefix and database

```dotenv
CAMVIEW_ENVIRONMENT=staging
CAMVIEW_DATA_DIR=/data
PORT=8077
CAMVIEW_DATABASE_URL=postgresql+psycopg://camview:CHANGE_ME@camview-staging.abcdefgh1234.ap-south-1.rds.amazonaws.com:5432/camview
CAMVIEW_DB_SSLMODE=require
CAMVIEW_STORAGE_BACKEND=s3
CAMVIEW_S3_BUCKET=camview-evidence-prod
CAMVIEW_S3_REGION=ap-south-1
CAMVIEW_S3_PREFIX=staging
CAMVIEW_CHROME_PATH=/usr/bin/chromium
CAMVIEW_CHROME_CONTAINER=1
CAMVIEW_RETENTION_MINUTES=0
```

### 4.3 Single-instance evaluation — SQLite and local frames on a durable volume

```dotenv
CAMVIEW_ENVIRONMENT=staging
CAMVIEW_DATA_DIR=/data
PORT=8077
CAMVIEW_DATABASE_URL=
CAMVIEW_STORAGE_BACKEND=local
CAMVIEW_CHROME_PATH=/usr/bin/chromium
CAMVIEW_CHROME_CONTAINER=1
CAMVIEW_RETENTION_MINUTES=0
```

The volume must then hold the whole evidence vault (~1 MB per alert frame).

### 4.4 Developer workstation (Windows / macOS, no container)

```dotenv
CAMVIEW_ENVIRONMENT=local
# CAMVIEW_DATA_DIR defaults to backend/data
CAMVIEW_STORAGE_BACKEND=local
CAMVIEW_CHROME_CONTAINER=0
# CAMVIEW_CHROME_PATH is auto-detected (Chrome/Edge/Brave)
```

To exercise the S3 path from a workstation add the bucket variables and
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` for a user limited to that bucket.

---

## 5. Pre-flight checklist

1. `CAMVIEW_DATA_DIR` is a mounted volume (`df -h /mnt/camview`), owned by
   uid 10001 (the container user): `chown 10001:10001 /mnt/camview`.
2. `CAMVIEW_DATABASE_URL` resolves: from the instance,
   `psql "$CAMVIEW_DATABASE_URL"` (or the container's Python) connects; the
   security group allows 5432 from the instance only.
3. The instance role carries the S3 policy from `DEPLOY_AWS.md` §7 and the
   bucket exists in `CAMVIEW_S3_REGION`; the boot log says `reachable`.
4. `CAMVIEW_CHROME_CONTAINER=1`; a test report downloads (open any
   examination → Report).
5. `GET /healthz` returns `200 {"ok": true}` and the load balancer health check
   points at it, with a 20 s start period and 300 s idle timeout for uploads.
6. TLS terminates at the ALB or nginx; the container serves plain HTTP.
7. An authenticating proxy or SSO gateway fronts the portal (§2.7).
8. `.env` is `chmod 600`, not committed, and its RDS password is rotated from
   the placeholder.

---

## 6. Related documents

- `DEPLOY_AWS.md` — build and push to ECR, EC2 + RDS + S3 runbook (§7), sizing.
- `docs/STORAGE.md` — the storage model, on-disk layout, S3 backend.
- `docker-compose.aws.yml` — the single-instance compose file.
- `.env.example` — annotated template of the variables above.
