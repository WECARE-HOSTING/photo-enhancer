#!/usr/bin/env python3
"""`review.html` — the job's before-and-after, for a person to approve or reject.

Written by `batch.py` at the end of every run. Nothing runs this directly.

A finished run used to archive itself the moment no photo had failed, which
confused two different questions: "did the API answer?" and "is this good enough
to send a client?". Only the first one a script can answer. So a job now stops
here and waits, and this page is where the second question gets asked.

The shape is the contact sheet's, deliberately — same clipboard trick, because a
browser page cannot write into the folder it is sitting in, and a download landing
in ~/Downloads would be worse than a copy button. What is different is the size:
the contact sheet shows 215px thumbnails because the job there is comparing fifty
photographs to each other, while the job here is comparing exactly two, and the
difference between a good edit and a subtly wrong one does not survive a thumbnail.

    tick a photo   ->  reject it
    Copy rejected  ->  paste into rework.txt, then batch.py --rework
    Approve        ->  copies the command that archives the job

Grouped by ambiente, read straight off the filenames — `QUARTO_01_0002_edit.jpg`
is bedroom 1, photo 2 — so nothing here parses `job.md`.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

# The canonical name `0 - selection/` writes. The owner of this shape is
# `0 - selection/ambientes.py`; this is a copy, because a folder name with spaces
# in it cannot be imported across. `_dependencies.md` lists every copy — grep for
# `NAME_RE` before changing the shape of a name.
NAME_RE = re.compile(r"^(?P<ambiente>[A-Z][A-Z_]*)_(?P<sala>\d{2})_(?P<n>\d{4})$")

REVIEW_NAME = "review.html"
REWORK_NAME = "rework.txt"


def group_key(stem: str) -> "tuple[str, int, int, str]":
    """Sort key that puts a job in ambiente order, rooms and photos in number order.

    A name that is not one of ours sorts last, under its own heading, rather than
    being hidden: a job dropped straight into `1 - input/` never went through the
    naming stage and still has to be reviewable.
    """
    if m := NAME_RE.match(stem):
        return m.group("ambiente"), int(m.group("sala")), int(m.group("n")), stem
    return "￿", 0, 0, stem


def ambiente_of(stem: str) -> str:
    m = NAME_RE.match(stem)
    return m.group("ambiente") if m else "SEM AMBIENTE"


def room_of(stem: str) -> str:
    m = NAME_RE.match(stem)
    return f"{m.group('ambiente')}_{m.group('sala')}" if m else "—"


def write(job: Path, pairs: "list[tuple[Path, Path]]", model: str,
          wall: str, failed: "list[str]") -> Path:
    """One page for the whole job. `pairs` is (source, edit), already existing."""
    rows: "list[str]" = []
    open_room = open_ambiente = None
    for src, edit in sorted(pairs, key=lambda p: group_key(p[0].stem)):
        stem = src.stem
        room = room_of(stem)
        if room != open_room:
            if open_room is not None:
                rows.append("</section>")
            n = sum(1 for s, _ in pairs if room_of(s.stem) == room)
            # The ambiente's anchor goes on its first room, which is where the nav
            # at the top of the page should land you. Rooms of one ambiente are
            # adjacent because `group_key` sorts on the ambiente first.
            amb = ambiente_of(stem)
            anchor = f' id="{html.escape(amb)}"' if amb != open_ambiente else ""
            open_ambiente = amb
            rows.append(f'<section{anchor}><h2>{html.escape(room)}'
                        f'<small>{n} photo{"s" if n != 1 else ""} · '
                        f'<b class="rej" data-for="{html.escape(room)}">0</b> '
                        f'rejected</small></h2>')
            open_room = room

        rows.append(
            f'<div class="pair" id="{html.escape(stem)}">'
            f'<label class="tick"><input type="checkbox" '
            f'data-stem="{html.escape(stem)}" data-room="{html.escape(room)}">'
            f'<span>reprovar</span></label>'
            f'<code>{html.escape(src.name)}</code>'
            f'<div class="two">'
            f'<figure><img src="{html.escape(src.name)}" loading="lazy" alt="">'
            f'<figcaption>antes</figcaption></figure>'
            f'<figure><img src="{html.escape(edit.name)}" loading="lazy" alt="">'
            f'<figcaption>depois</figcaption></figure>'
            f'</div></div>')
    if open_room is not None:
        rows.append("</section>")

    ambientes = sorted({ambiente_of(s.stem) for s, _ in pairs})
    nav = " · ".join(f'<a href="#{html.escape(a)}">{html.escape(a)}</a>'
                     for a in ambientes)

    warn = ""
    if failed:
        warn = (f'<p class="warn"><b>{len(failed)} photo(s) have no edit</b> and are '
                "not shown below: " + html.escape(", ".join(failed[:8]))
                + (" …" if len(failed) > 8 else "")
                + ". Re-run <code>batch.py</code> to retry just those. The job "
                  "cannot be approved until every photo has one.</p>")

    dest = job / REVIEW_NAME
    dest.write_text(TEMPLATE.format(
        job=html.escape(job.name),
        n=len(pairs),
        rooms=len(({room_of(s.stem) for s, _ in pairs})),
        model=html.escape(model),
        wall=html.escape(wall),
        stamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        nav=nav,
        warn=warn,
        approvable="false" if failed else "true",
        rework=REWORK_NAME,
        body="\n".join(rows),
    ), encoding="utf-8")
    return dest


TEMPLATE = """<title>{job} — review</title>
<style>
:root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --dim:#666; --line:#e2e2e2;
        --ok:#0a7d3c; --rej:#b3261e; --warnbg:#fff4e5; --warnfg:#8a4b00; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141414; --fg:#ececec; --dim:#9a9a9a; --line:#2e2e2e;
          --ok:#4ec97f; --rej:#ff6b5e; --warnbg:#3a2c14; --warnfg:#ffd28a; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; padding:1.4rem 1.4rem 6rem; background:var(--bg); color:var(--fg);
  font:14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif }}
