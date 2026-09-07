# The report standard

Every PDF the portal prints — the secure-box compliance report, the single-modality
report, the combined report, the centre dossier and the district report — is
printed on the Innovatiview house paper in `backend/app/iv_paper.py`. Change that
module and every report changes at once; the report modules only build charts and
tables.

## The look

- **Three colours.** Navy `#3B5877` for structure and established evidence, the
  second tone `#7189A4` and greys `#8A97A6 / #B8C0CA / #D5DAE0` for context, oxide
  red `#B6403A` for the one thing that matters on a page — a critical tier, a late
  box, the primary action. The Innovatiview wordmark keeps its own colours.
- **Severity tiers** follow the same rule: critical is red, high is navy, elevated
  is the second tone, normal is grey. The map ramp runs pale grey to navy.
- **Fonts**, bundled under `assets/fonts` so the portal reads the same offline:
  Jost for the interface, titles, labels and chart text; Source Serif for reading
  text (cover subtitles, the wizard's questions); IBM Plex Mono for every number.
- **The sheet.** A4 landscape, a near-white textured stock with a torn left edge
  and a punch rail, the gear from the wordmark bled off the bottom-right corner,
  a red-then-navy band along the foot, the wordmark top-right.
- **Type scale and grid** are locked in `iv_paper.paper_css()`.

## The rhythm of a report

Cover → full-page photograph → analytical pages, with a photograph before each
section → back page.

- **Cover.** Wordmark, a red eyebrow naming the report, the examination as the
  title, a serif subtitle, the run's facts in mono, the client block, and the
  CamView photograph (a monitoring centre) as a navy duotone across the right.
- **Photographs.** Four generic images, printed as full-page navy duotones so
  they read as one family: the exam hall (`hall`), cameras on a ceiling
  (`cameras`), a CCTV monitoring room (`monitoring`), a review station showing
  camera feeds (`evidence`), plus `invigilation` and the cover. They live in
  `assets/photos/` with `credits.json`; the credits print on the back page, which
  the CC BY-SA licences require. To swap one, replace the JPEG and its credit.
- **One dominant object per analytical page.** The modality page is a scatter of
  every centre (alerts against the modality's own severity metric, tier
  thresholds drawn as reference lines, the outliers named) beside the heat map,
  with the time curve beneath. The secure-box page plots every centre's arrival
  deviation against its opening deviation. The time curves are the only line
  plots.

## The client mark

The client is the exam's conducting body, and it is never one fixed body: NTA one
week, UPESSC or RUHS the next. The portal keeps a **client library** and adapts to
whichever body an exam belongs to, in the reports and on the dashboard, with no
code change per client.

- **Choosing the body.** The New Examination wizard's *Conducting body* field is a
  dropdown of every known body (the library plus bodies already used in this
  deployment); a new body can simply be typed. As the operator types, the field
  shows the body's mark if one is on file, or offers *Add the body's mark (SVG or
  PNG)*. The same field and picker sit in the workspace's *Edit details*.
- **Where marks live.** `assets/clients/clients.json` ships about thirty Indian
  exam bodies (name, aliases, whether the Emblem of India belongs beside the mark,
  a "Government of …" line) with free marks from Wikimedia Commons where one exists
  (`nta.png`, `upsc.png`, `cbse.png`, `hssc.png`, `upmsp.png`). Marks added from
  the portal are saved under `<data_dir>/clients/` with their own `clients.json`,
  which overrides the shipped library entry by entry.
- **Matching.** `backend/app/clients.py` resolves a body to its entry by name,
  slug, alias or acronym, case-insensitively — "NTA", "National Testing Agency"
  and "nta neet 2026" all resolve to the same mark.
- **Where it shows.** The resolved mark goes on every report cover in the
  "Prepared for" block (with the Emblem of India for government bodies), in the
  workspace header beside the exam name, and on the library card under the body.
- **API.** `GET /api/clients` (add `?match=<body>` to resolve one), `GET
  /api/clients/{slug}/mark`, `POST /api/clients` (multipart `name`, `mark`,
  optional `emblem`, `line`), and `GET /api/bodies` for the dropdown.
