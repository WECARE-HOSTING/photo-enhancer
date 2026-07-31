#!/usr/bin/env python3
"""One append-only `ledger.md` per numbered stage folder: what passed through
this phase, when, in what order.

    import ledger
    ledger.append(paths.EDIT_DIR, "Job_0023", "run 1", 52,
                  "50 ok · 2 falhas · 28m · PROMPT `#9803cabe`")

**Logs are write-only for the pipeline and read-only for humans.** Nothing in
this project reads a ledger to decide what to do next. The filesystem is still
the state — `is_done()` asks the disk whether a file exists. The moment a log
becomes an input it can disagree with the disk, and that is exactly the class of
bug that rework-by-deletion was built to eliminate.

Two record classes, and one test tells them apart:

    If I delete this job folder tomorrow, is this row still meaningful?
    Yes -> the stage ledger.  No -> inside the job (job.md, gate.md, *_log.md).

So a ledger row carries counts, a timestamp, a name and a pointer — never a fact
that exists nowhere else. Lose a job folder and you lose the detail but keep the
fact that it existed and where it went. The `left` row naming its destination is
what stops a stage log from being divorced from its subject:

    grep -n "Job_0023" */ledger.md
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

NAME = "ledger.md"

# A closed set, identical in all four stages. Closed because a free vocabulary
# drifts across four scripts, and because `grep '| gate |' */ledger.md` has to
# mean one thing. `run` carries a round number: "run 1", "run 2".
EVENTS = ("entered", "run", "gate", "left", "stopped")

HEADER = """# {stage} — ledger

_Append-only. One row per thing that happened in this folder, newest at the
bottom. Written by this stage's scripts; **nothing reads it back.** The detail
behind every row lives inside the job — `job.md`, `gate.md`, `<name>_log.md` —
and travels with it to `3 - completed/`._

_Evento is one of five words, the same in every stage: `entered` · `run` ·
`gate` · `left` · `stopped`. Fotos is how many photographs that event touched;
`gate` with 0 means a clean approval, and that row is the proof one happened._

_Paths in old rows are never corrected when a folder is renamed. A row records
what was true when it was written._

| Quando (UTC) | Job | Evento | Fotos | Detalhe |
|---|---|---|---|---|
"""


def cell(text: str) -> str:
    """Make free text safe for a markdown table cell.

    `|` becomes U+2223 DIVIDES rather than `\\|`. A backslash escape would need
    an unescape step on the way out, and nothing here ever reads a ledger back —
    so the escape would exist only to be forgotten. Substituting a lookalike
    keeps the file honest at a glance and costs one codepoint.
    """
    return " ".join(str(text).replace("|", "∣").split())


def append(stage_dir: "Path", job: str, event: str, photos: int,
           detail: str = "") -> Path:
    """Add one row. Creates the file with its header on first use."""
    verb = event.split()[0]
    if verb not in EVENTS:
        raise ValueError(f"ledger event {verb!r} is not one of {EVENTS}")

    path = Path(stage_dir) / NAME
    if not path.exists():
        path.write_text(HEADER.format(stage=Path(stage_dir).name),
                        encoding="utf-8")

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")[:19]
    row = (f"| {stamp} | {cell(job)} | {cell(event)} | {photos} "
           f"| {cell(detail)} |\n")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(row)
    return path
