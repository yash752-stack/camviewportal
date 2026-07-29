# Deploy the CamView Compliance Portal to Render (free) — a shareable link

This gives you a public `https://…onrender.com` link. Data is **ephemeral**:
it lives under `/tmp` and is wiped whenever the service restarts or wakes from
sleep. So someone can upload an Excel, create an exam, and generate a report —
and nothing is stored long-term. Perfect for a demo; **not** for real
candidate data (see "Important" at the bottom).

## What's included (already added to this folder)
- `Dockerfile` — Python 3.12 + Chromium (so PDF reports work) + the app.
- `render.yaml` — one-click blueprint (free plan, health check, env vars).
- `.dockerignore` — keeps the Windows wheels/venv out of the image.

You do **not** need Python, wheels, or run.bat/run.sh for the hosted version —
those are only for the offline Windows/Mac bundle. The container installs its
Linux packages fresh from PyPI.

---

## Option A — test it locally first (recommended, ~2 min)
If you have Docker Desktop:

```bash
cd Compliance_Portal
docker build -t camview-portal .
docker run --rm -p 8077:8077 camview-portal
```

Open http://127.0.0.1:8077 — create an exam, generate a report. If the PDF
downloads, the container is good and Render will behave the same.

## Option B — deploy to Render

### 1. Put this folder in a Git repo
Render deploys from GitHub/GitLab. From inside `Compliance_Portal`:

```bash
git init
git add .
git commit -m "CamView Compliance Portal — Render deploy"
```
Create an empty repo on GitHub, then:
```bash
git remote add origin https://github.com/<you>/camview-portal.git
git branch -M main
git push -u origin main
```

### 2. Create the service on Render
1. Sign in at https://render.com (free, GitHub login works).
2. **New +  →  Blueprint**.
3. Connect your repo. Render finds `render.yaml` and shows a service named
   **camview-compliance-portal** on the **free** plan.
4. Click **Apply**. First build takes ~3–6 min (it installs Chromium).

### 3. Open your link
When the build finishes, Render shows a URL like
`https://camview-compliance-portal.onrender.com`. That's your shareable link.

*(No `render.yaml`? You can instead do New + → Web Service → pick the repo →
Runtime: Docker → Plan: Free, and add the three env vars from `render.yaml`
by hand.)*

---

## How the "no stored data" part works
- `CAMVIEW_DATA_DIR=/tmp/camview_data` puts the SQLite DB, uploads and evidence
  under `/tmp`. Render wipes the filesystem on every restart/redeploy and when
  the free service wakes from sleep — so data doesn't persist.
- No external database, no S3, nothing to configure.

## Free-tier behaviour to expect
- **Cold start:** the free service sleeps after ~15 min idle. The first visit
  after that takes ~30–50s to wake, then it's fast. Subsequent visits are
  instant until it idles again.
- **Reports need internet for fonts:** the PDF pulls Google Fonts at print
  time. Render has internet, so this works — just adds a second or two.
- **One shared instance:** everyone hitting the link shares the same temporary
  workspace until it sleeps/restarts.

## Important — this is a demo link, not a data store
Because the instance is shared and the link is public, **anyone with the URL
can see and upload whatever is currently in that temporary instance.** Use only
sample/dummy exam data. For real candidate data you'd want auth + a private
host + persistent encrypted storage — a different setup than this free demo.

## Troubleshooting
- **Build fails on Chromium:** re-run the deploy; transient apt mirror hiccups
  happen. The Dockerfile only needs `chromium` + fonts, which are standard.
- **Report gives an error but dashboards work:** that means Chromium didn't
  launch. Confirm the three env vars are set (they are, via `render.yaml`):
  `CAMVIEW_CHROME_PATH=/usr/bin/chromium` and `CAMVIEW_CHROME_CONTAINER=1`.
- **App won't start:** check the Render logs tab — the health check hits
  `/healthz`; if that 404s, the service didn't boot (look for a Python
  traceback in the logs).
