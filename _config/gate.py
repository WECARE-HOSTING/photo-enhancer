#!/usr/bin/env python3
"""What the three gate pages share, and the format they hand work back in.

    import gate
    page = TEMPLATE.format(css=gate.BASE_CSS + OWN_CSS,
                           js=gate.BASE_JS + OWN_JS, ...)

Three pages ask a human for a decision: `review-selection.html` (which photos),
`review-edit.html` (is the edit right), `review-marca.html` (is the logo right).
Their layouts genuinely differ — a 215px grid, a before/after pair, a 1:1 crop of
one corner — so this module deliberately does **not** own layout. It owns the
palette, the clipboard, the lightbox and the wire format: the four things that
had already drifted between the two pages that existed before.

One drift was a real bug. `review.py` handled a rejected clipboard write;
`cull.py` did not, so a blocked clipboard on the contact sheet did nothing at all
and said nothing. Sharing `copy()` fixes that everywhere at once.

CSS and JS are injected through `.format()` rather than living inside the
template, so they no longer need doubled braces. `review.py`'s stylesheet used to
be written `{{ ... }}` throughout for that reason alone.

## The wire format

Every decision comes back as one file beside the page: `gate.txt`. Stage 0 keeps
`picks.txt` — a positive list of 63 out of 307 is not the same statement as
"these 3 of 63 go back" — but both are read by `parse()`.

A page opened from the disk cannot write that file, so it puts the text on your
clipboard and you paste it. A page opened from `_config/serve.py` sends the same
text to the server, which writes it for you and can run the next command. Both
routes exist on every page and produce the same bytes: the producing function is
the same one either way, and `SERVE_JS` calls it rather than composing anything
of its own. See "the server, if any", below.

The one-click route exists only on the served page, so a page opened from the disk
now **says so** — a band at the top naming `Abrir.command`, the double-clickable
launcher this module writes beside every page, which reopens it served. The band
and the launcher are one pair on purpose: see `serve_note()`.

    SALA_01_0002        # sofá saiu com textura plástica, refazer
    +COZINHA_01_0001    # bancada clareou mais do que eu queria, mas passa

A bare name means *send it back*; `+` means *keep it, but record this*. That is
today's `rework.txt` grammar plus two characters, so muscle memory survives.

Four things make it survive contact with a real Mac:

1. **Every run pre-creates `gate.txt`** with its instructions inside. Telling
   someone to paste into a file that does not exist means TextEdit, and TextEdit
   defaults to RTF — you get `gate.txt.rtf` full of `{\\rtf1\\ansi` and an error
   saying "no gate.txt", which points at the wrong problem. Against a file that
   already exists, `open -e` gives plain text and the job is ⌘A ⌘V ⌘S.
2. **The button copies the whole file, not the changes.** Pasting twice is then
   harmless; a delta would silently double every record.
3. **RTF is rejected by name**, with the fix in the message.
4. **The page is pre-filled from `gate.txt`**, so notes survive closing the tab —
   no `localStorage`, which Safari refuses under `file://` anyway.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402  — the only speller of a stage command, for the launcher

NAME = "gate.txt"
RECORD = "gate.md"
PICKS = "picks.txt"
LAUNCHER = "Abrir.command"

# The three pages, named in one place. Each stage's own writer holds the layout;
# this is only so a script can name a sibling stage's page in a message without
# importing it — `develop.py` telling you where `picks.txt` comes from, for one.
PAGES = {
    "selection": "review-selection.html",
    "edit": "review-edit.html",
    "marca": "review-marca.html",
}

# Options a comment may carry, e.g. `# variant=claro`. Stripped out of the text
# the human sees again, and handed to the stage as instructions for the re-run.
# They apply to that run only — the resulting file on disk IS the persistence,
# so nothing has to read a log back to honour them.
OPT_RE = re.compile(r"\b(variant|glow)=([A-Za-z_-]+)", re.I)


@dataclass
class Mark:
    key: str                      # stem, or a source filename at stage 0
    back: bool                    # True = redo it; False = keep, comment only
    comment: str = ""
    opts: "dict[str, str]" = field(default_factory=dict)


# --------------------------------------------------------------- reading back

def parse(path: Path) -> "tuple[list[Mark], list[str]]":
    """Read a pasted `gate.txt` into (marks, lines that named nothing usable).

    Forgiving about what gets pasted — a bare stem, a whole filename, a
    `_edit.jpg`, or a path are all the same photo, and rejecting one on a
    formality helps nobody. The caller resolves keys against real files and is
    the one that decides an unknown line is an error.
    """
    if not path.exists():
        return [], []
    raw = path.read_text(encoding="utf-8", errors="replace")

    # The TextEdit trap. Say what happened, not "the file is missing".
    if raw.lstrip().startswith("{\\rtf"):
        raise ValueError(
            f"{path.name} was saved as Rich Text, not plain text.\n"
            "       In TextEdit: Formatar -> Converter para texto simples "
            "(⇧⌘T), save again,\n       and re-run. The file must be plain "
            "text or none of it can be read.")

    marks, unknown = [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body, _, note = line.partition("#")     # the live bug this fixes: without
        body, note = body.strip(), note.strip() # this, Path(...).stem kept the whole
        if not body:                            # line and the photo was silently
            unknown.append(line)                # never reworked
            continue
        back = not body.startswith("+")
        key = body.lstrip("+").strip()

        opts = {m.group(1).lower(): m.group(2).lower() for m in OPT_RE.finditer(note)}
        if opts:
            # Cutting the token out of the middle of a sentence leaves the
            # punctuation from both sides of it touching: "sumiu, variant=claro.
            # refazer" became "sumiu, . refazer". Collapse the pair to the first
            # mark, squeeze the whitespace, then tidy the ends.
            note = OPT_RE.sub("", note)
            note = re.sub(r"([,;.·])(?:\s*[,;.·])+", r"\1", note)
            note = re.sub(r"\s{2,}", " ", note).strip(" ·,;.")
        marks.append(Mark(key=key, back=back, comment=note, opts=opts))
    return marks, unknown


def picks(shoot: Path) -> "tuple[list[list[str]], dict[str, str]]":
    """Read stage 0's `picks.txt` into (scenes, note by first frame).

    The grammar `parse()` cannot serve: a scene is one or more source filenames
    joined by `+` (a bracket collapsing into one photograph), and the statement is
    positive — these 63 of 307 are in. A trailing `#` is a comment, not part of a
    filename; without that split, one sentence on the sheet used to make
    `develop.resolve()` fail to find the file and kill the whole hand-off.

    **Missing or empty is not an error here.** `develop.read_picks()` wraps this
    with the `sys.exit` it needs, because a hand-off with no picks has nothing to
    do; `cull.py` calls it to pre-tick the sheet and a shoot nobody has ticked yet
    is the normal case.
    """
    path = Path(shoot) / PICKS
    if not path.exists():
        return [], {}
    scenes: "list[list[str]]" = []
    notes: "dict[str, str]" = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body, _, note = line.partition("#")
        frames = [f.strip() for f in body.split("+") if f.strip()]
        if frames:
            scenes.append(frames)
            if note.strip():
                notes[frames[0]] = note.strip()
    return scenes, notes


def stub(page: str, job: str) -> str:
    """The empty `gate.txt` a run leaves ready to be pasted over."""
    return f"""# {NAME} — {job}
