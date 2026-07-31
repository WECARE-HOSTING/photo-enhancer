# WC-00660 - Casa MAD Alter — delivery profile

_Written by `0 - selection/cull.py`. Override with `--type`._

## Type C — JPEG, camera filenames — the room has to be recognised

- 48 photos with no room names — small enough to be a finished selection, so it is treated as one

## Measured

| | |
|---|---|
| Photos | 48 |
| Raw | 0% |
| With a timestamp | 75% |
| Room named in the filename | 0% |
| Covered by a bracket | 0% |
| Rooms | 0 |
| Median photos per room | 0 |

## Worth knowing

- ⚠️ this could equally be a small raw dump; nothing in the filenames settles it. The near-duplicate count from the next pass will tell you — lots of near-duplicates means a dump. If it is one, re-run with `--type C`.
- ⚠️ profiled as A from the filenames, then contradicted once the rooms were named: 3.7 photos per room against the 3 a finished selection runs. Switched to C and curated. `--type A` forces the original guess back.
