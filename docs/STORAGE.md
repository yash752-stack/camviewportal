# Storage model — where the workbook, the images and the database live

Everything the portal writes lives under one directory, `CAMVIEW_DATA_DIR`.
Nothing is written anywhere else. That is the whole contract with the platform:
mount one volume there and the application is stateless around it.

---

## Block diagram

```
                 OPERATOR (browser)
                        │
        ┌───────────────┼────────────────┐
        │ alert export  │ evidence       │  or: a server-side folder path
        │  .xlsx        │  .zip / .jpg   │  (nothing is transferred)
        ▼               ▼                ▼
┌──────────────────────────────────────────────────────────────────┐
│                     PORTAL  (one container)                       │
│                                                                   │
│   ingest/excel.py          ingest/unpack.py                       │
│   parse rows, resolve      zip → verify → extract media           │
│   modality by channel      (zip-slip refused, size-capped)        │
│         │                          │                              │
│         │                          ▼                              │
│         │                  ingest/evidence.py                     │
│         │                  rglob the tree, key on filename:       │
│         │                  {AlarmID}_{dssId}.jpg → AlarmID        │
│         │                          │                              │
│         └──────────┬───────────────┘                              │
│                    ▼                                              │
│            one row per alert, carrying the                        │
│            ABSOLUTE PATH of its frame                             │
└────────────────────┬──────────────────────────┬──────────────────┘
                     │                          │
                     ▼                          ▼
        ┌────────────────────────┐   ┌──────────────────────────────┐
        │  DATABASE              │   │  FILESYSTEM                  │
        │  SQLite on the volume, │   │  $CAMVIEW_DATA_DIR/          │
        │  or RDS Postgres       │   │                              │
        │                        │   │  the .xlsx, verbatim         │
        │  alerts.evidence_image │──▶│  the .jpg frames             │
        │    = "/data/.../x.jpg" │   │  the PDF render workspace    │
        │  exams.evidence_root   │   │                              │
        │                        │   │  NO IMAGE BYTES IN THE DB    │
        └────────────────────────┘   └──────────────────────────────┘
                     │                          │
                     └────────────┬─────────────┘
                                  ▼
                      GET /api/evidence/{exam}/{alarmId}
                      realpath(image) must sit under
                      realpath(exam.evidence_root), else 404
```

**The one thing to take from this: images are files, the database holds paths.**
No BLOBs, no base64. A row is ~500 bytes; a frame is ~1 MB. That is why the
database stays small and the volume does not.

---

## On-disk layout

```
$CAMVIEW_DATA_DIR/
├── camview.db                  SQLite — only when CAMVIEW_DATABASE_URL is empty
├── uploads/
│   └── {EXAM_CODE}/            code sanitised: [^A-Za-z0-9_-] → _
│       ├── <original>.xlsx      the alert export, kept byte-for-byte
│       └── evidence/           written only when files were UPLOADED
│           ├── CD/  CHT/  CT/  … per-modality folders from the zip, preserved
│           └── *.jpg
├── evidence/
│   └── {EXAM_CODE}/            "bundled vault" — a folder dropped in beside the
│                               app. On boot the portal detects it and rebases
│                               evidence_root + every alert path onto it, so a
│                               vault moved between machines still resolves.
└── reportgen/
    └── {exam_id}_{modality}/   PDF render workspace
        └── thumbs/
```

### Three ways evidence arrives, one place it is read from

| Route | What happens | When to use it |
|---|---|---|
| **Loose files** | copied into `uploads/{CODE}/evidence/`, leaf filename only | a handful of frames |
| **`.zip`** | unpacked server-side into the same place, **inner folders preserved** | the normal case — this is how CamView exports |
| **Folder path** | used **in place**, nothing copied, nothing transferred | very large vaults already on the instance |

Whichever route, `exams.evidence_root` records the root and every
`alerts.evidence_image` is an absolute path beneath it. `EvidenceIndex` walks the
tree once with `rglob` and keys on the filename, so nesting is irrelevant to
lookup — `CD/C-354058-1-...jpg` and a flat `C-354058-1-...jpg` index identically.

---

## Sizing, and why it matters

| Artifact | Typical size | Grows with |
|---|---|---|
| Alert row | ~500 bytes | alerts |
| Alert workbook | ~16 KB per 100 alerts | exams |
| **Evidence frame** | **~1 MB** | **alerts — this dominates** |
| PDF workspace | tens of MB, transient | concurrent report generation |

A 100k-alert examination is roughly **100 GB of frames** and about **50 MB of
database**. Size the volume from the frames; the database is a rounding error.

> **There is no S3 offload.** `CAMVIEW_STORAGE_BACKEND=s3` is declared in
> `settings.py` and read by nothing — no boto3, no upload path. It fails
> silently: the app keeps writing to the volume. Size for the full vault.

---

## What this means for the platform

- **One volume at `CAMVIEW_DATA_DIR`** and the container is otherwise stateless.
- **Back up the volume and the database together.** They reference each other by
  absolute path; a database restored against a different vault has dangling
  paths, and the evidence route will 404 rather than serve the wrong frame.
- **Moving the vault is survivable.** Drop it at `evidence/{EXAM_CODE}` and the
  portal rebases every path on the next boot — idempotent, and cheap once healed.
- **The evidence route is path-traversal safe by construction**: it resolves the
  stored path and refuses anything that does not sit under the exam's recorded
  `evidence_root`.
