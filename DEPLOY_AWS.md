# CamView Portal — AWS deployment

For the DevOps team. The application is a single FastAPI container. There is no
build step, no separate frontend, no queue, no cache service. One image, one
port, one persistent volume.

---

## 1. The one thing that must not be got wrong

**All state lives in `CAMVIEW_DATA_DIR`, and it must be a mounted volume.**

That directory holds the SQLite database, the uploaded alert workbooks, and the
evidence vault (one image per alert — a real exam is tens of thousands of files,
tens of GB). The image defaults it to `/data` and declares `VOLUME ["/data"]`.

Anything written to the container's own filesystem is destroyed when the task is
replaced, which happens on every deploy. If `/data` is not backed by real
storage, **every examination uploaded is lost on the next deployment** and the
loss is silent — the portal comes back up looking healthy and empty.

| Platform | Mount at `/data` |
|---|---|
| EC2 (docker run / compose) | EBS volume, `-v /mnt/camview:/data` |
| ECS on EC2 | EBS volume + bind mount in the task definition |
| ECS Fargate | **EFS access point** — Fargate has no persistent block storage |
| App Runner | Not supported. App Runner has no persistent filesystem; use ECS |

See **`docs/STORAGE.md`** for the block diagram, the on-disk layout, and the
sizing basis — in short: the database holds paths, the volume holds the image
bytes, and a 100k-alert exam is ~100 GB of frames against ~50 MB of database.

> **With `CAMVIEW_STORAGE_BACKEND=s3` the evidence frames leave the volume.**
> Every frame is uploaded to the bucket at ingest and streamed back on demand;
> the row stores `s3://bucket/key`. The volume then holds only the working
> files (uploaded workbooks, thumbnails, PDF renders, a small evidence cache)
> and can be small and disposable. Together with RDS this makes the instance
> replaceable — the recommended production shape, §7 below.

---

## 2. Build and push to ECR

Run from a machine with Docker and the AWS CLI. Replace the account id and
region; everything else is copy-paste.

```bash
# --- variables ---------------------------------------------------------------
export AWS_ACCOUNT=123456789012
export AWS_REGION=ap-south-1
export REPO=camview-portal
export TAG=$(git rev-parse --short HEAD)          # tag by commit, not :latest
export ECR=$AWS_ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

# --- one-time: create the repository ----------------------------------------
aws ecr create-repository --repository-name $REPO --region $AWS_REGION \
  --image-scanning-configuration scanOnPush=true

# --- build, tag, push --------------------------------------------------------
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR

docker build --platform linux/amd64 -t $REPO:$TAG .
docker tag $REPO:$TAG $ECR/$REPO:$TAG
docker tag $REPO:$TAG $ECR/$REPO:latest
docker push $ECR/$REPO:$TAG
docker push $ECR/$REPO:latest
```

`--platform linux/amd64` matters if anyone builds on an Apple Silicon Mac —
without it the image is arm64 and will not start on an x86 task.

### If they want a file rather than a registry

```bash
docker build --platform linux/amd64 -t camview-portal:$TAG .
docker save camview-portal:$TAG | gzip > camview-portal-$TAG.tar.gz
# on the target host:
docker load < camview-portal-$TAG.tar.gz
```

Expect roughly **1.2–1.5 GB** compressed. The image carries Chromium, which is
needed for headless PDF report export and is most of the size. It cannot be
dropped without losing PDF generation.

---

## 3. Run it

```bash
docker run -d --name camview \
  -p 8077:8077 \
  -v /mnt/camview:/data \
  -e CAMVIEW_ENVIRONMENT=production \
  -e CAMVIEW_DATA_DIR=/data \
  --restart unless-stopped \
  $ECR/$REPO:$TAG
```

Health check: **`GET /healthz`** → `200 {"ok": true}`. Point the ALB target
group at it. Allow a ~20 s start period: the app opens the database and loads
the district GeoJSON on boot.

---

## 4. Configuration

Every setting is read with the `CAMVIEW_` prefix, from real environment
variables or a `.env` file. See `.env.example` for the annotated full list.

