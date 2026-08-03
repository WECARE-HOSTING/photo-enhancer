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

**A photograph that has been retouched shows three panes and asks a second
question.** `original / edição anterior / retoque`, flipped with `a` / `c` / `b`,
and under them the sentences you wrote, newest in the open and older ones folded.
The question stops being "is this good" and becomes "is this what I asked for" —
which nobody can answer from memory after eight requests in one round. The
sentences come from each photograph's `<stem>_log.md` and from `gate.md`, through
`retoque.history()` and `gate.passes()`; a request whose retouch failed has a row
in the second and no block in the first, and says so on the page.

    marque uma foto     ->  ela volta para a fila
    escreva o que mudar ->  vira nota no gate.md E o prompt inteiro do retoque
    Copiar marcações    ->  cole em gate.txt, depois batch.py --rework
    Aprovar             ->  copia o comando que manda o trabalho adiante

**The box is not a note, it is the prompt.** Phase 3 sends what is written there
and nothing else — `1 - edicao/PROMPT.md` is not read — against the image on the
*right*, with the original alongside it for reference. So it may ask for what
phase 1 forbids: put the person back, shift the angle. A photo ticked with an
empty box has nothing to send, and `--rework` refuses rather than guessing.

Nothing here changes anything on disk. It copies text; you paste it. A page that
could write into its own folder would be a second source of truth able to
disagree with the files.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
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

sys.path.insert(0, str(paths.RETOQUE_DIR))
import retoque  # noqa: E402  — history(): what was asked of each photograph

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


# --------------------------------------------------------- what you asked for

@dataclass
class Ask:
    """One thing a human asked of one photograph, and what came of it."""
    label: str          # "retoque 1" · "rodada 2" — what to call it on the page
    text: str           # the sentence, verbatim
    when: str = ""
    previous: str = ""  # the edit that request replaced, if it produced one
    kind: str = "done"  # "done" | "failed" | "kept"


def merge(job: Path, logs: "dict[str, list]", rounds: "list") -> "dict[str, list[Ask]]":
    """Per photograph, everything that has been asked of it, oldest first.

    Two sources, because neither answers alone. `<stem>_log.md` (`logs`) knows
    what was actually sent and which `_edit_rN.jpg` it displaced — but a
    photograph whose retouch *failed*, or one kept with a note, has no block
    there at all. `gate.md` (`rounds`) has a row for both. Pairing them by the
    sentence is exact: the same string is written to both files, through
    `ledger.cell()` on each side.
    """
    out: "dict[str, list[Ask]]" = {}

    for stem, history in logs.items():
        out[stem] = [Ask(label=f"retoque {r.n}", text=r.instruction, when=r.when,
                         previous=r.previous)
                     for r in history if r.instruction]

    for a_pass in rounds:
        for key, (back, note) in a_pass.rows.items():
            if not note:
                continue
            asks = out.setdefault(key, [])
            if any(a.text == note for a in asks):
                continue            # the retouch it produced is already listed
            asks.append(Ask(label=f"rodada {a_pass.round_n}", text=note,
                            when=a_pass.when,
                            kind="failed" if back else "kept"))
    return out


def gather(job: Path, pairs: "list[tuple[Path, Path]]") -> "dict[str, list[Ask]]":
    """`merge()` over a whole job. Kept here so `batch.py` stays one line."""
    logs = {src.stem: retoque.history(job / f"{src.stem}_log.md")
            for src, _ in pairs}
    return merge(job, logs, gate.passes(job, STAGE))


