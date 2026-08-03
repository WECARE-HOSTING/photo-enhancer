#!/usr/bin/env python3
"""Put the WeCare mark on the job waiting in `2 - marca dagua/`, then wait for you.

    ./_config/.venv/bin/python "2 - marca dagua/batch.py"
    ./_config/.venv/bin/python "2 - marca dagua/batch.py" --rebrand   # redo all, free
    ./_config/.venv/bin/python "2 - marca dagua/batch.py" --rework    # redo what you marked
    ./_config/.venv/bin/python "2 - marca dagua/batch.py" --approve   # -> 3 - completed/

Reads each `<name>_edit.jpg` and writes `<name>_final.jpg` beside it. The API's
output is never touched, which is the whole reason this stage is cheap to be
wrong in: **nothing here calls fal.ai, nothing here costs money, and re-running
it is free and instant.** If the mark is too big, edit a constant in `marca.py`
and run `--rebrand`.

Serial, not threaded. Stage 1 is network-bound and wants four photos in flight;
this is pure Pillow on the CPU, where threads buy nothing and only make the
output interleave.

A photo is re-marked when its `_final` is missing, older than its `_edit`, or
older than the logo file itself — so replacing the PNG in `_config/logos/`
re-marks the whole job on the next run, for free, without anyone remembering to
ask for it.

    batch.py            mark them -> review-marca.html
    (look at it)        the 1:1 crop is the point; mark what is wrong, force the
                        ink if you want, Copiar -> gate.txt
    batch.py --rework   redoes just those, honouring the override
    batch.py --approve  -> 3 - completed/, with originais/ built alongside
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "_config"))
import gate  # noqa: E402
import ledger  # noqa: E402
import marca  # noqa: E402
import paths  # noqa: E402
import review  # noqa: E402
import serve  # noqa: E402
import stage  # noqa: E402

# originais/ has to be assembled before the job moves, and the code that knows
# how lives with the archive. Through paths.py like every other stage path.
sys.path.insert(0, str(paths.COMPLETED_DIR))
import archive  # noqa: E402

SUFFIX = marca.SUFFIX          # "_final"
SOURCE = marca.SOURCE_SUFFIX   # "_edit"
STAGE = HERE.name
RECORD = "marca.md"


def logo_mtime() -> float:
    return max(p.stat().st_mtime for p in (marca.LOGO_DARK_INK, marca.LOGO_LIGHT_INK)
               if p.exists())


def needs_mark(job: Path, photo: Path, since: float) -> bool:
    """Missing, stale against its own `_edit`, or older than the logo art."""
    final = stage.result_of(job, photo, SUFFIX)
    if not final:
        return True
    edit = stage.result_of(job, photo, SOURCE)
    if not edit:
        return False                       # nothing to make it from; reported elsewhere
    return final.stat().st_mtime < max(edit.stat().st_mtime, since)


def check_logos() -> None:
    """Fail before doing anything if the art is not there or not readable."""
    try:
        marca.inks()
    except marca.MarcaError as e:
        sys.exit(f"error: {e}")


def resolve(job: Path) -> "tuple[list, list[str]]":
    path = job / gate.NAME
    if not path.exists():
        return [], []
    try:
        marks, bad = gate.parse(path)
    except ValueError as e:
        sys.exit(f"error: {e}")
    known = {p.stem for p in stage.photos_in(job)}
    ok, unknown = [], list(bad)
    for m in marks:
        m.key = stage.strip_result(Path(m.key).stem)
        (ok if m.key in known else unknown).append(m)
    return ok, [getattr(u, "key", u) for u in unknown]


def facts_for(job: Path, photos: "list[Path]",
              overrides: "dict[str, dict] | None" = None) -> "dict[str, dict]":
    """Measure every photo that has an `_edit`, without writing anything.

    Measured fresh rather than read out of `marca.md`, because nothing in this
    project reads a log to decide anything — and measuring is deterministic and
    costs milliseconds.

    `overrides` matters: measuring with none would report the *auto* ink for a
    photo whose `_final` was deliberately forced to the other one, so the gate
    page's badge would contradict the pixels next to it and the radio above it.
    """
    overrides = overrides or {}
    out = {}
    for p in photos:
        edit = stage.result_of(job, p, SOURCE)
        if not edit:
            continue
        o = overrides.get(p.stem, {})
        try:
            out[p.stem] = marca.run(
                edit, write=False, variant=o.get("variant"),
                glow={"on": True, "off": False}.get(o.get("glow")))
        except marca.MarcaError:
            pass
    return out


def write_record(job: Path, facts: "dict[str, dict]") -> None:
    """`marca.md` — one row per photo, one file per job.

    Deliberately not a `<name>_wm_log.md` per photo, the way stage 1 does it.
    That file exists there because every fal call is remote, unique, billed and
    unreproducible. This is local, free, deterministic and identical across the
    whole job: fifty files each repeating the same six settings would be fifty
    copies of one fact.
    """
    rows = ["| Foto | Tinta | Contraste | Glow | Caixa | Fundo |",
            "|---|---|---|---|---|---|"]
    for stem in sorted(facts):
        f = facts[stem]
        mx, my, lw, lh = f["box"]
        rows.append(
            f"| `{stem}` | {f['variant']} | {f['contrast']:.2f}:1 | "
            f"{f['reason'] or '—' if f['glow'] else 'não'} | "
            f"{lw}×{lh} @ {mx} | L {f['L']:.3f} · σ {f['std']:.3f} |")

    (job / RECORD).write_text(
        f"# {job.name} — marca d'água\n\n"
        f"_Uma linha por foto. Escrito por `{STAGE}/batch.py`; nada lê de "
        "volta._\n\n"
        f"| | |\n|---|---|\n"
        f"| Arte | `{marca.LOGO_DARK_INK.name}` · `{marca.LOGO_LIGHT_INK.name}` |\n"
        f"| Tamanho | {marca.LOGO_HEIGHT_PCT:.1%} do lado maior (altura) · margem "
        f"{marca.MARGIN_PCT:.0%} · opacidade {marca.OPACITY:.0%} |\n"
        f"| Glow quando | contraste < {marca.MIN_CONTRAST} ou desvio > "
        f"{marca.BUSY_STD} |\n\n" + "\n".join(rows) + "\n",
        encoding="utf-8")


def fold_gate(job: Path, marks: "list", approved: int) -> None:
    n = gate.rounds_so_far(job, STAGE) + 1
    gate.fold(job, STAGE, n, marks, approved)
    back = [m for m in marks if m.back]
    ledger.append(paths.MARCA_DIR, job.name, "gate", len(back),
                  f"{len(back)} para refazer, "
                  f"{sum(1 for m in marks if m.comment)} comentada(s) · "
                  f"`{gate.RECORD}` rodada {n}")


def write_review(job: Path, wall: str,
                 overrides: "dict[str, dict] | None" = None) -> Path:
    photos = stage.photos_in(job)
    facts = facts_for(job, photos, overrides)
    trios, missing = [], []
    for p in photos:
        edit = stage.result_of(job, p, SOURCE)
        final = stage.result_of(job, p, SUFFIX)
        if edit and final and p.stem in facts:
            trios.append((edit, final, facts[p.stem]))
        else:
            missing.append(p.stem)
    marks, _ = resolve(job)
    dest = review.write(job, trios, wall, missing, marks)
    gate.ensure_stub(job, review.NAME, job.name)
    print(f"\npágina      {paths.rel(dest)}")
    print(f'  open      "{dest}"')
    print(f'  open -e   "{job / gate.NAME}"     # cole aqui (⌘A ⌘V ⌘S)')
    return dest


def gate_actions(job: Path) -> "dict[str, serve.Action]":
    """The buttons `review-marca.html` gets when a server is behind it.

    Free stage, so no money warning — but `--no-serve` still rides on every
    command that re-invokes this script, for the same reason as everywhere else.
    """
    me = Path(__file__).resolve()
    job_args = ("--job", job.name, "--no-serve")
    return {a.name: a for a in (
        serve.Action("save_gate", f"Salvar em {gate.NAME}", writes=gate.NAME,
                     note="grava as marcações e para aí"),
        serve.Action("rework", "Refazer as marcadas", writes=gate.NAME,
                     script=me, args=("--rework", *job_args), tone="bad",
                     note="re-marca só as marcadas, honrando a tinta forçada — "
                          "local e de graça"),
        serve.Action("rebrand", "Re-marcar todas", script=me,
                     args=("--rebrand", *job_args),
                     note="refaz a marca em todas — o laço para afinar tamanho "
                          "e posição, sem custo"),
        serve.Action("approve", "Aprovar e arquivar", writes=gate.NAME,
                     script=me, args=("--approve", *job_args), tone="go",
                     note="monta originais/ e arquiva em 3 - completed/",
                     outcome="ends_session", needs_clean=True),
    )}


def serve_gate(job: Path, allowed: bool, photos: int) -> None:
    """Hand the page to a local server, and wait there until Ctrl-C."""
    if not serve.enabled(allowed):
        return
    serve.run(root=job, page=review.NAME, actions=gate_actions(job),
              title=job.name, counts={"fotos": photos})


def approve(job: Path) -> None:
    """You said the mark is right. Record it, assemble originais/, archive it."""
    photos = stage.photos_in(job)
    missing = [p.stem for p in photos if not stage.result_of(job, p, SUFFIX)]
    if missing:
        sys.exit(f"error: {len(missing)} foto(s) de {job.name} não têm marca:\n"
                 f"       {', '.join(missing[:8])}{' …' if len(missing) > 8 else ''}\n"
                 "       Rode batch.py — é grátis — e depois aprove.")

    marks, unknown = resolve(job)
    if unknown:
        print(f"nota        {len(unknown)} linha(s) de {gate.NAME} não nomeiam "
              f"foto deste trabalho: {', '.join(unknown[:4])}")
    back = [m for m in marks if m.back]
    if back:
        sys.exit(f"error: {gate.NAME} ainda marca {len(back)} foto(s) para "
                 f"refazer:\n       {', '.join(m.key for m in back[:8])}\n"
                 "       Rode --rework primeiro (é grátis), ou apague essas linhas.")

    # Record, then assemble, then delete scratch, then move. A crash leaves a
    # recorded decision with unfinished work — recoverable — rather than
    # finished work with no record of who approved it.
    fold_gate(job, marks, approved=len(photos))
    archive.build_originais(job)
    for scratch in (job / review.NAME, job / gate.NAME):
        if scratch.exists():
            scratch.unlink()
    print(f"aprovado    {job.name} · {len(photos)} foto(s)")
    dest = stage.advance(job, paths.COMPLETED_DIR, paths.MARCA_DIR, len(photos))
    ledger.append(paths.COMPLETED_DIR, job.name, "entered", len(photos),
                  f"de `{paths.rel(paths.MARCA_DIR)}` · aprovado")
    archive.add_to_index(dest)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="job folder name (default: lowest-numbered waiting)")
    ap.add_argument("--rebrand", action="store_true",
                    help="re-mark every photo, overwriting. Free — this is the "
                         "loop for tuning the mark's size or position")
    ap.add_argument("--rework", action="store_true",
                    help=f"read {gate.NAME} and re-mark just what it names, "
                         "honouring any forced ink")
    ap.add_argument("--approve", action="store_true",
                    help="you looked at the page and it is good — archive it")
    ap.add_argument("--serve", action=argparse.BooleanOptionalAction, default=True,
                    help="hand the review page to a local server so its buttons "
                         "work, and wait there until Ctrl-C (default: yes). "
                         "--no-serve is what every button passes to the command "
                         "it launches, so a child never opens a second one")
    args = ap.parse_args()

    check_logos()
    paths.MARCA_DIR.mkdir(exist_ok=True)
    job = stage.find_job(paths.MARCA_DIR, args.job)
    photos = stage.photos_in(job)
    if not photos:
        sys.exit(f"error: {job.name} has no photos in it")

    if args.approve:
        approve(job)
        return

    overrides: "dict[str, dict]" = {}
    if args.rework:
        marks, unknown = resolve(job)
        if unknown:
            print(f"nota        {len(unknown)} linha(s) ignoradas: "
                  f"{', '.join(unknown[:4])}")
        back = [m for m in marks if m.back]
        if not back and not any(m.opts for m in marks):
            sys.exit(f"error: {gate.NAME} não marca nenhuma foto para refazer.")
        fold_gate(job, marks, approved=len(photos) - len(back))
        overrides = {m.key: m.opts for m in marks if m.back or m.opts}
        removed = stage.drop_results(job, [m.key for m in back], SUFFIX)
        print(f"rework      {len(back)} foto(s), {removed} arquivo(s) apagado(s)")
        # Same reason as stage 1: the marks are in gate.md now, and a stale
        # gate.txt would block --approve permanently.
        (job / gate.NAME).unlink(missing_ok=True)

    since = logo_mtime()
    todo = photos if args.rebrand else [
        p for p in photos
        if needs_mark(job, p, since) or p.stem in overrides]
    skipped = len(photos) - len(todo)

    if not todo:
        print(f"{job.name}: as {len(photos)} foto(s) já estão marcadas — "
              "use --rebrand para refazer todas")
        write_review(job, "sem run")
        print("\nQuando estiver bom:\n  "
              + paths.cmd(Path(__file__), "--approve", "--job", job.name))
        serve_gate(job, args.serve, len(photos))
        return

    print(f"\n{job.name} · {len(todo)} foto(s)"
          f"{f' ({skipped} já marcadas)' if skipped else ''} · sem API, sem custo")

    t_start = time.time()
    facts: "dict[str, dict]" = {}
    failed: "list[str]" = []

    for n, photo in enumerate(todo, 1):
        edit = stage.result_of(job, photo, SOURCE)
        if not edit:
            failed.append(f"{photo.stem}: sem {SOURCE}.jpg — voltou de "
                          f"{paths.rel(paths.EDIT_DIR)} incompleto?")
            continue
        o = overrides.get(photo.stem, {})
        try:
            f = marca.run(edit, emit=lambda s: print(f"  [{n}/{len(todo)}] {s}"),
                          variant=o.get("variant"),
                          glow={"on": True, "off": False}.get(o.get("glow")))
            facts[photo.stem] = f
        except marca.MarcaError as e:
            failed.append(f"{photo.stem}: {e}")
        except Exception as e:      # noqa: BLE001 — one truncated JPEG must not
            failed.append(f"{photo.stem}: {type(e).__name__}: {e}")
            # stop the other 59. Stage 1 already treats one bad photo this way;
            # here the whole batch is free to re-run, so failing soft costs
            # nothing and failing hard would strand the job mid-stage.

    # Photos marked this run keep their real facts; the rest are measured. The
    # `if k not in facts` is what stops a measurement without the override from
    # overwriting the truth of a photo that was just forced.
    facts |= {k: v for k, v in facts_for(job, photos, overrides).items()
              if k not in facts}
    write_record(job, facts)

    elapsed = time.time() - t_start
    wall = f"{elapsed:.1f}s"
    tally = {}
    for f in facts.values():
        tally[f["variant"]] = tally.get(f["variant"], 0) + 1
    summary = (f"{len(facts)} marcadas · {tally.get('escuro', 0)} preta · "
               f"{tally.get('claro', 0)} branca · "
               f"{sum(1 for f in facts.values() if f['glow'])} com glow · {wall}")
    if failed:
        summary += f" · {len(failed)} falhas"
    print(f"\n=== {job.name}: {summary} ===")
    for line in failed:
        print(f"FALHOU      {line}")

    stage.log_run(job, [f"Marca: {summary}"])
    ledger.append(paths.MARCA_DIR, job.name,
                  f"run {gate.rounds_so_far(job, STAGE) + 1}", len(todo), summary)
    write_review(job, wall, overrides)
    paths.notify(f"{job.name} — marca", summary)

    print("\nO recorte 1:1 na página é o que importa. Se algo estiver errado:\n"
          "  marque e aperte 'Refazer as marcadas' — ou, sem servidor:\n"
          f"  'Copiar marcações', cole em {job.name}/{gate.NAME}, e\n  "
          + paths.cmd(Path(__file__), "--rework", "--job", job.name)
          + "\n\nou aprove, que arquiva o trabalho:\n  "
          + paths.cmd(Path(__file__), "--approve", "--job", job.name))
    serve_gate(job, args.serve, len(photos))


if __name__ == "__main__":
    main()
