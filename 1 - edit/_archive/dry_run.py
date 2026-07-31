"""Retired 2026-07-27 — the `--dry-run` flag pulled out of `enhance.py` and
`batch.py` after enough real jobs had run that a pre-flight cost/payload
preview stopped earning its keep. Nothing imports this file; it is not part
of the pipeline. Kept only so the removed code is still readable verbatim
instead of living solely in git history.

To bring a piece back: copy the relevant block below into the live file and
re-wire the `--dry-run` CLI flag.
"""

# ============================================================
# From enhance.py — CLI flag (in main()'s argparse setup)
# ============================================================
#
#     ap.add_argument("--dry-run", action="store_true",
#                     help="resolve everything and print the payload; submit nothing")
#
# ...and passed through:
#
#     run(Path(args.photo), model=args.model, dry_run=args.dry_run)


# ============================================================
# From enhance.py — run(), right after `payload` was built and
# before anything was uploaded or spent
# ============================================================

def enhance_dry_run_branch(payload, emit, json):
    """Verbatim body of the `if dry_run:` block that used to sit inside
    enhance.py's run(), right after the gpt-image / nano-banana payload
    dict was assembled. `payload` did not yet have `image_urls` — that key
    was only added right before `fal_client.subscribe`, once an upload had
    actually happened — so the dry run stood in a placeholder to show the
    request's shape without spending anything on an upload.
    """
    emit("--- dry run, nothing submitted ---")
    emit(json.dumps({**payload, "image_urls": ["<uploaded at run time>"]},
                    indent=2)[:2000])
    return None


# ============================================================
# From batch.py — CLI flag
# ============================================================
#
#     ap.add_argument("--dry-run", action="store_true",
#                     help="resolve sizes and cost for every photo; submit nothing")


# ============================================================
# From batch.py — main(), three effects `args.dry_run` had
# ============================================================

def batch_dry_run_effects_photos_selection(all_photos, is_done, args):
    """A dry run resolved every photo, not just the not-yet-done ones —
    otherwise re-running the preview on an already-finished job would show
    nothing."""
    return all_photos if (args.redo or args.dry_run) else [
        p for p in all_photos if not is_done(p)]


def batch_dry_run_effects_workers(args, photos):
    """A dry run forced a single worker — its console output exists purely
    to be read in order, so interleaving it across threads would defeat the
    point."""
    return 1 if args.dry_run else max(1, min(args.workers, len(photos)))


def batch_dry_run_effects_after_loop(args, job):
    """After the per-photo loop, a dry run stopped short of everything that
    makes a run real: no job.md entry, no move to `3 - completed/`, no
    index update."""
    if args.dry_run:
        print("--- dry run, nothing submitted and nothing moved ---")
        return True   # caller returned immediately
    return False