def shelved_edit(job: Path, stem: str, asks: "list[Ask]") -> str:
    """The newest `_edit_rN.jpg` for this photograph — the third pane.

    The log names it, but the disk is what can actually be displayed, so the
    disk wins: `--approve` deletes these, and a log outlives the file it names.
    """
    def number(p: Path) -> int:
        tail = p.stem.rsplit("_r", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    found = sorted(job.glob(f"{stem}_edit_r*.jpg"), key=number)
    if found:
        return found[-1].name
    named = [a.previous for a in asks if a.previous]
    return named[-1] if named and (job / named[-1]).exists() else ""


def when_short(iso: str) -> str:
    """`2026-08-01T07:52:32+00:00` -> `01/08 07:52`. The stamp is there to tell
    two rounds of the same day apart, not to be a date."""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return ""


def ask_line(a: Ask, tag: str = "p") -> str:
    """One request, as it appears under the photograph it was made about."""
    stamp = when_short(a.when)
    bits = [f'<b>{gate.esc(a.label)}</b> <q>{gate.esc(a.text)}</q>']
    if stamp:
        bits.append(f'<time>{stamp}</time>')
    if a.kind == "failed":
        bits.append('<em class="miss">nada voltou — o retoque falhou</em>')
    elif a.kind == "kept":
        bits.append('<em>anotação: a foto não voltou por causa disto</em>')
    elif a.previous:
        bits.append(f'<button type="button" class="mini" '
                    f'data-see="{gate.esc(a.previous)}" '
                    f'data-ask="{gate.esc(a.text)}">ver a edição de antes</button>')
    return f'<{tag} class="ask {a.kind}">' + " ".join(bits) + f'</{tag}>'


def asks_block(asks: "list[Ask]") -> str:
    """What was asked of this photograph, newest in the open, older folded.

    The newest is never behind a click: with eight requests in a round, the one
    thing a human cannot do is remember which sentence belongs to which
    photograph — and checking that against what came back is the whole point of
    looking at the page a second time.
    """
    if not asks:
        return ""
    older, newest = asks[:-1], asks[-1]
    out = [f'<div class="asks">{ask_line(newest)}']
    if older:
        out.append(
            f'<details class="hist"><summary>{len(older)} pedido'
            f'{"s" if len(older) != 1 else ""} anterior'
            f'{"es" if len(older) != 1 else ""}</summary><ol>'
            + "".join(ask_line(a, "li") for a in reversed(older))
            + '</ol></details>')
    return "".join(out) + "</div>"


def write(job: Path, pairs: "list[tuple[Path, Path]]", model: str, wall: str,
          missing: "list[str]", marks: "list | None" = None,
          history: "dict[str, list[Ask]] | None" = None) -> Path:
    """One page for the whole job. `pairs` is (source, edit), already on disk."""
    rows: "list[str]" = []
    open_room = open_amb = None
    history = history or {}

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

        asks = history.get(stem, [])
        a, b = gate.esc(src.name), gate.esc(edit.name)
        c = gate.esc(shelved_edit(job, stem, asks))
        # The pane between them only exists once a retouch has replaced an edit.
        # With it, "antes / depois" is the wrong pair of words — all three are a
        # before and an after of something.
        last = next((x for x in reversed(asks) if x.previous), None)
        data = (f'data-a="{a}" data-b="{b}" data-c="{c}" '
                f'data-ask="{gate.esc(last.text) if last and c else ""}"')

        def pane(src_name: str, which: str, caption: str) -> str:
            return (f'<figure><img class="zoomable" src="{src_name}" {data} '
                    f'data-show="{which}" loading="lazy" alt="">'
                    f'<figcaption>{caption}</figcaption></figure>')

        panes = [pane(a, "a", "original")]
        if c:
            panes.append(pane(c, "c", "edição anterior"))
        panes.append(pane(b, "b", "retoque" if c else "edição"))

        rows.append(
            f'<div class="pair" data-item id="{gate.esc(stem)}">'
            f'<label class="tick"><input type="checkbox" '
            f'data-key="{gate.esc(stem)}" data-group="{gate.esc(room)}">'
            f'<span>refazer</span></label>'
            f'<code>{gate.esc(src.name)}</code>'
            f'<div class="{"three" if c else "two"}">' + "".join(panes) + '</div>'
            + asks_block(asks) +
            f'<textarea class="note" rows="1" data-key="{gate.esc(stem)}" '
            f'placeholder="o que mudar na foto da direita — este texto é a '
            f'instrução inteira, e pode pedir o que o prompt padrão não deixa '
            f'(devolver uma pessoa, mudar o ângulo)"></textarea>'
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
    page = TEMPLATE.format(
        css=gate.BASE_CSS + OWN_CSS + gate.SERVE_CSS,
        # BASE_JS opens the lightbox from the clicked thumbnail; OWN_JS runs
        # after it so its src and caption win. Both are one <script>, so the
        # hoisted zoomFlip() is visible to BASE_JS whatever the order. SERVE_JS
        # goes last: it probes for a server and needs GATE_TEXT defined.
        js=gate.BASE_JS + OWN_JS + gate.SERVE_JS,
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
        srv_bar=gate.SERVE_BAR,
        js_header=gate.js(gate.header_line(NAME, job.name)),
        js_gate=gate.js(gate.NAME),
        js_approvable="false" if missing else "true",
        js_approve=gate.js(approve + "\n"),
        js_prefill=gate.js([
            {"key": m.key, "back": m.back, "comment": m.comment, "opts": m.opts}
            for m in (marks or [])]),
    )
    # Through a temporary, like everything else this pipeline writes: the page is
    # rewritten while a browser may be asking for it, and half a page renders as
    # a job with no photographs rather than as an error.
    scratch = dest.with_suffix(".html.new")
    scratch.write_text(page, encoding="utf-8")
    scratch.replace(dest)
    return dest


OWN_CSS = """
.pair { margin:0 0 1.6rem; border:2px solid transparent; border-radius:10px;
  padding:.5rem .55rem .55rem; transition:border-color .12s }
.pair.out { border-color:var(--rej);
  background:color-mix(in srgb, var(--rej) 7%, transparent) }
.pair > code { font-size:11.5px; color:var(--dim); margin-left:.6rem }
/* Two panes, each half the row — three once a retouch has an edit to compare
   against. They collapse to one column on a narrow screen rather than shrinking
   to a row of thumbnails, which would defeat the page. */
.two { display:grid; grid-template-columns:1fr 1fr; gap:.6rem; margin-top:.45rem }
.three { display:grid; grid-template-columns:1fr 1fr 1fr; gap:.6rem; margin-top:.45rem }
@media (max-width: 900px) { .two, .three { grid-template-columns:1fr } }
/* What was asked, under the photograph it was asked about. */
.asks { margin-top:.5rem; font-size:12.5px }
.ask { margin:.25rem 0; color:var(--fg) }
.ask q { quotes:'“' '”'; }
.ask time { color:var(--dim); font-size:11.5px; margin-left:.35rem }
.ask em { font-style:normal; color:var(--dim); margin-left:.35rem }
.ask em.miss { color:var(--rej) }
.ask.kept { color:var(--dim) }
button.mini { padding:.1rem .45rem; font-size:11px; border-radius:5px;
  margin-left:.4rem; vertical-align:baseline }
.hist { margin:.2rem 0 0 }
.hist summary { color:var(--dim); font-size:11.5px; cursor:pointer }
.hist ol { margin:.3rem 0 0; padding-left:1.2rem; color:var(--dim) }
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
let zoomA = '', zoomB = '', zoomC = '', zoomAsk = '', zoomOn = 'b';

const PANE = { a: 'original', b: 'retoque', c: 'edição anterior' };
// Oldest to newest, which is also left to right on the page. Flipping in the
// order the photograph actually moved is what makes a change legible.
const zoomOrder = () => zoomC ? ['a', 'c', 'b'] : ['a', 'b'];

function showZoom(which) {
  if (which === 'c' && !zoomC) return;
  zoomOn = which;
  document.querySelector('#zoom img').src =
    (which === 'a' ? zoomA : which === 'c' ? zoomC : zoomB);
  const keys = zoomOrder().join(' / ');
  const name = (which === 'b' && !zoomC) ? 'edição' : PANE[which];
  // With the previous edit on screen, the sentence that replaced it is the
  // caption that matters: you are looking at what the retouch was asked about.
  const ask = (which === 'c' && zoomAsk) ? '   antes de “' + zoomAsk + '”' : '';
  document.getElementById('flip').textContent = name + ask + '   ' + keys +
    ' para trocar';
}
// gate.py's BASE_JS calls this when the zoomed image is clicked, so a click
// flips and only the backdrop closes. It also seeds which pair is open, from the
// thumbnail that was clicked to get here.
function zoomFlip() {
  const o = zoomOrder();
  showZoom(o[(o.indexOf(zoomOn) + 1) % o.length]);
}

function openZoom() {
  document.getElementById('zoom').classList.add('on');
  document.body.classList.add('zoom');
}

function seedZoom(el) {
  zoomA = el.dataset.a || '';
  zoomB = el.dataset.b || '';
  zoomC = el.dataset.c || '';
  zoomAsk = el.dataset.ask || '';
}

document.addEventListener('click', e => {
  if (e.target.matches('img.zoomable')) {
    seedZoom(e.target);
    showZoom(e.target.dataset.show || 'b');
    return;
  }
  // "ver a edição de antes", on one line of the request history. It opens that
  // round's shelved file even when a newer one is what the panes show.
  const mini = e.target.closest && e.target.closest('button.mini[data-see]');
  if (mini) {
    const img = mini.closest('.pair').querySelector('img.zoomable');
    if (!img) return;
    seedZoom(img);
    zoomC = mini.dataset.see;
    zoomAsk = mini.dataset.ask || '';
    openZoom();
    showZoom('c');
  }
});
document.addEventListener('keydown', e => {
  if (!document.body.classList.contains('zoom')) return;
  if (e.key === 'a' || e.key === 'b' || e.key === 'c') {
    showZoom(e.key); e.preventDefault();
  }
  if (e.key === ' ') { zoomFlip(); e.preventDefault(); }
});
"""

TEMPLATE = """<title>{job} — edição</title>
<style>{css}</style>

<h1>{job} — edição</h1>
<p class="sub">{n} foto(s) em {rooms} ambiente(s) · <code>{model}</code> ·
{wall} · {stamp}<br>
Marque as que <b>não</b> estão boas e escreva na caixa <b>o que mudar</b>. Clique
numa imagem para enchê-la na tela e aperte <b>a</b> / <b>b</b> para alternar
original e resultado no mesmo lugar — é assim que se vê o que o lado a lado
esconde. Uma foto que já passou por retoque ganha um terceiro painel e a tecla
<b>c</b>: a edição que o retoque substituiu, com o que você pediu embaixo dela.<br>
O que você escreve <b>é o prompt inteiro</b> do reprocessamento, e ele fala da foto
da <b>direita</b>: peça o que quiser, inclusive o que o prompt padrão proíbe.
Uma foto marcada sem texto não roda.<br>
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
  {srv_bar}
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

// What the server writes, per file it writes. `payload()` is the same function
// "Copiar marcações" calls, so the two routes cannot drift.
const GATE_TEXT = {{ '{gate_file}': payload }};

// Shown in the confirmation dialog. A number would not do: with eight
// photographs going back, the mistake worth catching is a sentence written
// under the wrong one, and that is only visible as a list.
function srvSummary(name) {{
  const esc = s => String(s).replace(/[&<>]/g,
    c => ({{ '&':'&amp;', '<':'&lt;', '>':'&gt;' }}[c]));
  const back = boxes().filter(b => b.checked).map(b => {{
    const t = noteOf(b.dataset.key);
    return {{ k: b.dataset.key, n: t ? t.value.replace(/\\s+/g, ' ').trim() : '' }};
  }});
  if (!back.length) return '';
  return '<p>' + back.length + ' foto(s) voltam, cada uma com esta frase como ' +
    'prompt inteiro:</p><ol>' + back.map(x => '<li><code>' + esc(x.k) +
    '</code> <q>' + esc(x.n || '— sem texto, e sem texto ela não roda') +
    '</q></li>').join('') + '</ol>';
}}
{js}
</script>
"""
