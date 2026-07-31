# WC-00660 - Casa MAD Alter — Fetch report

| | |
|---|---|
| Fetched | 2026-07-31T04:21:44+00:00 |
| Asked for | `None` |
| Arrived via | from `0 - selection/drop/`: `WC-00660 - Casa MAD Alter` |
| Photos | **48** (0 raw, 48 jpeg/tiff) |
| On disk | 146.5 MB |

## By extension

| Ext | Count | Size |
|---|---|---|
| `.heic` | 46 | 135.4 MB |
| `.jpg` | 2 | 11.0 MB |

## Did everything arrive?

**Unverified.** 48 photos arrived. Nothing here knows how many were sent, so that number is unconfirmed. Ask the photographer for the count and re-run with `--expect N` to turn this into a real check:

```bash
./_config/.venv/bin/python "0 - selection/fetch.py" \
    "None" --force --expect 450
```

### Frame numbering

- `IMG_` runs `0016`–`9737` · 38 present · 9684 hole(s) inside that range
  - **0017–0576** (560), **0578–0582** (5), **0584–2755** (2172), **2757–2907** (151), **2909–2917** (9), **2919–2940** (22), **2942–2945** (4), **2947–3152** (206), **3154–3193** (40), **3195–3887** (693), **3889–4077** (189), **4079–5850** (1772), … 23 more runs
  - ⚠️ A run of 2172 consecutive frames is gone. Could be a deleted bad bracket, could be a short zip. Worth asking.

> This only finds holes **between** the first and last frame. If the download stopped early, the frames past the cut are simply absent and the range ends there looking perfectly intact — so a clean result above is **not** evidence the tail arrived. Only `--expect` settles that.

### Housekeeping

- Duplicates removed: **1** — byte-identical under different names, which is what overlapping Drive partitions and browser re-downloads produce
  - `IMG_2918 (1).HEIC` = `IMG_2918.HEIC`
- OS/editor junk dropped: 1  — `.DS_Store`, AppleDouble `._` forks, Lightroom `.xmp` sidecars

---

Nothing here has been judged, renamed, or resized. Next:

```bash
./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/WC-00660 - Casa MAD Alter"
```