| Variable | Set it to |
|---|---|
| `CAMVIEW_DATA_DIR` | `/data` — the mounted volume |
| `CAMVIEW_ENVIRONMENT` | `production` |
| `CAMVIEW_DATABASE_URL` | empty for SQLite on the volume; a Postgres URL once there is more than one task |
| `CAMVIEW_STORAGE_BACKEND` | `s3` in production (frames in the bucket); `local` keeps them on the volume |
| `CAMVIEW_S3_BUCKET` | the evidence bucket, e.g. `camview-evidence-prod` |
| `CAMVIEW_S3_REGION` | the bucket's region, e.g. `ap-south-1` |
| `CAMVIEW_S3_PREFIX` | optional key prefix inside the bucket |
| `CAMVIEW_GOOGLE_MAPS_KEY` | optional; leave empty and no external call is ever made |
| `CAMVIEW_DB_POOL_SIZE` | `5` (default). Per worker process — see the sizing note below |
| `CAMVIEW_DB_MAX_OVERFLOW` | `10` (default) |
| `CAMVIEW_DB_SSLMODE` | `require` (default). Raise to `verify-full` once the RDS CA bundle is on the host |
| `CAMVIEW_DB_STATEMENT_TIMEOUT_MS` | `30000` (default). Ceiling on any single statement |

## Moving the database to RDS

The app resolves its engine from `CAMVIEW_DATABASE_URL` and nothing else, so
the switch is a configuration change — but the existing exams have to be
carried across, and an empty Postgres will not reproduce yesterday's reports.

**1. Provision.** Postgres 15 or later. `db.t4g.micro` is enough for a single
exam body; the database itself stays small (~50 MB per 100k-alert exam) because
it stores evidence *paths*, not image bytes. Put it in a private subnet and let
only the task security group reach 5432.

**2. Migrate the data.** From a host that can see both the old volume and RDS:

```bash
python tools/migrate_to_postgres.py \
  --target postgresql+psycopg://camview:PASSWORD@your-instance.rds.amazonaws.com:5432/camview \
  --dry-run
```

Then re-run without `--dry-run`. It copies every table in foreign-key order,
resets the Postgres identity sequences (skip that and the first new alert
raises a duplicate-key error), and verifies both row counts and per-exam,
per-modality totals before reporting success. It refuses to write into a
database that already holds rows unless you pass `--replace`.

**3. Cut over.** Set `CAMVIEW_DATABASE_URL` on the task definition and restart.
On boot the app creates any missing tables, adds missing columns, and creates
the indexes the models declare — including the unique `(exam_id, alarm_id)`
index that stops a repeated ingest from double-counting an exam.

**4. Keep the SQLite file** until the portal has served a full report from
Postgres. It is the only rollback.

### Connection sizing

`CAMVIEW_DB_POOL_SIZE` and `CAMVIEW_DB_MAX_OVERFLOW` are **per worker process**.
The real ceiling on the instance is

```
tasks x uvicorn workers x (pool_size + max_overflow)
```

against the RDS `max_connections`, which is about 80 on a `db.t4g.micro`. Two
tasks of two workers at the defaults is 60 — deliberately close, so raising
either number is a decision that arrives with an instance size. Connections are
opened with `sslmode=require`, a 10 s connect timeout, TCP keepalives and a
statement timeout, so a failover or a dropped idle session surfaces as a clean
error instead of a hung worker.

**On scaling out:** the default SQLite database is single-writer. One task is
fine and fast (WAL is enabled, readers are not blocked by writes). The moment a
second task runs against the same volume, move to RDS — but note the database
is only half of it. The **evidence vault is still local files**: two tasks on
separate volumes will each serve reports with the other's frames missing.
Until S3 offload is built, scaling out means EFS (shared, slower) or staying
on a single task.

Put secrets in **Secrets Manager or SSM Parameter Store** and inject them as
task-definition secrets. Do not bake a `.env` into the image; `.dockerignore`
excludes it deliberately.

---

## 5. Before it faces the internet