#
# Cole aqui o que a página {page} copiou (⌘A ⌘V ⌘S — substitua tudo).
# Uma linha por foto sobre a qual você tem algo a dizer:
#
#    NOME            # por que está voltando
#    +NOME           # fica, mas anote isto
#
# Linhas em branco e linhas começando com # são ignoradas. O script dobra este
# arquivo em {RECORD} e o apaga — o registro fica lá, não aqui.
"""


def ensure_stub(job_dir: Path, page: str, job: str) -> Path:
    """Create `gate.txt` if it is not there. Never overwrites a pasted one."""
    path = Path(job_dir) / NAME
    if not path.exists():
        path.write_text(stub(page, job), encoding="utf-8")
    return path


# ------------------------------------------------------------ the audit trail

def fold(job_dir: Path, stage: str, round_n: int, marks: "list[Mark]",
         approved: int, by: str = "") -> Path:
    """Append one gate pass to `gate.md`, the job's permanent record.

    Called **before** the scratch files are deleted and before the job moves.
    Until this existed, `approve()` unlinked `review.html` and `rework.txt` and
    then archived — destroying the rejection history at the exact moment it
    became permanent.
    """
    import ledger                                   # for cell(): `|` -> U+2223

    path = Path(job_dir) / RECORD
    if not path.exists():
        path.write_text(
            f"# {Path(job_dir).name} — registro dos portões\n\n"
            "_Cada decisão humana por que este trabalho passou, da mais antiga "
            "para a mais nova.\nEscrito pelo script do estágio quando ele dobra "
            f"o `{NAME}`; o pipeline nunca lê este\narquivo de volta. "
            "Edite à vontade — é um registro, não uma trava._\n",
            encoding="utf-8")

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    back = [m for m in marks if m.back]
    who = f"{by} · " if by else ""
    out = [f"\n## {stage} · rodada {round_n} · {stamp}", "",
           f"{who}{len(back)} de volta · {approved} "
           f"aprovada{'' if approved == 1 else 's'}"]

    if marks:
        out += ["", "| Foto | Decisão | Comentário |", "|---|---|---|"]
        for m in marks:
            note = ledger.cell(m.comment) or "—"
            if m.opts:
                note += " · " + " ".join(f"`{k}={v}`" for k, v in m.opts.items())
            out.append(f"| `{ledger.cell(m.key)}` | "
                       f"{'volta' if m.back else 'ok'} | {note} |")
    else:
        out.append("\n_Aprovado sem comentários._")

    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return path


@dataclass
class Pass:
    """One round already recorded in `gate.md`, read back out of it."""
    stage: str
    round_n: int
    when: str
    rows: "dict[str, tuple[bool, str]]"       # key -> (back, comment)


ROUND_HEAD_RE = re.compile(r"^## (.+?) · rodada (\d+) · (\S+)\s*$", re.M)
DECISION_RE = re.compile(r"^\| `([^`]+)` \| (volta|ok) \| (.*?) \|\s*$", re.M)


def passes(job_dir: Path, stage: str = "") -> "list[Pass]":
    """Every gate round this job has been through, oldest first.

    The complement to `<name>_log.md` on `review-edit.html`: a photograph that
    was kept with a note, or one whose retouch *failed*, has a row here and no
    retouch block there. "This is what you asked, and nothing came back" is
    exactly what the page has to be able to say.

    Forgiving by design — `fold()` writes this file telling you to edit it freely
    ("é um registro, não uma trava"), so a hand-edited round costs its own rows
    and nothing else. Never raises.
    """
    path = Path(job_dir) / RECORD
    try:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    heads = list(ROUND_HEAD_RE.finditer(raw))
    out: "list[Pass]" = []
    for i, head in enumerate(heads):
        if stage and head.group(1).strip() != stage:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw)
        rows = {}
        for row in DECISION_RE.finditer(raw[head.start():end]):
            note = row.group(3).strip()
            rows.setdefault(row.group(1), (row.group(2) == "volta",
                                           "" if note == "—" else note))
        out.append(Pass(stage=head.group(1).strip(), round_n=int(head.group(2)),
                        when=head.group(3), rows=rows))
    out.sort(key=lambda p: p.round_n)
    return out


def rounds_so_far(job_dir: Path, stage: str) -> int:
    """How many gate passes this stage has already recorded for this job."""
    path = Path(job_dir) / RECORD
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8").count(f"\n## {stage} · rodada ")


def repeats(job_dir: Path, stage: str, marks: "list[Mark]") -> "list[str]":
    """Photos going back that have already gone back at this stage before.

    A photo failing the same way twice is not a re-run problem — it is a
    `PROMPT.md` problem, and the fix applies to every future photo rather than
    to this one. Cheap to detect inside a job; deliberately not tallied across
    jobs, which would be a taxonomy invented before the first real comment.
    """
    path = Path(job_dir) / RECORD
    if not path.exists():
        return []
    seen = path.read_text(encoding="utf-8")
    return [m.key for m in marks
            if m.back and f"| `{m.key}` | volta |" in seen]


# ------------------------------------------------------------------- page bits

def esc(s: "str | Path") -> str:
    return html.escape(str(s), quote=True)


def js(value) -> str:
    """A Python value as a JS literal, safe to sit inside a <script> tag."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


