Professional real estate listing enhancement: edit this exact photograph — same space, same layout, same vantage, same time of day, never recreate the scene. Every object in the result already exists in the source photograph. Bare surfaces stay bare.

Light: balance the interior's exposure like a bracketed HDR merge of the room itself — recover burnt highlights on walls, floors, and fixtures, lift shadows, keep blacks rich and neutral white balance. Window and door glass is outside that recovery and follows its own rule below.

Planting already present renders green and healthy, same layout.

Surfaces' Reflections: identify reflections on any opaque surface and remote it, keeping the original surfaces shiny. Window and door glass is the exception: the glass keeps every reflection the source already shows on it, unchanged.

Reframe for composition from the same vantage, keeping everything the source shows. Widened margins continue the surfaces already meeting that edge, in the same material.

Lighting Scheme : explore only existing lighting hardware to use it.

Apply Rule of Thirds, symmetry, level horizon, headroom to balance negative space.

Staging, with only what is already in frame: keep whatever shows what the property offers — the appliances and equipment that prove it is provisioned stay — cleaned and squared, every cord removed end to end with the device it serves left in place;

Remove whatever belongs to the resident or serves only upkeep — anything dropped on the floor, toiletries, papers, cleaning supplies, empty racks and dispensers. Keep it tight.

Chairs may be tucked and squared.

Beds and sheets: make beds, pristine pressed bedsheets and all textiles, level frames. Organize pillows to same height.

Curtains pressed

TVs and projectors already visible in the source display a Netflix home screen. Dark panels and unlit walls stay flat painted surfaces.

Window views: whatever the glass shows in the source is all the glass ever shows. A shape already photographed through a pane keeps its own outline, position and size, and may only have its colour cast and haze cleaned — it never becomes sharper, more detailed or larger than the source rendered it. A pane the source blew out keeps its flat bright wash, with no shape resolving inside it. No sky, cloud, sun, horizon, tree, garden, lawn, hill, mountain, beach, ocean, pool, street, car, building or city view is drawn beyond a pane where the source did not already photograph it. Any doubt about what lies outside a window resolves to that flat bright wash, never to a view. Frames, mullions, glazing bars and sills stay straight, rectangular and sharp.

Documents: any document, page, contract, form or certificate visible in the source stays exactly where it is, same size, same angle, same hand on it. Its printed and handwritten text renders as a soft out-of-focus blur — the shape of lines and paragraphs with no readable letter, word, name or number anywhere, as if that page alone were photographed at shallow depth of field. Letterheads, stamps, logos and signatures blur the same way. Everything else in the photograph stays tack sharp.

People, hands and vehicles: every person, hand, arm and sleeve already in the source stays — same position, same pose, same clothing, never erased or replaced by empty surface. A hand resting on a document, page, table or handle stays exactly where it rests, holding exactly what it holds. Render hands and fingers with correct anatomy: five fingers, natural joints, correct skin tone, no fusing, no extra digits. Vehicles already in the source stay too.

===== END OF PROMPT — everything below is NOT sent to the model =====

## This file governs phase 1 only

Every photo of a job, same text, no exceptions. **Phase 3 does not read it.**
When you send a photo back at the gate with a comment, `2 - retoque/` runs it
again with your sentence alone — the whole point of that phase is to override
rules written here, one photo at a time. So a rule added here is a rule for
every future photo, and a gate comment is a rule for exactly one.

## fal.ai request settings

What `enhance.py` sends alongside the text above, on every run. These are read
from the constants at the top of `../../_config/fal.py`, not from this file —
this list is here so you can check them in the same place you edit the prompt.
Change the constant in `fal.py` if one of these needs to change; it is shared
with phase 3, so a change lands on both.

| Setting          | Value                                                              | Constant             |
| ---------------- | ------------------------------------------------------------------ | -------------------- |
| Model            | `openai/gpt-image-2/edit`                                        | `DEFAULT_MODEL`    |
| Quality          | `medium`                                                         | `QUALITY`          |
| Image size       | matched to the source's exact aspect ratio                         | `TARGET_LONG_EDGE` |
| Upload long edge | source downscaled to 2048px before upload (speed, no quality loss) | `UPLOAD_LONG_EDGE` |
| Output format    | `jpeg`                                                           | —                   |
| Number of images | `1`                                                              | `NUM_IMAGES`       |
| fal.ai API key   | `FAL_KEY` in `.env` (never in this file, never in the prompt)  | —                   |

**The marker line above is load-bearing.** `enhance.py` splits on
`===== END OF PROMPT` and sends only what precedes it. If you edit this file,
leave that line in place — the script fails loudly rather than sending this
table to the model as prompt text.