h1 {{ font-size:1.35rem; margin:0 0 .3rem }}
.sub {{ color:var(--dim); font-size:12.5px; margin:0 0 1rem }}
.sub a {{ color:inherit }}
.warn {{ margin:0 0 1.2rem; padding:.6rem .8rem; border-radius:7px;
  background:var(--warnbg); color:var(--warnfg); font-size:12.5px }}
h2 {{ font-size:.95rem; margin:2.2rem 0 .7rem; padding-bottom:.3rem;
  border-bottom:1px solid var(--line); display:flex; justify-content:space-between;
  align-items:baseline; position:sticky; top:0; background:var(--bg); z-index:2 }}
h2 small {{ color:var(--dim); font-weight:400 }}
.pair {{ margin:0 0 1.6rem; border:2px solid transparent; border-radius:10px;
  padding:.5rem .55rem .2rem; transition:border-color .12s }}
.pair.out {{ border-color:var(--rej); background:color-mix(in srgb, var(--rej) 7%, transparent) }}
.pair > code {{ font-size:11.5px; color:var(--dim); margin-left:.6rem }}
.tick {{ display:inline-flex; gap:.35rem; align-items:center; cursor:pointer;
  font-size:11.5px; color:var(--dim); user-select:none }}
.tick input {{ width:17px; height:17px; accent-color:var(--rej); cursor:pointer; margin:0 }}
.pair.out .tick span {{ color:var(--rej); font-weight:700 }}
/* Two panes side by side, each half the row. They collapse to one column on a
   narrow screen rather than shrinking to a pair of thumbnails, which would defeat
   the point of this page. */
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:.6rem; margin-top:.45rem }}
@media (max-width: 900px) {{ .two {{ grid-template-columns:1fr }} }}
figure {{ margin:0; position:relative }}
figure img {{ width:100%; display:block; border-radius:7px; background:var(--line);
  cursor:zoom-in }}
figcaption {{ position:absolute; top:.5rem; left:.5rem; padding:.1rem .42rem;
  border-radius:4px; font-size:10.5px; font-weight:700; letter-spacing:.04em;
  text-transform:uppercase; background:color-mix(in srgb, var(--bg) 78%, transparent);
  backdrop-filter:blur(6px); color:var(--dim) }}
/* Click either pane to fill the window with it. The one comparison a side-by-side
   layout cannot make is "is this detail right", and that needs the pixels. */
body.zoom {{ overflow:hidden }}
#zoom {{ display:none; position:fixed; inset:0; z-index:20; background:#000d;
  backdrop-filter:blur(4px); cursor:zoom-out; padding:1rem }}
