#!/usr/bin/env python3
"""`review-edit.html` — the gate between `1 - edit/` and `2 - marca dagua/`.

Written by `batch.py` at the end of every run. Nothing runs this directly.

A finished run used to archive itself the moment no photo had failed, which
confused two different questions: "did the API answer?" and "is this good enough
to send a client?". Only the first one a script can answer. So a job stops here
and waits, and this page is where the second question gets asked.

Source and result side by side, each half the window, grouped by ambiente, with a
comment box under every pair. The contact sheet's 215px thumbnails are right
there and wrong here: that page compares fifty photographs to each other, this
one compares exactly two, and a subtly wrong edit does not survive a thumbnail.

**The A/B flip is the point of this page.** Side by side answers "did it change";
it does not answer "did it change *correctly*", because the eye cannot carry a 3°
wall lean or an invented chair across a gap. Click either image to fill the
window, then press `a` / `b` — or click again — to swap between them in place, at
identical scale and position. A wrong edit that survives a side-by-side does not
survive a flip.

    marque uma foto     ->  ela volta para a fila
    escreva o porquê    ->  vira nota no gate.md e instrução extra no reprocessamento
    Copiar marcações    ->  cole em gate.txt, depois batch.py --rework
    Aprovar             ->  copia o comando que manda o trabalho adiante

Nothing here changes anything on disk. It copies text; you paste it. A page that
could write into its own folder would be a second source of truth able to
disagree with the files.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_config"))
import gate  # noqa: E402
import paths  # noqa: E402

# The one stage that imports across a sibling folder, and it goes through
# paths.py like everything else — a literal "0 - selection" here would be the
# sixth hardcoded stage path, in the file least likely to be grepped.
sys.path.insert(0, str(paths.SELECTION_DIR))
import ambientes  # noqa: E402  — the single owner of NAME_RE

NAME = "review-edit.html"
STAGE = Path(__file__).resolve().parent.name


def parts(stem: str) -> "tuple[str, str]":
    """(ambiente, room) for grouping. Unparseable names get their own heading
    rather than being hidden — they still have to be reviewable."""
    got = ambientes.parse_name(stem)
    if not got:
        return "SEM_AMBIENTE", "—"
    amb, sala, _ = got
    return amb, f"{amb}_{sala:02d}"


def sort_key(stem: str) -> tuple:
    got = ambientes.parse_name(stem)
    return (0, *got) if got else (1, stem, 0, 0)


def write(job: Path, pairs: "list[tuple[Path, Path]]", model: str, wall: str,
          missing: "list[str]", marks: "list | None" = None) -> Path:
    """One page for the whole job. `pairs` is (source, edit), already on disk."""
    rows: "list[str]" = []
    open_room = open_amb = None

    for src, edit in sorted(pairs, key=lambda p: sort_key(p[0].stem)):
        stem = src.stem
        amb, room = parts(stem)
        if room != open_room:
            if open_room is not None:
                rows.append("</section>")
            n = sum(1 for s, _ in pairs if parts(s.stem)[1] == room)
            anchor = f' id="{gate.esc(amb)}"' if amb != open_amb else ""
            open_amb, open_room = amb, room
            rows.append(
                f'<section{anchor}><h2>{gate.esc(room)}'
                f'<small>{n} foto{"s" if n != 1 else ""} · '
                f'<b class="rej" data-for="{gate.esc(room)}">0</b> de volta</small>'
                f'</h2>')

        a, b = gate.esc(src.name), gate.esc(edit.name)
        rows.append(
            f'<div class="pair" data-item id="{gate.esc(stem)}">'
            f'<label class="tick"><input type="checkbox" '
            f'data-key="{gate.esc(stem)}" data-group="{gate.esc(room)}">'
            f'<span>refazer</span></label>'
            f'<code>{gate.esc(src.name)}</code>'
            f'<div class="two">'
            f'<figure><img class="zoomable" src="{a}" data-a="{a}" data-b="{b}" '
            f'data-show="a" loading="lazy" alt="">'
            f'<figcaption>antes</figcaption></figure>'
            f'<figure><img class="zoomable" src="{b}" data-a="{a}" data-b="{b}" '
            f'data-show="b" loading="lazy" alt="">'
            f'<figcaption>depois</figcaption></figure>'
            f'</div>'
            f'<textarea class="note" rows="1" data-key="{gate.esc(stem)}" '
            f'placeholder="o que houve nesta foto — vira nota no registro, e '
            f'instrução extra se ela voltar"></textarea>'
            f'</div>')
    if open_room is not None:
        rows.append("</section>")

    nav = " · ".join(
        f'<a href="#{gate.esc(a)}">{gate.esc(a)}</a>'
        for a in sorted({parts(s.stem)[0] for s, _ in pairs}))

    warn = ""
    if missing:
        warn = (f'<p class="warn"><b>{len(missing)} foto(s) sem resultado</b> e '
                "portanto fora desta página: " + gate.esc(", ".join(missing[:8]))
                + (" …" if len(missing) > 8 else "")
                + ". Rode <code>batch.py</code> de novo para tentar só essas — "
                  "o trabalho não pode ser aprovado enquanto faltar uma.</p>")

    approve = paths.cmd(Path(__file__).resolve().parent / "batch.py",
                        "--approve", "--job", job.name)

    dest = job / NAME
    dest.write_text(TEMPLATE.format(
        css=gate.BASE_CSS + OWN_CSS,
        js=OWN_JS + gate.BASE_JS,
        body="\n".join(rows),
        job=gate.esc(job.name),
        n=len(pairs),
        rooms=len({parts(s.stem)[1] for s, _ in pairs}),
        model=gate.esc(model),
        wall=gate.esc(wall),
        stamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        nav=nav,
        warn=warn,
        zoom=gate.zoom_div(),
        gate_file=gate.NAME,
        js_header=gate.js(gate.header_line(NAME, job.name)),
        js_gate=gate.js(gate.NAME),
        js_approvable="false" if missing else "true",
        js_approve=gate.js(approve + "\n"),
        js_prefill=gate.js([
            {"key": m.key, "back": m.back, "comment": m.comment, "opts": m.opts}
            for m in (marks or [])]),
    ), encoding="utf-8")
    return dest


OWN_CSS = """
.pair { margin:0 0 1.6rem; border:2px solid transparent; border-radius:10px;
  padding:.5rem .55rem .55rem; transition:border-color .12s }
