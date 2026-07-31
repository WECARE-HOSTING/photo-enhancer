#!/usr/bin/env python3
"""`review-marca.html` — the gate between `2 - marca dagua/` and `3 - completed/`.

Written by `batch.py`. This is the last look before a photograph reaches a
client, and it asks one question the other two pages cannot: **is the mark
legible where it landed?**

That question does not survive a thumbnail. The mark is 295×56 px on a 2048 px
photo — 2% of the frame — so the primary view here is a **1:1 crop of the top-left
corner**, at native resolution.

The crop is CSS, not a file: `object-fit:none` with `object-position:0 0` inside
a fixed box shows the image's own top-left pixels at exactly 1:1, with no
resampling at any point. Writing 60 crop files per job would have cost 3.6 MB in
every archive forever — and, worse, a `<stem>_crop.jpg` carries no result marker,
so `photos_in()` would have read each one as a source photograph and sent it to
the paid API.

Each photo also carries the measurement that produced its ink — background
luminance, contrast against each colourway, whether the glow fired and why — so
an override is an informed decision rather than a guess. Those numbers are
measured fresh, not read out of `marca.md`: no script in this project reads a log
to decide anything.

    marque uma foto          ->  ela é remarcada (grátis, sem API)
    auto / escuro / claro    ->  força a tinta naquela foto
    Copiar marcações         ->  cole em gate.txt, depois batch.py --rework
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

NAME = "review-marca.html"
STAGE = Path(__file__).resolve().parent.name

# How much of the photo around the mark the 1:1 crop shows, as a multiple of the
# margin. 2 gives roughly a mark's-worth of wall on each side — enough to judge
# it against its background without scrolling a 2048px image.
CROP_PAD = 2


def parts(stem: str) -> "tuple[str, str]":
    got = ambientes.parse_name(stem)
    if not got:
        return "SEM_AMBIENTE", "—"
    amb, sala, _ = got
    return amb, f"{amb}_{sala:02d}"


def sort_key(stem: str) -> tuple:
    got = ambientes.parse_name(stem)
    return (0, *got) if got else (1, stem, 0, 0)


def write(job: Path, trios: "list[tuple[Path, Path, dict]]", wall: str,
          missing: "list[str]", marks: "list | None" = None) -> Path:
    """`trios` is (edit, final, facts) for every photo that has a mark."""
    rows: "list[str]" = []
    open_room = open_amb = None

    for edit, final, f in sorted(trios, key=lambda t: sort_key(t[0].stem)):
        stem = f["stem"]
        amb, room = parts(stem)
        if room != open_room:
            if open_room is not None:
                rows.append("</section>")
            n = sum(1 for e, _, _ in trios if parts(e.stem)[1] == room)
            anchor = f' id="{gate.esc(amb)}"' if amb != open_amb else ""
            open_amb, open_room = amb, room
            rows.append(
                f'<section{anchor}><h2>{gate.esc(room)}'
                f'<small>{n} foto{"s" if n != 1 else ""} · '
                f'<b class="rej" data-for="{gate.esc(room)}">0</b> refazer</small>'
                f'</h2>')

        mx, my, lw, lh = f["box"]
        cw, ch = lw + mx * CROP_PAD, lh + my * CROP_PAD
        badge = (f'{f["variant"]} · {f["contrast"]:.2f}:1'
                 + (f' · glow ({f["reason"]})' if f["glow"] else ""))
        detail = (f'fundo L {f["L"]:.3f} · desvio {f["std"]:.3f} · '
                  f'navy {f["c_dark"]:.2f}:1 · creme {f["c_light"]:.2f}:1')
        k = gate.esc(stem)

        radios = "".join(
            f'<label class="opt"><input type="radio" data-opt data-key="{k}" '
            f'name="v_{k}" value="{v}"{" checked" if v == "" else ""}>'
            f'<span>{lbl}</span></label>'
            for v, lbl in (("", "auto"), ("variant=escuro", "navy"),
                           ("variant=claro", "creme"), ("glow=on", "+glow")))

        rows.append(
            f'<div class="pair" data-item id="{k}">'
            f'<label class="tick"><input type="checkbox" data-key="{k}" '
            f'data-group="{gate.esc(room)}"><span>refazer</span></label>'
            f'<code>{k}</code><span class="badge">{gate.esc(badge)}</span>'
            f'<div class="two">'
            f'<figure class="crop" style="width:{cw}px;height:{ch}px">'
            f'<img class="zoomable" src="{gate.esc(final.name)}" alt="" '
            f'style="object-position:0 0">'
            f'<figcaption>1:1 · o canto de verdade</figcaption></figure>'
            f'<figure class="whole"><img class="zoomable" '
            f'src="{gate.esc(final.name)}" loading="lazy" alt="">'
            f'<figcaption>a foto inteira</figcaption></figure>'
            f'</div>'
            f'<p class="detail">{gate.esc(detail)}</p>'
            f'<div class="opts">{radios}</div>'
            f'<textarea class="note" rows="1" data-key="{k}" '
            f'placeholder="o que houve com a marca nesta foto"></textarea>'
            f'</div>')
    if open_room is not None:
        rows.append("</section>")

    nav = " · ".join(
        f'<a href="#{gate.esc(a)}">{gate.esc(a)}</a>'
        for a in sorted({parts(e.stem)[0] for e, _, _ in trios}))

    warn = ""
    if missing:
        warn = (f'<p class="warn"><b>{len(missing)} foto(s) sem marca</b> e fora '
                "desta página: " + gate.esc(", ".join(missing[:8]))
                + (" …" if len(missing) > 8 else "")
                + ". Rode <code>batch.py</code> de novo — é grátis.</p>")

    glows = sum(1 for _, _, f in trios if f["glow"])
    creme = sum(1 for _, _, f in trios if f["variant"] == "claro")
    approve = paths.cmd(Path(__file__).resolve().parent / "batch.py",
                        "--approve", "--job", job.name)

    dest = job / NAME
    dest.write_text(TEMPLATE.format(
        css=gate.BASE_CSS + OWN_CSS,
        js=gate.BASE_JS,
        body="\n".join(rows),
        job=gate.esc(job.name),
        n=len(trios),
        navy=len(trios) - creme,
        creme=creme,
        glows=glows,
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
.badge { font-size:11px; margin-left:.5rem; padding:.1rem .45rem; border-radius:4px;
  background:var(--note); color:var(--dim); font-family:ui-monospace, Menlo, monospace }
.detail { margin:.4rem 0 0; font-size:11px; color:var(--dim);
  font-family:ui-monospace, Menlo, monospace }
.two { display:grid; grid-template-columns:auto 1fr; gap:.6rem; margin-top:.45rem;
  align-items:start }
@media (max-width: 900px) { .two { grid-template-columns:1fr } }
figure { margin:0; position:relative }
/* The 1:1 crop. object-fit:none means no scaling at all — the box is a window
   onto the file's own pixels, which is the only way to judge a 295x56 mark. */
figure.crop { overflow:hidden; border-radius:7px; background:var(--line);
  max-width:100%; flex:0 0 auto }
figure.crop img { width:100%; height:100%; object-fit:none; display:block;
  cursor:zoom-in }
figure.whole img { width:100%; display:block; border-radius:7px;
  background:var(--line); cursor:zoom-in }
figcaption { position:absolute; bottom:.4rem; left:.5rem; padding:.1rem .42rem;
  border-radius:4px; font-size:10.5px; font-weight:700; letter-spacing:.04em;
  text-transform:uppercase; color:var(--dim);
  background:color-mix(in srgb, var(--bg) 82%, transparent); backdrop-filter:blur(6px) }
.opts { display:flex; gap:.1rem; margin-top:.45rem; flex-wrap:wrap }
.opt { display:inline-flex; align-items:center; gap:.25rem; font-size:11px;
  color:var(--dim); cursor:pointer; padding:.15rem .5rem; border-radius:99px;
  border:1px solid var(--line) }
.opt input { margin:0; accent-color:var(--ok); width:13px; height:13px }
.opt:has(input:checked) { color:var(--fg); border-color:var(--dim);
  background:var(--note) }
"""