PALETTE_CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#111; --dim:#666; --line:#e2e2e2;
        --ok:#0a7d3c; --rej:#b3261e; --warnbg:#fff4e5; --warnfg:#8a4b00;
        --note:#f6f6f4; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141414; --fg:#ececec; --dim:#9a9a9a; --line:#2e2e2e;
          --ok:#4ec97f; --rej:#ff6b5e; --warnbg:#3a2c14; --warnfg:#ffd28a;
          --note:#1c1c1c; } }
"""

BASE_CSS = PALETTE_CSS + """
* { box-sizing:border-box }
body { margin:0; padding:1.4rem 1.4rem 6rem; background:var(--bg); color:var(--fg);
  font:14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif }
h1 { font-size:1.35rem; margin:0 0 .3rem }
.sub { color:var(--dim); font-size:12.5px; margin:0 0 1rem }
.sub a { color:inherit }
.warn { margin:0 0 1.2rem; padding:.6rem .8rem; border-radius:7px;
  background:var(--warnbg); color:var(--warnfg); font-size:12.5px }
h2 { font-size:.95rem; margin:2.2rem 0 .7rem; padding-bottom:.3rem;
  border-bottom:1px solid var(--line); display:flex; justify-content:space-between;
  align-items:baseline; position:sticky; top:0; background:var(--bg); z-index:2 }
h2 small { color:var(--dim); font-weight:400 }
code { font-family:ui-monospace, SFMono-Regular, Menlo, monospace }
.tick { display:inline-flex; gap:.35rem; align-items:center; cursor:pointer;
  font-size:11.5px; color:var(--dim); user-select:none }
.tick input { width:17px; height:17px; accent-color:var(--rej); cursor:pointer; margin:0 }
/* The comment box is a SIBLING of the label, never a child of it: a form control
   inside a <label> toggles that label's checkbox when you click it. */
.note { display:block; width:100%; margin-top:.45rem; padding:.4rem .55rem;
  font:inherit; font-size:12.5px; color:var(--fg); background:var(--note);
  border:1px solid var(--line); border-radius:6px; resize:vertical }
.note::placeholder { color:var(--dim) }
.note:focus { outline:2px solid var(--dim); outline-offset:-1px }
/* Click any image to fill the window with it. The one comparison a side-by-side
   layout cannot make is "is this detail right", and that needs the pixels. */
body.zoom { overflow:hidden }
#zoom { display:none; position:fixed; inset:0; z-index:20; background:#000d;
  backdrop-filter:blur(4px); cursor:zoom-out; padding:1rem }
#zoom.on { display:flex; align-items:center; justify-content:center }
#zoom img { max-width:100%; max-height:100%; object-fit:contain; border-radius:6px }
#bar { position:fixed; left:0; right:0; bottom:0; padding:.7rem 1.4rem;
  background:color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter:blur(12px); border-top:1px solid var(--line);
  display:flex; gap:.8rem; align-items:center; z-index:9; flex-wrap:wrap }
