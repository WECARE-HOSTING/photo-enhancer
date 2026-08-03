#!/usr/bin/env python3
"""Phase 3 — one photo, one sentence the human wrote, no rules attached.

    ./_config/.venv/bin/python "1 - edit/2 - retoque/retoque.py" \\
        "1 - edit/Job_0023/SALA_01_0001.jpg" "põe a pessoa da janela de volta"

Normally driven by `1 - edit/batch.py --rework`, which reads the sentences out of
`gate.txt`. The CLI above exists for trying one by hand.

**It edits the result, not the source.** The human judged `SALA_01_0001_edit.jpg`
and wrote about *that* image, so that is image 1 — the photograph being edited. The
original goes along as image 2, reference only, for recovering how a detail really
looked. Editing the source instead would throw away everything phase 1 got right
and re-roll it, which is what this phase did until 2026-08-01.

**The original is not uploaded again.** Phase 1 already put it on fal's CDN and
recorded the URL in `<name>_log.md`; this reads it back, confirms with a HEAD that
it still serves, and reuses it. Only if that fails does it upload the file. Which is
why `--rework` must never delete a log: it is no longer just a record, it is input.

**`PROMPT.md` here is three sentences of addressing, and phase 1's PROMPT.md is not
read at all.** The human's text is the instruction; the frame only tells the model
which image is which and that image 1's differences from image 2 were deliberate.
See `PROMPT.md` below its marker for why even that much is needed.

**The previous edit is kept.** Before the new result takes the `_edit.jpg` name, the
old one is shelved as `_edit_r1.jpg`, `_edit_r2.jpg`… so a retouch that fixes what
you asked but breaks something else costs a rename to undo, not another run. They
are discarded when you approve the job.

**The log is appended to, never rewritten.** Phase 1's header — and the source URL
in it — has to survive every retouch, and the file is the honest history of what was
asked of this photograph and when.

**And it is read back twice.** `recorded_source_url()` takes the original's CDN URL
out of phase 1's block; `history()` takes every retouch's sentence out of the blocks
below it, so `review-edit.html` can show you what you asked next to what came back.
That makes the block a format with two readers, not just a record: change a row
label here and change it in `history()` in the same commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_config"))
import fal  # noqa: E402
import ledger  # noqa: E402  — for cell(): a `|` in a sentence would end the row
import paths  # noqa: E402
import stage  # noqa: E402

from PIL import Image  # noqa: E402

PROMPT_PATH = HERE / "PROMPT.md"
PROMPT_END_MARKER = "===== END OF PROMPT"

DEFAULT_MODEL = fal.DEFAULT_MODEL
EnhanceError = fal.EnhanceError
fail = fal.fail

# The one line this script parses out of another script's output. Phase 1 writes
# it (`1 - edicao/enhance.py`, SOURCE_URL_LABEL); change the wording there and the
# original silently starts being uploaded a second time on every retouch — which
# still works, just slower. See `_dependencies.md`.
SOURCE_URL_RE = re.compile(r"^\|\s*Uploaded source\s*\|\s*(\S+)\s*\|", re.M)

# Counts how many retouches a log already records, so the next block is numbered.
ROUND_RE = re.compile(r"^## Retoque (\d+) ", re.M)

# The heading of one retouch block, and the rows inside it. `history()` reads
# both back — which is what turns the block below from a record into a format
# with a second reader. Deliberately loose about the dash and the spacing: these
# files are hand-editable and a page with one gap beats a page that will not draw.
BLOCK_RE = re.compile(r"^## Retoque (\d+)\b[ \t]*[—–-]?[ \t]*(.*)$", re.M)
ROW_RE = re.compile(r"^\|([^|]+)\|(.*)\|[ \t]*$", re.M)


@dataclass
class Round:
    """One retouch, as its own log recorded it."""
    n: int
    when: str                 # ISO stamp from the heading, or ""
    instruction: str          # the sentence the human wrote — the whole prompt
    previous: str = ""        # "SALA_01_0001_edit_r1.jpg": the edit this replaced
    result: str = ""          # the file it wrote, normally "<stem>_edit.jpg"
    model: str = ""


def _bare(cell: str) -> str:
    """A table cell as text: backticks off, an em-dash placeholder as empty."""
    text = cell.strip().strip("`").strip()
    return "" if text in {"—", "-", ""} else text


def history(log: "Path") -> "list[Round]":
    """Every retouch this photograph has had, oldest first, out of its own log.

    `[]` when the log has no retouch block, is missing, or is unreadable. This is
    drawn on `review-edit.html` next to the photograph so you can check what you
    asked against what came back — a page that refuses to render because one log
    was hand-edited would be worse than a page with a hole in it, so nothing in
    here raises.

    The second reader of `<stem>_log.md`, after `recorded_source_url()`. See
    `_dependencies.md`.
    """
    try:
        if not log.exists():
            return []
        raw = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    heads = list(BLOCK_RE.finditer(raw))
    out: "list[Round]" = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(raw)
        body = raw[head.end():end]
        # Everything after the "### Prompt as sent" fence is the prompt verbatim,
        # which may itself contain pipes and headings. Stop at the first one.
        body = body.split("\n### ", 1)[0]

        got = {}
        for row in ROW_RE.finditer(body):
            label = row.group(1).strip().lower()
            # Rejoin: a `|` typed inside a sentence used to be written raw, and
            # splitting on every pipe would truncate the instruction at it.
            got.setdefault(label, row.group(2).strip())

        out.append(Round(
            n=int(head.group(1)),
            when=head.group(2).strip(),
            instruction=_bare(got.get("instrução humana", "")),
            previous=_bare(got.get("edit anterior", "")),
            result=_bare(got.get("resultado", "").split("·")[0]),
            model=_bare(got.get("model", "")),
        ))
    out.sort(key=lambda r: r.n)
    return out


def load_frame() -> "tuple[str, str]":
    """The addressing text above the marker, and its 8-char fingerprint.

    Re-read per photo, like phase 1's prompt: this file is a tuning surface and an
    edit should land on the next photo without restarting anything. The fingerprint
    goes into every retouch block, so "which framing produced this" stays
    answerable after you have rewritten it.
    """
    if not PROMPT_PATH.exists():
        fail(f"no prompt file at {PROMPT_PATH}")
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    if PROMPT_END_MARKER not in raw:
        fail(f"2 - retoque/PROMPT.md is missing its '{PROMPT_END_MARKER}' marker "
             "line. Without it these notes would be sent to the model as prompt "
             "text. Put the marker back before running.")
    frame = raw.split(PROMPT_END_MARKER, 1)[0].strip()
    if not frame:
        fail("2 - retoque/PROMPT.md has nothing above its marker. The model needs "
             "at least one sentence saying which image is which.")
    return frame, hashlib.sha256(frame.encode("utf-8")).hexdigest()[:8]


def recorded_source_url(log: Path) -> str:
    """The original's fal CDN URL, out of phase 1's log. `""` if it isn't there.

    Takes the **first** match on purpose: phase 1's block is at the top and its
    URL is the original photograph. A later retouch block may record a re-upload,
    which is the same image but not the authoritative row.
    """
    if not log.exists():
        return ""
    found = SOURCE_URL_RE.search(log.read_text(encoding="utf-8"))
    return found.group(1) if found else ""


def next_round(log: Path) -> int:
    """Which retouch this is, counted from the log itself rather than from state."""
    if not log.exists():
        return 1
    rounds = [int(n) for n in ROUND_RE.findall(log.read_text(encoding="utf-8"))]
    return max(rounds) + 1 if rounds else 1


def original_reference(source: Path, log: Path, emit) -> "tuple[str, str]":
    """(url, how we got it) for the original, reusing phase 1's upload if it lives.

    A HEAD costs ~200ms against a ~4s upload, and the cost of assuming wrong is a
    request that reaches the model with a broken reference and is billed anyway.
    """
    known = recorded_source_url(log)
    if known and fal.url_alive(known):
        emit(f"original    reaproveitada do log · {known}")
        return known, "reaproveitada do log"

    why = "log não tem a URL" if not known else "a URL do log não responde mais"
    emit(f"original    {why} — reenviando {source.name}")
    data, mime_type, _, _, sent = fal.prepare_upload(source)
    url = fal.upload(data, mime_type,
                     file_name=f"photo{'.jpg' if sent else source.suffix or ''}")
    return url, f"reenviada ({why})"


def run(source: Path, edit: Path, instruction: str,
        model: str = DEFAULT_MODEL, emit=print) -> Path:
    """Retouch one photo. Returns the path of the new `_edit`.
    Raises EnhanceError on failure.

    `source` is the original — it names everything (`<stem>_edit.jpg`,
    `<stem>_log.md`) and is the fallback reference upload. `edit` is the image the
    human actually looked at and is what gets edited. `instruction` is their
    sentence, sent verbatim.
    """
    t_start = time.time()
    instruction = (instruction or "").strip()
    if not instruction:
        fail("a retouch with no instruction has nothing to send. "
             "Write why the photo is coming back, or re-run phase 1 with --redo.")
    if not edit.exists():
        fail(f"no edit to retouch at {paths.rel(edit)} — run phase 1 first")

    job = source.parent
    stem = source.stem
    log = job / f"{stem}_log.md"
    frame, frame_id = load_frame()
    prompt = f"{frame}\n\n{instruction}"

    upload_bytes, mime_type, edit_w, edit_h, sent_size = fal.prepare_upload(edit)

    emit(f"retoque     {edit.name}  {edit_w}x{edit_h}")
    emit(f"instrução   {instruction}")
    emit(f"prompt      {PROMPT_PATH.name} #{frame_id} + a sua frase  "
         f"({len(prompt)} chars)")
    emit(f"model       {model}")

    # image_size comes from the edit, not the source: the edit is already ~2K at
    # the source's aspect ratio, and measuring it means the source file never has
    # to be opened when its URL is reused.
    payload, setting_line = fal.payload_for(model, prompt, edit_w, edit_h,
                                            num_images=1)
    emit(setting_line)

    fal.require_key()
    import fal_client

    t = time.time()
    edit_url = fal.upload(upload_bytes, mime_type, file_name="edit.jpg")
    original_url, how = original_reference(source, log, emit)
    t_upload = time.time() - t

    # Order is the contract with PROMPT.md: image 1 is the one being edited,
    # image 2 is the original. Swap these and the frame text describes the wrong
    # picture, which is worse than sending no frame at all.
    payload["image_urls"] = [edit_url, original_url]
    emit(f"uploaded    {t_upload:.1f}s · 2 imagens")

    t = time.time()
    try:
        result = fal_client.subscribe(model, arguments=payload, with_logs=False)
    except Exception as e:              # noqa: BLE001 — the request left; it may have billed
        fail(f"{type(e).__name__}: {e}", phase="after")
    t_generate = time.time() - t
    emit(f"generated   {t_generate:.1f}s")

    images = result.get("images") or []
    if not images:
        fail(f"no image in response: {json.dumps(result)[:500]}", phase="after")

    # Download to a name of its own first, and only then shelve the old edit and
    # take its place. The destination *is* the image that was just uploaded as
    # input, so a failed download must not be able to leave the job with no
    # `_edit.jpg` at all. Both renames are atomic; the window is microseconds.
    t = time.time()
    scratch = job / f"{stem}_edit.new.jpg"
    try:
        fal.download(images[0]["url"], scratch)
        with Image.open(scratch) as out:
            out_w, out_h = out.size
        # `current=edit` and not a fresh lookup: `result_of()` prefers
        # `_edit.jpg` over `_edit_1.jpg`, so on a job holding both it would shelve
        # one file while the line below overwrites the other — losing the new
        # result's predecessor and keeping a stale copy of an unrelated one.
        shelved = stage.shelve_result(job, source, "_edit", current=edit)
        scratch.replace(edit)
    finally:
        scratch.unlink(missing_ok=True)
    t_download = time.time() - t
    t_total = time.time() - t_start

    emit(f"guardado    {paths.rel(shelved)}" if shelved else
         "guardado    (não havia edit anterior para guardar)")
    emit(f"saved       {paths.rel(edit)}  {out_w}x{out_h}")

    n = next_round(log)
    block = [
        "", f"## Retoque {n} — "
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
        "| | |", "|---|---|",
        # `cell()` for the same reason gate.md uses it: a `|` in the sentence
        # ends the row early. It was harmless while nothing read this back;
        # `history()` reads it back, so the sentence on the page would be the
        # sentence up to the first pipe. The prompt fence below stays verbatim.
        f"| Instrução humana | {ledger.cell(instruction)} |",
        f"| Imagem editada | `{edit.name}` · {edit_w}×{edit_h} "
        f"· {len(upload_bytes) / 1e6:.2f} MB |",
        f"| Original de referência | {original_url} · {how} |",
        f"| Model | `{model}` |",
        f"| Prompt | `2 - retoque/PROMPT.md` #{frame_id} + a instrução "
        f"· {len(prompt)} chars |",
    ]
    block += fal.settings_row(model, payload, edit_w, edit_h)
    block += [
        f"| Edit anterior | {f'`{shelved.name}`' if shelved else '—'} |",
        f"| Timing | {t_total:.0f}s total — upload {t_upload:.1f}s · generate "
        f"{t_generate:.0f}s · download {t_download:.1f}s |",
        f"| Resultado | `{edit.name}` · {out_w}×{out_h} · "
        f"[fal url]({images[0]['url']}) |",
    ]
    if result.get("description"):
        block += ["", f"### Model description of retouch {n}", "",
                  f"> {result['description']}"]
    block += ["", f"### Prompt as sent (retoque {n})", "", "```", prompt, "```", ""]

    if not log.exists():
        # Phase 1's log was deleted by hand. Start one rather than lose the record
        # of what was just asked — the source URL is gone either way.
        log.write_text(f"# {stem} — Generation Log\n\n_Phase 1's block is missing "
                       "from this file; what follows starts at the first retouch "
                       "recorded here._\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block) + "\n")
    emit(f"logged      {paths.rel(log)} · retoque {n}")
    emit(f"done        {t_total:.0f}s total")
    return edit


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", help="the SOURCE photo, e.g. "
                                  "'1 - edit/Job_0023/SALA_01_0001.jpg'")
    ap.add_argument("instruction", help="what to change, in your own words")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    source = Path(args.photo)
    if not source.is_absolute():
        source = (paths.ROOT / source).resolve()
    edit = stage.result_of(source.parent, source, "_edit")
    if edit is None:
        sys.exit(f"error: {source.name} has no `_edit.jpg` to retouch — "
                 "run phase 1 on it first.")

    try:
        run(source, edit, args.instruction, model=args.model)
    except EnhanceError as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ninterrupted — nothing changed for this photo")
    except Exception as e:              # noqa: BLE001 — a clean message beats a traceback
        sys.exit(f"error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