TEMPLATE = """<title>{job} — marca</title>
<style>{css}</style>

<h1>{job} — marca d'água</h1>
<p class="sub">{n} foto(s) · {navy} navy · {creme} creme · {glows} com glow ·
{wall} · {stamp}<br>
O recorte da esquerda é <b>1:1, pixels reais</b> — é ali que se vê se a marca
some. Marque a foto para refazê-la e, se quiser, force a tinta. Remarcar é
grátis: não há chamada de API neste estágio.<br>
{nav}</p>
{warn}

{body}

{zoom}

<div id="bar">
  <span id="n">0</span><span>para refazer, de {n}</span>
  <button class="bad" onclick="copyMarks()">Copiar marcações</button>
  <button onclick="setAll(false)">Limpar</button>
  <button class="go" id="ok" onclick="copyApprove()">Aprovar e arquivar</button>
  <span id="hint">Cole em <code>{gate_file}</code>, ao lado deste arquivo</span>
</div>

<script>
const GATE_HEADER = {js_header};
const GATE_FILE = {js_gate};
const APPROVABLE = {js_approvable};
const PREFILL = {js_prefill};
function copyApprove() {{
  copy({js_approve}, 'Comando copiado — cole no terminal para arquivar o trabalho');
}}
{js}
</script>
"""