button { font:inherit; padding:.42rem .85rem; border-radius:7px; cursor:pointer;
  border:1px solid var(--line); background:var(--bg); color:var(--fg) }
button.go { background:var(--ok); border-color:var(--ok); color:#fff; font-weight:600 }
button.bad { background:var(--rej); border-color:var(--rej); color:#fff; font-weight:600 }
button:disabled { opacity:.4; cursor:not-allowed }
#n { font-variant-numeric:tabular-nums; font-weight:600 }
#hint { color:var(--dim); margin-left:auto; font-size:12px; text-align:right }
"""

# Shared behaviour. A page supplies GATE_HEADER, GATE_FILE and PREFILL, and may
# define paintExtra() to update its own counters.
BASE_JS = """
// Checkboxes ONLY. The stage-2 page also gives its override radios a data-key,
// and a bare input[data-key] picked those up too: the "auto" radio ships
// checked, so paint() counted every photo as marked, the counter read N with
// nothing ticked, and the Approve button could never enable.
const boxes = () => [...document.querySelectorAll('input[type="checkbox"][data-key]')];
const noteOf = k => document.querySelector('textarea[data-key="' + CSS.escape(k) + '"]');
const optOf  = k => {
  const el = document.querySelector('[data-opt][data-key="' + CSS.escape(k) + '"]:checked');
  return el ? el.value : '';
};
let dirty = false;

function markLines() {
  const out = [];
  boxes().forEach(b => {
    const k = b.dataset.key;
    const t = noteOf(k), o = optOf(k);
    let note = (t ? t.value : '').replace(/\\s+/g, ' ').trim();
    if (o) note = (note ? note + ' ' : '') + o;
    if (!b.checked && !note) return;
    const name = (b.checked ? '' : '+') + k;
    out.push(note ? name.padEnd(28) + '# ' + note : name);
  });
  return out;
}

function payload() {
  return GATE_HEADER + '\\n' + markLines().join('\\n') + '\\n';
}

function copy(text, msg) {
  navigator.clipboard.writeText(text).then(
    () => { dirty = false; document.getElementById('hint').textContent = msg; },
    () => { document.getElementById('hint').textContent =
             'Clipboard bloqueado — abra este arquivo do disco, não por http.'; });
}

function copyMarks() {
  const n = markLines().length;
  copy(payload(), n
    ? 'Copiado (' + n + ') — cole em ' + GATE_FILE + ' substituindo tudo (⌘A ⌘V ⌘S)'
    : 'Nada marcado — copiado assim mesmo, o arquivo fica vazio.');
}

function setAll(v) { boxes().forEach(b => b.checked = v); dirty = true; paint(); }

function paint() {
  const on = boxes().filter(b => b.checked);
  const el = document.getElementById('n');
  if (el) el.textContent = on.length;
  boxes().forEach(b => {
    const item = b.closest('[data-item]');
    if (item) item.classList.toggle('out', b.checked);
  });
  const per = {};
  on.forEach(b => per[b.dataset.group] = (per[b.dataset.group] || 0) + 1);
  document.querySelectorAll('.rej').forEach(x => {
    x.textContent = per[x.dataset.for] || 0;
  });
  const ok = document.getElementById('ok');
  if (ok) {
    // Approving a job you have just ticked photographs in is always a mistake:
    // the rework would be thrown away by the step that archives it.
    ok.disabled = on.length > 0 || !APPROVABLE;
    ok.title = on.length ? 'Limpe as marcações ou copie-as primeiro'
             : (APPROVABLE ? '' : 'Alguma foto ainda não tem resultado');
  }
  if (typeof paintExtra === 'function') paintExtra(on);
}

document.addEventListener('change', e => {
  if (e.target.matches('input[data-key], [data-opt]')) { dirty = true; paint(); }
});
document.addEventListener('input', e => {
  if (e.target.matches('textarea[data-key]')) dirty = true;
});
function closeZoom() {
  document.getElementById('zoom').classList.remove('on');
  document.body.classList.remove('zoom');
}

// The lightbox used to carry an inline onclick that closed on any click inside
// it. That fired while the event was still bubbling, so a page handler further
// out never got to act — the edit page's A/B flip was reachable only by keyboard.
// Now the backdrop closes, and a click on the image asks the page first.
document.addEventListener('click', e => {
  if (e.target.matches('img.zoomable')) {
    const z = document.getElementById('zoom');
    z.querySelector('img').src = e.target.dataset.full || e.target.src;
    z.classList.add('on');
    document.body.classList.add('zoom');
  } else if (e.target.matches('#zoom img')) {
    if (typeof zoomFlip === 'function') zoomFlip(); else closeZoom();
  } else if (e.target.id === 'zoom') {
    closeZoom();
  }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeZoom();
});

// Prevents the loss instead of recovering from it, which is why there is no
// localStorage layer here: Safari refuses it under file:// anyway, and the
// durable draft is the pasted file, which this page is pre-filled from.
window.addEventListener('beforeunload', e => {
  if (!dirty || !markLines().length) return;
  e.preventDefault();
  e.returnValue = '';
});

// Pre-fill from whatever is already in gate.txt.
PREFILL.forEach(m => {
  const b = document.querySelector('input[data-key="' + CSS.escape(m.key) + '"]');
  if (b) b.checked = m.back;
  const t = noteOf(m.key);
  if (t && m.comment) t.value = m.comment;
  // The radios carry the whole token ("variant=claro"), which is what optOf()
  // reads back and what markLines() writes. Restoring from the bare value
  // ("claro") matched nothing, so a forced ink silently reverted to auto on the
  // next copy — the opposite of what pre-filling is for.
  const tok = m.opts && (m.opts.variant ? 'variant=' + m.opts.variant
                       : m.opts.glow ? 'glow=' + m.opts.glow : '');
  if (tok) {
    const r = document.querySelector('[data-opt][data-key="' + CSS.escape(m.key)
                                     + '"][value="' + tok + '"]');
    if (r) r.checked = true;
  }
});
paint();
"""


# --------------------------------------------------------- the server, if any
#
# `_config/serve.py` is the other half of this. When the page is opened from it
# rather than from the disk, these buttons appear beside the clipboard ones and
# do the pasting and the typing for you. Under `file://` they never appear, and
# nothing on this page changes at all — the first line of `srvProbe()` is the
# entire fallback, and the clipboard route stays exactly as it was.

SERVE_BAR = '<span id="srvbar"></span>'     # where the buttons get built

# Every colour here has a fallback, because `cull.py`'s page does not use
# BASE_CSS — it has a palette of its own, older and named differently. Rather
# than fold the two (a refactor with its own blast radius, for no gain here),
# each `var()` names both spellings and this stylesheet drops into either page.
SERVE_CSS = """
#srvbar { display:inline-flex; gap:.5rem; flex-wrap:wrap }
#srvbar:not(:empty)::before { content:''; width:1px; align-self:stretch;
  background:var(--line); margin-right:.1rem }
dialog#srvask { border:1px solid var(--line); border-radius:11px; padding:0;
  max-width:min(46rem, 92vw); background:var(--bg); color:var(--fg) }
