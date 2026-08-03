#!/usr/bin/env python3
"""Where the four stages are, and how to spell a command that runs one.

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_config"))
    import paths

Every script in this project imports this. Nothing else in the codebase may
hold a stage-folder literal: five of them existed before the restructure, and
one — `develop.py`'s `INPUT_DIR = ROOT / "1 - input"` — was the dangerous kind,
because the restructure reuses the numbers 1 and 2. A stale constant pointing
at "1 - input" would have resolved to a folder that exists and is wrong, and
nothing would have raised.

`cmd()` exists for the same reason at a different layer. There were 34
hardcoded `./_config/.venv/bin/python "<stage>/<script>.py"` strings in printed
next-steps, argparse help and docstrings — including one baked inside the
generated review page's JavaScript, which is what the Approve button puts on
your clipboard. Derived from `__file__`, a printed command cannot outlive a
rename; typed out by hand, it fails silently and confusingly.
"""

from __future__ import annotations

import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "_config"

# The four stages, in the order a job passes through them. A job's folder
# location IS its status — nothing else records it — so these names are
# load-bearing and renaming one means renaming it here and nowhere else.
SELECTION_DIR = ROOT / "0 - selection"
EDIT_DIR = ROOT / "1 - edit"
MARCA_DIR = ROOT / "2 - marca dagua"
COMPLETED_DIR = ROOT / "3 - completed"

# The three that hold Job_NNNN folders. `0 - selection/` holds shoots, not
# jobs — it is the one stage that receives and keeps.
JOB_DIRS = (EDIT_DIR, MARCA_DIR, COMPLETED_DIR)
STAGE_DIRS = (SELECTION_DIR, *JOB_DIRS)

# The two phases inside `1 - edit/`. They hold the stage's *tooling*, never a
# job: a `Job_NNNN/` stays whole in `1 - edit/` with its photo, its `_edit` and
# its `_log` side by side, because stages 2 and 3 find files by name in the job
# folder and splitting it would hide them.
EDICAO_DIR = EDIT_DIR / "1 - edicao"        # phase 1 — one fixed prompt, every photo
RETOQUE_DIR = EDIT_DIR / "2 - retoque"      # phase 3 — one free instruction, one photo

DROP_DIR = SELECTION_DIR / "drop"
LOGOS_DIR = CONFIG_DIR / "logos"
SELETOR_DIR = CONFIG_DIR / "Seletor"

VENV_PY = "./_config/.venv/bin/python"

# The same interpreter, absolute. `VENV_PY` is a *printed* command and is
# relative on purpose — it is what you paste, and it reads as the project root.
# A `subprocess` spawn cannot use it: it would resolve against whatever cwd the
# parent happened to have. `serve.py` runs the stage scripts, so it needs this.
VENV_PY_ABS = CONFIG_DIR / ".venv" / "bin" / "python"


def rel(p: "Path | str") -> str:
    """A path as you would type it from the project root. Falls back to the
    absolute path for anything outside the project, rather than emitting the
    `../../..` chain that `Path.relative_to` would need."""
    p = Path(p)
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def cmd(script: "Path | str", *args: str) -> str:
    """The command that runs `script`, ready to paste.

    Pass `Path(__file__)` from the calling script — that is what makes the
    printed command track a folder rename for free. Arguments are quoted only
    when they need it, so the common case stays readable.
    """
    parts = [VENV_PY, f'"{rel(script)}"']
    parts += [a if a.startswith("-") and " " not in a else shlex.quote(a)
              for a in args]
    return " ".join(parts)


def notify(title: str, message: str, sound: bool = True) -> None:
    """Ring and post a macOS notification. Best-effort and always silent on
    failure — this is a courtesy at the end of a 27-minute batch, never
    something a run should die for.

    A batch of 60 photos is ~27 minutes and you will walk away from it. Without
    this the run finishes into an unwatched terminal.
    """
    import subprocess
    for argv in (["afplay", "/System/Library/Sounds/Glass.aiff"] if sound else None,
                 ["osascript", "-e",
                  f'display notification {json_str(message)} with title {json_str(title)}']):
        if not argv:
            continue
        try:
            subprocess.run(argv, check=False, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:                       # noqa: BLE001 — a courtesy, never a failure
            pass


def json_str(s: str) -> str:
    """AppleScript string literal. Double quotes and backslashes only."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
