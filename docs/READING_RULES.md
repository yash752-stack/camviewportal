# How the portal reads an exam

Operations review set out, in the Exam Monitoring Report, how an exam day should
be read: when the exam actually runs, which alerts belong to setup and which to
the exam, how persistent a camera is, what counts as an unusual centre. Those
rules now live in one module, `backend/app/exam_rules.py`, and drive the
**Shift insights** page, the **validation check**, the alert **priority** column
and the default **trunk windows**. Each rule is a named constant at the top of
that module; change it there and every view follows.

## The rules

| Rule | Setting | Where |
|---|---|---|
| Exam window | Opens with the first sustained Invigilator Not Moving cluster, closes with its last alert, rounded out to 30 min. INM more than 30 min from the rest is noise (a cluster under 2% of the day, min 3); clusters more than 90 min apart are separate shifts. No INM on a day: guessed from overall alert density and flagged. | `infer_windows` |
| Operator confirms | The New Examination wizard pre-fills each shift's exam window; the operator confirms or edits it. On the Insights page *Confirm exam windows* re-reads the whole exam. A confirmed window always wins over inference. | `exam_windows.json`, `POST /api/exams/{code}/windows` |
| Window cross-check | If 60% or more of a shift's boxes were opened before the earliest moment the opening window allows, INM probably lagged the real start. The page and the wizard say so and offer the start the openings imply (median opening rounded up to 30 min). | `window_checks` |
| Shifts and phases | Shift 1 runs from the day's first alert to the end of its exam window, Shift 2 from there to the end of its own. Before the window = pre-exam (setup); after the last window = post-exam. | `assign` |
| Stages | `pre`: Trunk Placed, Trunk Opened, Trunk Tampering, Furniture Out of Place — counted across the shift. `during`: Cheating, Multiple Persons Standing, Invigilator Not Moving — counted inside the exam window; outside it they are off-hours, shown separately, not dropped. `whole`: Crowd, Zone Intrusion, Camera Tampering, No Person, Mobile — counted across the shift. | `config/modalities.json` → `stage` |
| Shift comparisons | Swings, the exam clock and the heat map use exam-window alerts only. Swing = (S2 − S1) ÷ S1; "new" when S1 was zero. | `analyse`, `swing` |
| Severity | Unchanged: what kind of alert, fixed per model, raised by camera location where the model says so. | `config/modalities.json` |
| Priority | A second axis: how many times that camera raised that alert type in the shift. High ≥ 10, Medium 5–9, Low < 5. Stored on every alert (`alerts.priority`, `priority_count`, `shift_no`, `phase`). | `assign`, `refresh_exam` |
| Trunk windows | When the exam has no timetable: arrival 90 → 45 min before the exam starts, opening the last 15 min before. Configured timetables (and the shipped UPESSC / NEET ones) are untouched. | `trunk_windows`, `compliance._from_exam_windows` |
| Unusual centre | Outside mean ± 1 SD of per-centre counts for that alert type, every centre counted (zeros included). | `outliers` |
| Lists | Top 10 or top 5%, whichever is larger (pages list at most 100 rows of a list and say so). | `top_k` |
| Risk overlaps | Named pairs, e.g. Zone Intrusion with camera tampering at the same centre within 30 min; Cheating while that room's invigilator was stationary (15 min); empty control room within 1 h of a trunk being placed. Full list in `RISK_RULES`. | `risk_overlaps` |
| Warehouse | Procurement-centre cameras (a `WH …` sub-location or a `PC-xx` centre code) sit in the same charts as the exam. A warehouse has no exam window, so its alerts count for the **whole shift** in every comparison; they never set the exam window and stay out of the exam-only views (location scorecard, volume against variety, concentration). On a warehouse camera Zone Intrusion reads as **Perimeter Breach** and Crowd Detection as **Worker Crowding**, and a label naming a warehouse model wins over the channel. | `registry.resolve`, `Rec.counts`, `sector` / `variantOf` |
| Warehouse risk pairs | Same centre within 30 min: Stack Height with Sacks Outside ROI (both ways), Suspicious Activity Near Sacks with Perimeter Breach and with Worker Crowding (both ways), Worker Crowding with Fire and Smoke (both ways). | `RISK_RULES` |
| Exam details table | Per shift and both shifts: candidates, cameras scheduled, cameras alerting, alerts raised, tickets created, resolved and still open. Candidates, cameras scheduled and tickets resolved are entered on the Insights page (*Edit exam details*); tickets created are the distinct Ticket IDs in the export; still open = created − resolved. Both shifts: sums, except cameras scheduled (the larger shift) and cameras alerting (not added up). | `summary_table`, `exam_details.json`, `GET/POST /api/exams/{code}/details` |

## New catalogue entries

Cheating Detection (channel 17, Critical, during), Multiple Persons Standing
(channel 15, High, during), Trunk Tampering (channel 18, High, pre) and Furniture
Out of Place (no channel known yet, matched by label, Medium, pre). Exams loaded
before these existed carried them as generic `X15/X17/X18` at Medium; the portal
moves those rows onto the real models at start-up (`reconcile_codes`).

Warehouse models (sector `warehouse`, stage whole, matched by label until their
channels are known): Stack Height Exceeded (`SHE`, Medium), Sacks Outside ROI
(`SOR`, Medium), Suspicious Activity Near Sacks (`SAS`, High), Fire and Smoke
Detection (`FSD`, Critical), Vehicle Detection (`VD`, Low), Perimeter Breach
(`PB`, High, Zone Intrusion at a warehouse) and Worker Crowding (`WC`, Medium,
Crowd Detection at a warehouse). The severities are a first proposal for
operations review to confirm.

## Using it

- **Shift insights** — workspace → Examination tile → *Insights*, or
  `/exam/{code}/insights`. Alert Stats, Alert Analysis by stage, and a *How alerts
  are read* tab that prints the rules above from the live settings.
- **Validation check** — before loading an export:
  `python tools/validate_excel.py export.xlsx [--exam CODE] [--json out.json]`, or
  `POST /api/validate-excel`. Reports errors (unreadable columns, dropped rows,
  unreadable times), warnings (duplicate Alarm IDs, label contradicting channel,
  sheet time disagreeing with the time in the Alarm ID, a doubtful exam window,
  centre codes with two names or districts) and notes (new alarm types, unusual
  camera locations, off-hours alerts, boxes never seen on camera, warehouse
  alerts and how they were read), then the
  numbers the portal will report for the file.
- **Tests** — `pytest tests`.