dialog#srvask::backdrop { background:#0009; backdrop-filter:blur(3px) }
#srvask .in { padding:1.1rem 1.2rem }
#srvask h3 { margin:0 0 .5rem; font-size:1.05rem }
#srvask p { margin:.4rem 0; font-size:13px }
#srvask .cmd { display:block; margin:.7rem 0; padding:.5rem .6rem; font-size:12px;
  background:var(--note, #8881); border:1px solid var(--line); border-radius:6px;
  overflow-x:auto; white-space:pre }
#srvask .danger { color:var(--warnfg); background:var(--warnbg); padding:.5rem .6rem;
  border-radius:6px }
#srvbar button.go, #srvask button.go { color:#fff; font-weight:600;
  background:var(--ok, var(--pick)); border-color:var(--ok, var(--pick)) }
#srvbar button.bad, #srvask button.bad { color:#fff; font-weight:600;
  background:var(--rej, var(--flag)); border-color:var(--rej, var(--flag)) }
#srvbar button:disabled, #srvask button:disabled { opacity:.4; cursor:not-allowed }
#srvask ol { margin:.5rem 0; padding-left:1.3rem; font-size:12.5px; max-height:32vh;
  overflow-y:auto }
#srvask li { margin:.2rem 0 }
#srvask li q { color:var(--dim) }
#srvask .row { display:flex; gap:.6rem; justify-content:flex-end;
  padding:.8rem 1.2rem; border-top:1px solid var(--line) }
#srvout { position:fixed; right:1rem; bottom:4.6rem; z-index:12; width:min(46rem, 92vw);
  max-height:52vh; display:flex; flex-direction:column; border-radius:10px;
  border:1px solid var(--line); background:var(--bg); overflow:hidden;
  box-shadow:0 10px 40px #0004 }
#srvout header { display:flex; gap:.6rem; align-items:center; padding:.5rem .7rem;
  border-bottom:1px solid var(--line); font-size:12.5px }
#srvout header b { font-weight:600 }
#srvout header .sp { margin-left:auto }
#srvout pre { margin:0; padding:.6rem .7rem; overflow:auto; font-size:11.5px;
  line-height:1.45; white-space:pre-wrap; word-break:break-word;
  font-family:ui-monospace, SFMono-Regular, Menlo, monospace }
#srvout.bad { border-color:var(--rej, var(--flag)) }
/* The band a page opened from the disk shows instead of an empty #srvbar. It
   ships hidden, and `#srvoff[hidden]` has to be spelled out: a `display:flex`
   rule outranks the hidden attribute's UA stylesheet, and the band would then be
   on in every served page, permanently. */
#srvoff { margin:0 0 1.2rem; padding:.7rem .85rem; border-radius:8px;
  background:var(--warnbg); color:var(--warnfg); font-size:12.5px;
  display:flex; flex-wrap:wrap; gap:.45rem .7rem; align-items:center }
#srvoff[hidden] { display:none }
#srvoff .how { flex:1 1 100% }
#srvoff code { font-family:ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size:11.5px; padding:.3rem .5rem; border-radius:6px; max-width:100%;
  background:color-mix(in srgb, var(--warnfg) 13%, transparent);
  overflow-x:auto; white-space:pre }