`backend/app/auth.py` ships **three hardcoded plaintext accounts** —
`admin/innovatiview`, `operator/camview2026`, `viewer/viewonly` — and a session
cookie with no expiry. Its own docstring says it is a placeholder, not
authentication, and those credentials are in a public repository.

This is fine behind a VPN or an ALB with OIDC in front. It is **not** fine as
the only gate on a public endpoint. Either put an authenticating proxy in front
or replace the module before launch.

Also worth setting at the load balancer: a request body limit generous enough
for evidence uploads. A full evidence archive is hundreds of MB, and the ALB
default idle timeout of 60 s will cut a large upload mid-flight — raise it to
300 s on that path, or have operators use the **evidence folder path** field,
which reads from a directory already on the instance and transfers nothing.

---

## 7. Production shape: EC2 + RDS + S3

One `t3.medium`, an RDS Postgres, one S3 bucket. The instance is disposable:
rows in RDS, frames in S3, and the volume holds only working files.

**1. S3 bucket** (private, versioning optional, no public access):

```bash
export AWS_REGION=ap-south-1
export BUCKET=camview-evidence-prod
aws s3api create-bucket --bucket $BUCKET --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket $BUCKET --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

**2. IAM role for the instance** — the portal never needs keys on disk. Policy
(replace the bucket name), attach it to a role, attach the role to the EC2
instance as its instance profile:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:ListBucket"],
     "Resource": "arn:aws:s3:::camview-evidence-prod"},
    {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
     "Resource": "arn:aws:s3:::camview-evidence-prod/*"}
  ]
}
```

**3. RDS Postgres** — Postgres 15+, `db.t4g.micro` is enough, private subnet,
security group allowing 5432 from the instance's security group only. Create
the database and user, then the URL for `.env` is
`postgresql+psycopg://camview:PASSWORD@ENDPOINT:5432/camview`. Migration of an
existing SQLite volume: `tools/migrate_to_postgres.py` (§"Moving the database").

**4. The instance** — Amazon Linux 2023 or Ubuntu 22.04, Docker and the compose
plugin installed, a 30 GB EBS volume mounted at `/mnt/camview`, security group
allowing 80/443 from the internet (or from the ALB) and 22 from the office.

```bash
sudo mkdir -p /mnt/camview && sudo chown 10001:10001 /mnt/camview   # the container's user
git clone https://github.com/yash752-stack/camviewportal.git && cd camviewportal
cp .env.example .env && nano .env        # RDS url, bucket, region; nothing else needs changing
docker compose -f docker-compose.aws.yml up -d --build
docker compose -f docker-compose.aws.yml logs -f portal   # first line reports "evidence storage: s3://... reachable"
curl -s http://127.0.0.1/healthz
```

The boot log prints the storage status; if it says `NOT reachable`, the
instance role or the bucket name is wrong and uploads will fail rather than
silently fall back to disk.

**5. TLS.** Put an ALB (ACM certificate, target group on port 80, health check
`/healthz`, idle timeout 300 s for evidence uploads) or nginx with certbot in
front. Nothing in the container terminates TLS.

**6. Backups.** RDS automated backups cover the rows; S3 versioning or a
lifecycle rule to Glacier covers the frames. Nothing on the instance needs
backing up.

**Upgrading:** `git pull && docker compose -f docker-compose.aws.yml up -d --build`.
Because nothing durable lives on the instance, a broken upgrade is undone by
checking out the previous commit and running the same command.

---

## 6. Sizing

Measured on the reference dataset (100k alerts, 1,200 centres):

| | |
|---|---|
| Idle memory | ~200 MB; ~500 MB while rendering a PDF (Chromium) |
| CPU | 1 vCPU is enough for the portal; PDF export is the only spike |
| Map render | ~25 ms, cached per lens |
| Storage | database is small; the **evidence vault** dominates — size the volume from the expected exam count, ~1 MB per alert frame |

A `t3.medium` (2 vCPU / 4 GB) with a right-sized EBS volume runs this
comfortably. Scale the volume, not the instance.
