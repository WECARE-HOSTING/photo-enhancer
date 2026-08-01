#!/usr/bin/env python3
"""Run the job waiting in `1 - edit/` through fal.ai, then stop and wait for you.

    ./_config/.venv/bin/python "1 - edit/batch.py"
    ./_config/.venv/bin/python "1 - edit/batch.py" --job Job_0023 --workers 6
    ./_config/.venv/bin/python "1 - edit/batch.py" --rework    # redo what you marked
    ./_config/.venv/bin/python "1 - edit/batch.py" --approve   # -> 2 - marca dagua/

One job at a time. It arrives from `0 - selection/develop.py` with its photos
already named — `SALA_01_0001.jpg` — and every result is written back into the
same folder under the same name plus `_edit`, so the job stays one bundle:
source, edit and log side by side. Nothing is renamed at this stage.

Photos run **concurrently**, `--workers` at a time; each is an independent
upload -> generate -> download chain that spends almost all its time waiting on
fal, so wall clock is set by how many run at once, not by their sum. Each
photo's output is buffered and printed as one block, so parallel runs stay
readable.

A photo that already has an `_edit.jpg` is skipped, which makes a re-run after a
partial failure a retry of just the failures. `--redo` overrides that.

**The job does not advance itself.** "The API answered" and "this is good enough
to send a client" are different questions and only the first one a script can
answer. So a finished run writes `review-edit.html` and stops:

    batch.py            phase 1 — every photo, one fixed prompt -> review-edit.html
    (look at it)        mark what is not good enough, write why, Copiar -> gate.txt
    batch.py --rework   phase 3 — only those, each with your sentence as the
                        entire prompt, editing the `_edit` and not the source
    batch.py --approve  you said yes -> 2 - marca dagua/

**Phase 3 is not phase 1 again.** `2 - retoque/retoque.py` sends the `_edit.jpg`
the human actually looked at, plus the original as a second reference, and their
sentence with no rules attached — `1 - edicao/PROMPT.md` is not read at all,
because the sentence exists precisely to override it.

That is why `--rework` deletes nothing, unlike every other rejection in this
project: the `_edit.jpg` is phase 3's **input**, and the `_log.md` holds the
original's CDN URL that saves uploading the photo a second time. The edit it
replaces is shelved as `_edit_rN.jpg`, and `--approve` discards those.

**A photo marked back with no sentence stops the run**, before anything is
recorded and before anything is spent — phase 3 *is* the sentence. Another draw
from the fixed prompt is `--redo`, which is phase 1 again.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "_config"))
import gate  # noqa: E402
import ledger  # noqa: E402
import paths  # noqa: E402
import review  # noqa: E402
import stage  # noqa: E402

# The two phases this script drives, each from its own folder. Imported by path
# rather than by a plain `import enhance` because the folder names have spaces and
# digits in them — `1 - edicao` is not a Python identifier.
sys.path.insert(0, str(paths.EDICAO_DIR))
sys.path.insert(0, str(paths.RETOQUE_DIR))
import enhance  # noqa: E402  — phase 1: the fixed PROMPT.md, every photo
import retoque  # noqa: E402  — phase 3: one free instruction, one photo

SUFFIX = "_edit"
STAGE = HERE.name

# How many photos are in flight at once. Each spends most of its time waiting on
# fal, so threads (not processes) are the right tool. 4 is comfortable; raise it
# if fal keeps up, lower it to spread cost over time.
WORKERS = 4


def process(photo: Path, model: str,
            instruction: str = "") -> "tuple[Path, str, str, list[str]]":
    """Run one photo through phase 1, or through phase 3 if it carries a sentence.

    Returns (photo, status, phase, its buffered output lines). Runs in a worker
    thread, so it must not print — lines go into a buffer the main thread prints
    as one block.

    The branch is the whole difference between the two phases: with no
    instruction, `enhance.run()` sends the source and the fixed prompt; with one,
    `retoque.run()` sends the *edit* plus the original and that sentence alone.
    """
    lines: "list[str]" = []
    try:
        if instruction:
            edit = stage.result_of(photo.parent, photo, SUFFIX)
            if edit is None:
                raise enhance.EnhanceError(
                    f"{photo.stem} tem comentário mas nenhum {SUFFIX}.jpg para "
                    "retocar — rode a fase 1 nela primeiro")
            retoque.run(photo, edit, instruction, model=model, emit=lines.append)
        else:
            enhance.run(photo, model=model, emit=lines.append)
    except enhance.EnhanceError as e:
        lines.append(f"FAILED      {e} — rode de novo para tentar esta de novo")
        return photo, "failed", e.phase, lines
    except Exception as e:              # noqa: BLE001 — one bad photo must not stop the job
        lines.append(f"FAILED      {type(e).__name__}: {e}")
        return photo, "failed", "before", lines
    return photo, "ok", "", lines


def resolve(job: Path) -> "tuple[list, list[str]]":
    """Parse `gate.txt` and normalise its keys to real source stems.

    Forgiving about what gets pasted — a bare stem, a filename, an `_edit.jpg`
    or a path all name the same photo. Anything that still resolves to nothing
    is handed back as unknown, because a line the human wrote and the script
    silently dropped is worse than a line it complains about.
    """
    path = job / gate.NAME
    if not path.exists():
        return [], []
    try:
        marks, bad = gate.parse(path)
    except ValueError as e:
        sys.exit(f"error: {e}")

    known = {p.stem for p in stage.photos_in(job)}
    resolved, unknown = [], list(bad)
    for m in marks:
        m.key = stage.strip_result(Path(m.key).stem)
        (resolved if m.key in known else unknown).append(m)
    return resolved, [getattr(u, "key", u) for u in unknown]


def read_gate(job: Path, required: bool) -> "tuple[list, list[str]]":
    """`resolve()`, but insisting the file exists and names something."""
    path = job / gate.NAME
    resolved, unknown = resolve(job)

    if required and not resolved:
        sys.exit(
            f"error: {paths.rel(path)} não nomeia nenhuma foto de {job.name}.\n"
            f"       Abra {job.name}/{review.NAME}, marque o que precisa "
            "refazer, clique\n       'Copiar marcações' e cole no arquivo, "
            "substituindo tudo (⌘A ⌘V ⌘S).")
    return resolved, unknown


def fold_gate(job: Path, marks: "list", approved: int) -> None:
    """Write the human's decisions into `gate.md` before anything is deleted."""
    n = gate.rounds_so_far(job, STAGE) + 1
    again = gate.repeats(job, STAGE, marks)      # ask before this round is written
    gate.fold(job, STAGE, n, marks, approved)

    back = [m for m in marks if m.back]
    commented = [m for m in marks if m.comment]
    ledger.append(paths.EDIT_DIR, job.name, "gate", len(back),
                  f"{len(back)} de volta, {len(commented)} comentada(s) · "
                  f"`{gate.RECORD}` rodada {n}")

    if again:
        print(f"\nnota        {len(again)} foto(s) já tinham voltado antes: "
              f"{', '.join(again[:4])}{' …' if len(again) > 4 else ''}\n"
              "            Uma foto que falha do mesmo jeito duas vezes é "
              "PROMPT.md, não outro run.\n            A correção lá vale para "
              "toda foto futura; o comentário vale só para esta.")