#srvoff button { font:inherit; font-size:12px; padding:.28rem .7rem;
  border-radius:6px; cursor:pointer; border:1px solid var(--warnfg);
  background:transparent; color:var(--warnfg) }
#srvcmdhint { font-size:11.5px }
"""


# ------------------------------------------------- when there is no server
#
# The first line of `srvProbe()` is still the entire `file://` fallback — no
# fetch, no console error, no buttons — but it used to return in *silence*,
# leaving `#srvbar` empty with nothing to say why, and the barra showing only
# 'Copiar marcações' in a flow that no longer needs copying at all.
#
# These two are deliberately one pair: `serve_note()` is the band that names
# `LAUNCHER`, `write_launcher()` is what puts that file there. Both are handed the
# same command string by the caller, so the band cannot name a file nobody wrote,
# nor print a command that file does not run.

def serve_note(command: str) -> str:
    """The band a page shows when it was opened from the disk.

    Ships hidden and is revealed by `srvOffline()`, never the other way round: a
    served page must not flash a warning it is about to take away. The command is
    baked into the HTML at write time because under `file://` there is nothing to
    ask — the `actions` registry only exists on the other route.
    """
    return (
        '<div id="srvoff" hidden>'
        '<b>Esta página foi aberta do disco.</b> Por isso os botões de um clique '
        '(«Refazer as marcadas», «Aprovar…») não estão aqui: eles falam com o '
        'servidor que o comando abaixo levanta. Os botões de copiar continuam '
        'funcionando como sempre — copie, cole no arquivo ao lado, rode o comando.'
        f'<span class="how">De um clique: <b>{esc(LAUNCHER)}</b>, nesta mesma '
        'pasta — duplo clique no Finder e esta página reabre servida, com os '
        'botões.</span>'
        f'<code id="srvcmd">{esc(command)}</code>'
        '<button type="button" onclick="srvCopyCmd()">Copiar o comando</button>'
        '<span id="srvcmdhint"></span></div>')

# The page supplies GATE_TEXT: {filename it writes -> function returning its
# bytes}. Those functions are the ones the clipboard buttons already call, so
# what gets written is what would have been pasted, to the byte.
SERVE_JS = """
const SRV = { on:false, gen:0, tok:'', acts:{}, run:null, busy:false };

// BASE_JS's unsaved-work guard. The selection page does not use BASE_JS and has
// no such variable, so this is a check and not an assignment to a global that
// would only exist on one of the two pages.
function srvUndirty() { if (typeof dirty !== 'undefined') dirty = false; }

// Under file:// there is no bar to build and no state to fetch, so the page
// explains itself instead of looking broken. It only unhides text that is already
// in the HTML, so a page with no JS at all is no worse off than before.
function srvOffline() {
  const el = document.getElementById('srvoff');
  if (el) el.hidden = false;
}

function srvCopyCmd() {
  const code = document.getElementById('srvcmd');
  const hint = document.getElementById('srvcmdhint');
  if (!code) return;
  // With a trailing newline, like copyApprove()'s: pasted into Terminal it runs,
  // instead of sitting there waiting for a return nobody realises is missing.
  navigator.clipboard.writeText(code.textContent + '\\n').then(
    () => { hint.textContent = 'Comando copiado — cole no terminal ✓'; },
    () => {
      // The same rejection copy() has always handled, with the fallback that
      // needs no permission at all: select it, and ⌘C works.
      const r = document.createRange();
      r.selectNodeContents(code);
      const s = getSelection();
      s.removeAllRanges();
      s.addRange(r);
      hint.textContent = 'Clipboard bloqueado — o comando está selecionado, ⌘C';
    });
}

function srvHead(extra) {
  const h = { 'Content-Type':'application/json', 'X-Gate-Token':SRV.tok };
  if (extra !== false) h['X-Gate-Gen'] = String(SRV.gen);
  return h;
}

async function srvProbe() {
  // Still the whole file:// fallback. No fetch, no console error, no buttons —
  // the one thing it does now is say so, which is what stops an empty barra from
  // reading as a broken page.
  if (!location.protocol.startsWith('http')) return srvOffline();
  SRV.tok = new URLSearchParams(location.search).get('t') || '';
  let s;
  try {
    // These two stay silent on purpose. They mean "served over http, but not by
    // *this* server" — a plain python -m http.server, or a tab left open on a
    // dead session — and the band's "aberta do disco" would be a lie there.
    const r = await fetch('/_gate/state');
    if (!r.ok) return;
    s = await r.json();
  } catch (e) { return; }
  SRV.on = true;
  SRV.gen = s.gen;
  s.actions.forEach(a => SRV.acts[a.name] = a);
  srvBuild(s.actions);
  if (s.running) srvOpen(s.running.action, s.running.id, 0);
}

function srvBuild(actions) {
  const bar = document.getElementById('srvbar');
  if (!bar) return;
  actions.forEach(a => {
    const b = document.createElement('button');
    b.textContent = a.label;
    if (a.tone) b.className = a.tone;
    b.dataset.act = a.name;
    if (a.needsClean) b.dataset.clean = '1';
    b.title = a.note || a.cmd || '';
    b.onclick = () => srvAsk(a.name);
    bar.appendChild(b);
  });
  srvPaint();
}