.pair.out { border-color:var(--rej);
  background:color-mix(in srgb, var(--rej) 7%, transparent) }
.pair > code { font-size:11.5px; color:var(--dim); margin-left:.6rem }
/* Two panes, each half the row. They collapse to one column on a narrow screen
   rather than shrinking to a pair of thumbnails, which would defeat the page. */
.two { display:grid; grid-template-columns:1fr 1fr; gap:.6rem; margin-top:.45rem }
@media (max-width: 900px) { .two { grid-template-columns:1fr } }
figure { margin:0; position:relative }
figure img { width:100%; display:block; border-radius:7px; background:var(--line);
  cursor:zoom-in }
figcaption { position:absolute; top:.5rem; left:.5rem; padding:.1rem .42rem;
  border-radius:4px; font-size:10.5px; font-weight:700; letter-spacing:.04em;
  text-transform:uppercase; color:var(--dim);
  background:color-mix(in srgb, var(--bg) 78%, transparent); backdrop-filter:blur(6px) }
#flip { position:fixed; top:1rem; left:50%; transform:translateX(-50%); z-index:21;
  padding:.3rem .75rem; border-radius:99px; font-size:12px; font-weight:600;
  letter-spacing:.06em; text-transform:uppercase; pointer-events:none;
  background:#000b; color:#fff; display:none }
body.zoom #flip { display:block }
"""

# Both images are already in the DOM and already decoded, so swapping the
# lightbox's src is instant and lands on exactly the same pixels — which is the
# whole reason this comparison works where side-by-side does not.
OWN_JS = """
let zoomA = '', zoomB = '', zoomOn = 'b';

function showZoom(which) {
  zoomOn = which;
  document.querySelector('#zoom img').src = (which === 'a' ? zoomA : zoomB);
  document.getElementById('flip').textContent =
    (which === 'a' ? 'antes' : 'depois') + '   a / b para trocar';
}
document.addEventListener('click', e => {
  if (e.target.matches('img.zoomable')) {
    zoomA = e.target.dataset.a; zoomB = e.target.dataset.b;
    showZoom(e.target.dataset.show || 'b');
  } else if (e.target.matches('#zoom img')) {
    showZoom(zoomOn === 'a' ? 'b' : 'a');    // click the image flips; the backdrop closes
    e.stopPropagation();
  }
});
document.addEventListener('keydown', e => {
  if (!document.body.classList.contains('zoom')) return;
  if (e.key === 'a' || e.key === 'b') { showZoom(e.key); e.preventDefault(); }
  if (e.key === ' ') { showZoom(zoomOn === 'a' ? 'b' : 'a'); e.preventDefault(); }
});
"""

TEMPLATE = """<title>{job} — edição</title>
<style>{css}</style>

<h1>{job} — edição</h1>
<p class="sub">{n} foto(s) em {rooms} ambiente(s) · <code>{model}</code> ·
{wall} · {stamp}<br>
Marque as que <b>não</b> estão boas e escreva o porquê. Clique numa imagem para
enchê-la na tela e aperte <b>a</b> / <b>b</b> para alternar antes e depois no
mesmo lugar — é assim que se vê o que o lado a lado esconde.<br>
{nav}</p>
{warn}

{body}

{zoom}
<div id="flip"></div>

<div id="bar">
  <span id="n">0</span><span>de volta, de {n}</span>
  <button class="bad" onclick="copyMarks()">Copiar marcações</button>
  <button onclick="setAll(false)">Limpar</button>
  <button class="go" id="ok" onclick="copyApprove()">Aprovar</button>
  <span id="hint">Cole em <code>{gate_file}</code>, ao lado deste arquivo</span>
</div>

<script>
const GATE_HEADER = {js_header};
const GATE_FILE = {js_gate};
const APPROVABLE = {js_approvable};
const PREFILL = {js_prefill};
function copyApprove() {{
  copy({js_approve},
       'Comando copiado — cole no terminal para mandar o trabalho adiante');
}}
{js}
</script>
"""