def write_review(job: Path, model: str, wall: str) -> Path:
    pairs, missing = stage.pairs_in(job, SUFFIX)
    # Resolved, not raw: the page looks marks up by the checkbox's data-key, so
    # a line pasted as `SALA_01_0001_edit.jpg` has to arrive here as the stem or
    # it silently pre-fills nothing.
    marks, _ = resolve(job)
    dest = review.write(job, pairs, model, wall, missing, marks)
    gate.ensure_stub(job, review.NAME, job.name)
    print(f"\npágina      {paths.rel(dest)}")
    print(f'  open      "{dest}"')
    print(f'  open -e   "{job / gate.NAME}"     # cole aqui (⌘A ⌘V ⌘S)')
    return dest


def approve(job: Path) -> None:
    """You said it is good. Check it is finished, record it, then move it on.

    The check is not second-guessing you — a photo with no edit has nothing to
    show and so never appeared on the page at all. Moving a job with a hole in
    it would put it beyond the stage that knows how to fill it.
    """
    pairs, missing = stage.pairs_in(job, SUFFIX)
    if missing:
        sys.exit(f"error: {len(missing)} foto(s) de {job.name} não têm resultado:\n"
                 f"       {', '.join(missing[:8])}{' …' if len(missing) > 8 else ''}\n"
                 "       Rode batch.py para fazê-las, depois aprove.")

    marks, unknown = read_gate(job, required=False)
    if unknown:
        print(f"nota        {len(unknown)} linha(s) de {gate.NAME} não nomeiam "
              f"foto deste trabalho e foram ignoradas: {', '.join(unknown[:4])}")
    back = [m for m in marks if m.back]
    if back:
        sys.exit(f"error: {gate.NAME} ainda marca {len(back)} foto(s) para "
                 f"refazer:\n       {', '.join(m.key for m in back[:8])}\n"
                 "       Rode --rework primeiro, ou apague essas linhas se "
                 "mudou de ideia.")

    # Record first, delete second, move third. Until this order existed, approve
    # unlinked the page and the rework list and *then* archived — destroying the
    # rejection history at the exact moment it became permanent.
    fold_gate(job, marks, approved=len(pairs))
    for scratch in (job / review.NAME, job / gate.NAME):
        if scratch.exists():
            scratch.unlink()
    # The shelved retouch versions go too. They exist so a human can choose
    # between rounds; once the job has moved there is nothing left to choose, and
    # `3 - completed/` would otherwise fill with 2K images nobody opens. Said out
    # loud, never silently — what happened stays in `gate.md` and each `_log.md`.
    shelved = stage.drop_shelved(job)
    if shelved:
        print(f"descartado  {shelved} versão(ões) anterior(es) de retoque "
              "(`_edit_rN.jpg`)")
    print(f"aprovado    {job.name} · {len(pairs)} foto(s)")
    stage.advance(job, paths.MARCA_DIR, paths.EDIT_DIR, len(pairs))
    print("\nAgora a marca d'água:\n  "
          + paths.cmd(paths.MARCA_DIR / "batch.py", "--job", job.name))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="job folder name (default: lowest-numbered waiting)")
    ap.add_argument("--model", default=enhance.DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"photos in flight at once (default {WORKERS})")
    ap.add_argument("--redo", action="store_true",
                    help="re-run photos that already have a result, overwriting it")
    ap.add_argument("--rework", action="store_true",
                    help=f"phase 3: read {gate.NAME} and retouch just the photos "
                         "it marks — each one's comment is the whole prompt, and "
                         "it edits the result, not the source")
    ap.add_argument("--approve", action="store_true",
                    help="you looked at the page and it is good — move the job on")
    args = ap.parse_args()

    paths.EDIT_DIR.mkdir(exist_ok=True)
    job = stage.find_job(paths.EDIT_DIR, args.job)
    all_photos = stage.photos_in(job)
    if not all_photos:
        sys.exit(f"error: {job.name} has no photos in it")

    if args.approve:
        approve(job)
        return

    instructions: "dict[str, str]" = {}
    if args.rework:
        marks, unknown = read_gate(job, required=True)
        if unknown:
            print(f"nota        {len(unknown)} linha(s) de {gate.NAME} não nomeiam "
                  f"foto de {job.name} e foram ignoradas: {', '.join(unknown[:4])}")
        back = [m for m in marks if m.back]

        # Refuse BEFORE fold_gate() and before anything is sent. A photo marked
        # with no sentence has nothing to send — phase 3 IS the sentence — and
        # folding first would write a round into gate.md that never happened.
        # gate.txt is left untouched so the marks survive to be written on.
        silent = [m.key for m in back if not m.comment]
        if silent:
            sys.exit(
                f"error: {len(silent)} foto(s) marcada(s) sem comentário:\n"
                f"       {', '.join(silent[:8])}{' …' if len(silent) > 8 else ''}\n"
                "       O que você escreve na caixa É a instrução inteira que a "
                "fase 3 manda —\n       sem ela não há o que pedir. Abra "
                f"{job.name}/{review.NAME}, escreva o porquê\n       de cada uma, "
                "copie e cole de novo.\n\n"
                "       Se você só quer outro sorteio com o prompt padrão, isso é "
                "--redo,\n       que refaz a foto do zero a partir da original.")

        fold_gate(job, marks, approved=len(all_photos) - len(back))
        # The sentences ride to the run below in memory. Nothing writes them
        # where a later run could read them back: a plain re-run is phase 1 with
        # PROMPT.md alone, which is the honest default.
        instructions = {m.key: m.comment for m in back}
        print(f"retoque     {len(back)} foto(s) de volta: "
              f"{', '.join(m.key for m in back[:4])}"
              f"{' …' if len(back) > 4 else ''}")
        # Nothing is deleted here, and that is the difference from every other
        # rejection in this project. The `_edit.jpg` is phase 3's INPUT, and the
        # `_log.md` carries the original's CDN URL that saves re-uploading it.
        # The previous edit is shelved as `_edit_rN.jpg` by retoque.run().

        # Reset the paste target now that its marks are recorded in gate.md and
        # acted on. Leaving them there was a dead end: the page pre-filled itself
        # with photos that had already been redone, and --approve refused forever
        # because the file still asked for a rework it had already had.
        (job / gate.NAME).unlink(missing_ok=True)

    if args.rework:
        # An explicit list, not the skip rule: phase 3's input is the `_edit.jpg`
        # that the skip rule would take as "already done". Only the marked photos
        # run, and each runs whether or not it has a result.
        marked = set(instructions)
        photos = [p for p in all_photos if p.stem in marked]
        skipped = 0
    else:
        photos = all_photos if args.redo else [
            p for p in all_photos if not stage.is_done(job, p, SUFFIX)]
        skipped = len(all_photos) - len(photos)

    if not photos:
        print(f"{job.name}: as {len(all_photos)} foto(s) já têm resultado — "
              "use --redo para rodá-las de novo")
        write_review(job, args.model, "sem run")
        print("\nQuando estiver bom:\n  "
              + paths.cmd(Path(__file__), "--approve", "--job", job.name))
        return

    workers = max(1, min(args.workers, len(photos)))
    print(f"\n{job.name} · {'retoque' if args.rework else 'edição'} · "
          f"{len(photos)} foto(s)"
          f"{f' ({skipped} já prontas, puladas)' if skipped else ''}"
          f" · {workers} por vez · {args.model}")

    t_start = time.time()
    tally = {"ok": 0, "failed": 0}
    billed = {"before": 0, "after": 0}
    errors: "list[str]" = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, p, args.model,
                               instructions.get(p.stem, "")): p
                   for p in photos}
        for n, future in enumerate(as_completed(futures), 1):
            photo, status, phase, lines = future.result()
            tally[status] += 1
            if status == "failed":
                billed[phase] += 1
                errors.append(next((l.split(None, 1)[1] for l in lines
                                    if l.startswith("FAILED")), "?"))
            print(f"\n--- {photo.name}  [{n}/{len(photos)}] ---")
            for line in lines:
                print(line)

    elapsed = time.time() - t_start
    wall = f"{elapsed:.0f}s" if elapsed < 90 else f"{elapsed / 60:.1f} min"
    # Where a failure died says whether it was billed. At 2am, after two
    # failures in a batch of sixty, "did I pay for 60 or for 62" is a real
    # question and nobody opens sixty log files to answer it.
    where = (f" ({billed['before']} antes do envio, {billed['after']} depois)"
             if tally["failed"] else "")
    summary = f"{tally['ok']} ok · {tally['failed']} falhas{where} · {wall}"
    print(f"\n=== {job.name}: {summary} ({elapsed / len(photos):.1f}s por foto) ===")

    phase = "retoque" if args.rework else "edição"
    stage.log_run(job, [f"Phase: {'3 — retoque' if args.rework else '1 — edição'}",
                        f"Model: `{args.model}`", f"Result: {summary}"])
    # One ledger for the whole stage, and the phase rides in the **detail** — the
    # event stays `run`. `ledger.EVENTS` is a closed set, identical in all four
    # stages so that `grep '| run |' */ledger.md` means one thing everywhere; a
    # stage-specific sixth word would be the drift it exists to prevent. Nor one
    # ledger per phase: `grep -n "Job_0023" */ledger.md` is a job's life *in
    # order*, which is the only reason the file exists.
    ledger.append(paths.EDIT_DIR, job.name,
                  f"run {gate.rounds_so_far(job, STAGE) + 1}", len(photos),
                  f"{phase} · {summary} · `{args.model}`")
    write_review(job, args.model, wall)
    paths.notify(f"{job.name} — {'retoque' if args.rework else 'edição'}", summary)

    if tally["failed"]:
        whole = stage.failure_summary(errors)
        print(f"\naviso       {whole}" if whole else
              f"\n{tally['failed']} foto(s) falharam — rode de novo para tentar "
              "só essas.\nA página acima mostra as que deram certo.")
        return

    print("\nOlhe a página, e mande de volta o que errou:\n"
          f"  marque, 'Copiar marcações', cole em {job.name}/{gate.NAME}, e\n  "
          + paths.cmd(Path(__file__), "--rework", "--job", job.name)
          + "\n\nou aprove, que é a única coisa que move o trabalho adiante:\n  "
          + paths.cmd(Path(__file__), "--approve", "--job", job.name))


if __name__ == "__main__":
    main()