// The same rule the clipboard Aprovar button has always had, applied to the
// server's copy of it: a job you have just ticked photographs in cannot be
// approved, because the archive step would throw that rework away.
function srvPaint() {
  const bar = document.getElementById('srvbar');
  if (!bar) return;
  const ticked = (typeof boxes === 'function')
    ? boxes().filter(b => b.checked).length : 0;
  bar.querySelectorAll('button[data-clean]').forEach(b => {
    b.disabled = ticked > 0 || SRV.busy;
    b.title = ticked ? 'Limpe as marcações ou mande-as primeiro'
                     : ((SRV.acts[b.dataset.act] || {}).note || '');
  });
}
document.addEventListener('change', e => {
  if (e.target.matches && e.target.matches('input[data-key]')) srvPaint();
});

function textFor(name) {
  const a = SRV.acts[name];
  if (!a || !a.writes) return null;
  const make = (typeof GATE_TEXT === 'object') && GATE_TEXT[a.writes];
  return make ? make() : null;
}

// A page may define srvSummary(name) to show exactly what it is about to send.
// On the edit page that is every photograph going back with its sentence — the
// last moment before a paid run to notice you wrote it about the wrong photo.
function srvDetail(name) {
  return (typeof srvSummary === 'function') ? (srvSummary(name) || '') : '';
}

function srvAsk(name) {
  const a = SRV.acts[name];
  if (!a) return;
  let dlg = document.getElementById('srvask');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'srvask';
    document.body.appendChild(dlg);
  }
  const text = textFor(name);
  const lines = text === null ? 0 : text.split('\\n').filter(l =>
    l.trim() && !l.trim().startsWith('#')).length;
  const esc = s => String(s).replace(/[&<>]/g,
    c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;' }[c]));

  const bits = [];
  if (a.writes) bits.push('<p>Grava <code>' + esc(a.writes) + '</code> — ' +
    lines + ' linha(s), o mesmo texto do botão de copiar.</p>');
  if (a.cmd) bits.push('<p>E roda:</p><code class="cmd">' + esc(a.cmd) + '</code>');
  else bits.push('<p>Não roda nada — só grava o arquivo.</p>');
  const detail = srvDetail(name);
  if (detail) bits.push(detail);
  if (a.danger) bits.push('<p class="danger">' + esc(a.danger) + '</p>');
  if (a.outcome === 'ends_session')
    bits.push('<p class="danger">Isto encerra a revisão: o trabalho sai desta ' +
      'pasta e esta página para de responder.</p>');

  dlg.innerHTML = '<form method="dialog"><div class="in"><h3>' + esc(a.label) +
    '</h3>' + bits.join('') + '</div><div class="row">' +
    '<button value="no">Cancelar</button>' +
    '<button value="yes" class="' + (a.tone || 'go') + '">Confirmar</button>' +
    '</div></form>';
  dlg.onclose = () => { if (dlg.returnValue === 'yes') srvGo(name); };
  dlg.showModal();
}

async function srvGo(name) {
  const a = SRV.acts[name];
  if (SRV.busy) return;
  SRV.busy = true;
  const text = textFor(name);
  const body = { action: name };
  if (text !== null) body.text = text;
  const where = a.cmd ? '/_gate/run' : '/_gate/save';
  let out;
  try {
    const r = await fetch(where, { method:'POST', headers:srvHead(),
                                   body:JSON.stringify(body) });
    out = await r.json();
    if (!r.ok) {
      SRV.busy = false;
      return srvOpen(name, null, null, out.error || ('erro ' + r.status));
    }
  } catch (e) {
    SRV.busy = false;
    return srvOpen(name, null, null, 'o servidor não respondeu — ele ainda ' +
      'está rodando no terminal?');
  }
  srvUndirty();
  if (!a.cmd) {
    SRV.busy = false;
    document.getElementById('hint').textContent =
      'Gravado em ' + a.writes + ' ✓';
    return;
  }
  srvOpen(name, out.run, 0);
}

function srvPanel() {
  let el = document.getElementById('srvout');
  if (el) return el;
  el = document.createElement('section');
  el.id = 'srvout';
  el.innerHTML = '<header><b class="what"></b><span class="st"></span>' +
    '<span class="sp"></span><button class="kill">Cancelar a rodada</button>' +
    '<button class="hide">Fechar</button></header><pre></pre>';
  document.body.appendChild(el);
  el.querySelector('.hide').onclick = () => el.remove();
  el.querySelector('.kill').onclick = () => srvCancel();
  return el;
}