#zoom.on {{ display:flex; align-items:center; justify-content:center }}
#zoom img {{ max-width:100%; max-height:100%; object-fit:contain; border-radius:6px }}
#bar {{ position:fixed; left:0; right:0; bottom:0; padding:.7rem 1.4rem;
  background:color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter:blur(12px); border-top:1px solid var(--line);
  display:flex; gap:.8rem; align-items:center; z-index:9 }}
button {{ font:inherit; padding:.42rem .85rem; border-radius:7px; cursor:pointer;
  border:1px solid var(--line); background:var(--bg); color:var(--fg) }}
button.go {{ background:var(--ok); border-color:var(--ok); color:#fff; font-weight:600 }}
button.bad {{ background:var(--rej); border-color:var(--rej); color:#fff; font-weight:600 }}
button:disabled {{ opacity:.4; cursor:not-allowed }}
#n {{ font-variant-numeric:tabular-nums; font-weight:600 }}
#hint {{ color:var(--dim); margin-left:auto; font-size:12px; text-align:right }}
code {{ font-family:ui-monospace, SFMono-Regular, Menlo, monospace }}
</style>

<h1>{job} — review</h1>
<p class="sub">{n} photo(s) across {rooms} room(s) · <code>{model}</code> ·
{wall} · {stamp}<br>
Tick the ones that are <b>not</b> good enough to send. Click either image to fill
the screen. Nothing is decided in this page — it copies a list, you paste it.<br>
{nav}</p>
{warn}

{body}

<div id="zoom" onclick="this.classList.remove('on');document.body.classList.remove('zoom')">
  <img alt=""></div>

<div id="bar">
  <span id="n">0</span><span>rejected of {n}</span>
  <button class="bad" onclick="copyRejected()">Copy rejected</button>
  <button onclick="setAll(false)">Clear</button>
  <button class="go" id="ok" onclick="copyApprove()">Approve job</button>
  <span id="hint">Rejected go in <code>{rework}</code> beside this file</span>
</div>

<script>
const JOB = {job!r};
const APPROVABLE = {approvable};
const boxes = () => [...document.querySelectorAll('input[data-stem]')];

function paint() {{
  const on = boxes().filter(b => b.checked);
  document.getElementById('n').textContent = on.length;
  boxes().forEach(b => b.closest('.pair').classList.toggle('out', b.checked));
  const per = {{}};
  on.forEach(b => per[b.dataset.room] = (per[b.dataset.room] || 0) + 1);
  document.querySelectorAll('.rej').forEach(el => {{
    el.textContent = per[el.dataset.for] || 0;
  }});
  // Approving a job you have just rejected photographs in is always a mistake:
  // the rework would be thrown away by the archive step.
  const ok = document.getElementById('ok');
  ok.disabled = on.length > 0 || !APPROVABLE;
  ok.title = on.length ? 'Clear the rejections first, or copy them into rework.txt'
           : (APPROVABLE ? '' : 'Some photos have no edit yet — re-run batch.py');
}}
document.addEventListener('change', e => {{
  if (e.target.matches('input[data-stem]')) paint();
}});
function setAll(v) {{ boxes().forEach(b => b.checked = v); paint(); }}

document.addEventListener('click', e => {{
  if (!e.target.matches('figure img')) return;
  const z = document.getElementById('zoom');
  z.querySelector('img').src = e.target.src;
  z.classList.add('on');
  document.body.classList.add('zoom');
}});
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{
    document.getElementById('zoom').classList.remove('on');
    document.body.classList.remove('zoom');
  }}
}});

function copy(text, msg) {{
  navigator.clipboard.writeText(text).then(
    () => {{ document.getElementById('hint').textContent = msg; }},
    () => {{ document.getElementById('hint').textContent =
             'Clipboard blocked — open this file from disk, not over http.'; }});
}}
function copyRejected() {{
  const on = boxes().filter(b => b.checked).map(b => b.dataset.stem);
  if (!on.length) {{
    document.getElementById('hint').textContent =
      'Nothing ticked — tick what needs redoing first.';
    return;
  }}
  copy(on.join('\\n') + '\\n',
       'Copied ' + on.length + ' — paste into {rework}, then run batch.py --rework');
}}
function copyApprove() {{
  copy('./_config/.venv/bin/python "2 - in progress/batch.py" --approve --job '
       + JOB + '\\n', 'Command copied — paste it in the terminal to archive the job');
}}
paint();
</script>
"""
