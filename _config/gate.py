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

A browser page cannot write into the folder it sits in, so every decision comes
back through the clipboard and one file the human pastes into: `gate.txt`, beside
the page. Stage 0 keeps `picks.txt` — a positive list of 63 out of 307 is not the
same statement as "these 3 of 63 go back" — but both are read by `parse()`.

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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

NAME = "gate.txt"
RECORD = "gate.md"

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


def zoom_div() -> str:
    """The lightbox, deliberately without an inline onclick — see `closeZoom` in
    BASE_JS for why that inline handler broke the A/B flip."""
    return '<div id="zoom"><img alt=""></div>'


def header_line(page: str, job: str) -> str:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"# {NAME} — {job} · copiado de {page} em {stamp}"