function srvOpen(name, runId, from, error) {
  const el = srvPanel();
  el.classList.toggle('bad', !!error);
  el.querySelector('.what').textContent = (SRV.acts[name] || {}).label || name;
  el.querySelector('.kill').hidden = !runId;
  const pre = el.querySelector('pre');
  if (error) {
    el.querySelector('.st').textContent = '— não rodou';
    pre.textContent = error;
    return;
  }
  SRV.run = runId;
  pre.textContent = '';
  el.querySelector('.st').textContent = '— rodando';
  const es = new EventSource('/_gate/stream?run=' + runId + '&from=' + (from || 0));
  es.addEventListener('line', e => {
    pre.textContent += e.data + '\\n';
    pre.scrollTop = pre.scrollHeight;
  });
  es.addEventListener('end', e => {
    es.close();
    SRV.busy = false;
    SRV.run = null;
    el.querySelector('.kill').hidden = true;
    let d = {};
    try { d = JSON.parse(e.data); } catch (x) {}
    SRV.gen = d.gen || SRV.gen;
    el.classList.toggle('bad', d.code !== 0);
    el.querySelector('.st').textContent = d.code === 0 ? '— pronto' :
      '— parou com erro ' + d.code + ', nada mudou de página';
    if (d.outcome === 'reload') { srvUndirty(); setTimeout(() => location.reload(), 700); }
    if (d.outcome === 'ends_session') {
      document.querySelectorAll('#srvbar button').forEach(b => b.disabled = true);
      el.querySelector('.st').textContent =
        '— pronto. O trabalho saiu desta pasta; esta página é só leitura agora.';
    }
  });
  es.onerror = () => {
    // The stream drops when the server stops answering, which after an
    // ends_session run is the expected ending, not a failure.
    es.close();
    SRV.busy = false;
  };
}

async function srvCancel() {
  if (!SRV.run) return;
  if (!confirm('Interromper a rodada?\\n\\nO que já foi enviado à fal.ai já foi ' +
      'cobrado. Uma foto no meio do caminho pode ficar sem o _edit.jpg — nesse ' +
      'caso ela volta a rodar na próxima vez.')) return;
  try {
    await fetch('/_gate/cancel', { method:'POST', headers:srvHead(false),
                                   body:JSON.stringify({ run:SRV.run }) });
  } catch (e) {}
}

srvProbe();
"""


def zoom_div() -> str:
    """The lightbox, deliberately without an inline onclick — see `closeZoom` in
    BASE_JS for why that inline handler broke the A/B flip."""
    return '<div id="zoom"><img alt=""></div>'


def header_line(page: str, job: str) -> str:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"# {NAME} — {job} · copiado de {page} em {stamp}"


# ---------------------------------------------------------------- the launcher

def launcher_body(command: str) -> str:
    """The `Abrir.command` script, verbatim.

    `${0:A:h:h:h}` is zsh for "this file's absolute path, up three": the job or
    shoot folder, its stage folder, the project root. Deriving the root instead of
    baking it means the file survives the whole project being moved or renamed,
    and keeps the command inside it the *relative* one you would type from the
    root — which is `paths.cmd()`, the only speller of a stage command here.

    A double-click has no terminal standing by to explain itself afterwards, so
    the one failure worth catching — this file copied elsewhere, or the folder
    dragged out of the project — says so on screen and waits for a keypress before
    the window closes. That message carries the command inside a **quoted**
    heredoc: `paths.cmd()` returns double quotes around the script path and
    `shlex.quote` can add single ones (a shoot named `Casa d'Água`), and
    `<<'ABRIR-FIM'` is the one construct where neither is parsed. A `print` or an
    `echo` here breaks on the first quote.

    `exec` makes Python *be* the process, so the Terminal's Ctrl-C lands straight
    in `serve_forever()`'s KeyboardInterrupt with no shell left over to confuse
    the exit code.
    """
    return f"""#!/bin/zsh
# {LAUNCHER} — escrito ao lado da página de revisão, toda vez que ela é escrita.
# Duplo clique no Finder: abre um Terminal na raiz do projeto, redesenha esta
# página com o que já está no disco, serve por http e abre o navegador — que é o
# que faz os botões de um clique dela funcionarem. Ctrl-C ali encerra.
#
# Gerado. Qualquer edição aqui se perde na próxima vez.
cd "${{0:A:h:h:h}}" || exit 1
if [ ! -x "{paths.VENV_PY}" ]; then
  cat >&2 <<'ABRIR-FIM'
error: este atalho não achou o python do projeto a partir da pasta acima.
       Ele só vale de dentro do projeto. Se você copiou este arquivo para outro
       lugar, ou arrastou a pasta para fora, rode na raiz do projeto:

         {command}

ABRIR-FIM
  printf 'Enter para fechar '
  read -r _
  exit 1
fi
exec {command}
"""


def write_launcher(folder: Path, command: str) -> Path:
    """Write `Abrir.command` beside the page, executable. Returns its path.

    Through a temporary and `os.replace`, like every other file this pipeline
    writes: a double-click that caught a half-written script would run half a
    command. The `chmod` happens on the temporary, *before* the rename, so the
    file is never visible without its executable bit — Finder offers to open a
    non-executable `.command` in TextEdit, which is a confusing dead end.
    """
    dest = Path(folder) / LAUNCHER
    scratch = dest.with_name(dest.name + ".new")
    try:
        scratch.write_text(launcher_body(command), encoding="utf-8")
        scratch.chmod(0o755)
        os.replace(scratch, dest)
    finally:
        scratch.unlink(missing_ok=True)
    return dest
