# WC-00660 - Casa MAD Alter — Ambientes

_Written by `0 - selection/cull.py` on 2026-07-31 02:49. Vocabulary `AMBIENTES.md` `#c2fe74fd`._

Which room every photograph in this shoot is of, and where that answer came from.
The name each picked photo is delivered under is built from this: `SALA` + room
`01` becomes `SALA_01_0001.jpg`.

**`Ambiente` and `Sala` are yours to correct.** Edit either, re-run `cull.py`, and
your value wins. Easier than editing this file by hand: change the room under a
photograph in `contact.html` and press **Copy ambientes.md**, which hands you this
whole file with the changed cells already rewritten — paste it back over this one.

- `Ambiente` is *what kind of room* it is. Correcting it turns `Origem` to
  `manual`, and that room is then never sent to the model again.
- `Sala` is *which room of that kind* — the `02` in `QUARTO_02_0001.jpg`. Change
  it to split one room into two, which is the only way to say that two bedrooms
  photographing alike are different bedrooms. Each half then gets its own quota.
  A number you do not touch is recomputed from the grouping, and numbering stays
  dense: write `05` into a shoot with two bedrooms and you get `QUARTO_02`.

  Changing `Ambiente` discards that row's `Sala`, because a room number only means
  something inside the ambiente it was handed out in — a photograph moved from
  `QUARTO_02` to `SALA` joins `SALA_01`, rather than inventing a `SALA_02`.

`Visto` is output, not input, and editing it does nothing useful. It is what the
last run's check actually saw, and it is how your `Ambiente` edit is recognised: a
run always writes `Visto` to whatever it just computed, so the two columns agree
unless *you* pulled them apart. Leave it alone and the difference keeps your
correction alive; overwrite it to match `Ambiente` and the next run will treat the
room as unsettled again, which is how you undo a correction.

The photo number is deliberately not here. The ambiente and the room are facts
about the photograph and are settled now; the number can only be handed out once
the picks are known, or it would arrive full of gaps where the unpicked photos
were. `develop.py` assigns it.

| Origem | Meaning |
|---|---|
| `filename` | The photographer's own label, mapped to the vocabulary and confirmed |
| `vision` | The model disagreed with the label, or there was no label to read |
| `manual` | You wrote it in this file |
| `keyword` | Mapped from the label, **not** confirmed — the vision pass did not run |

48 photo(s) — 45 `vision` · 3 `manual`

> **Not verified.** The vision pass did not run, so every ambiente below is a keyword guess from the filename. Re-run `cull.py` with a `FAL_KEY` in `_config/.env` to have them checked against the pictures.


| Ambiente         | Visto            | Sala | Rótulo do fotógrafo | Arquivo           | Origem | Nota                                                                                                                                                                                                                   |
|------------------|------------------|------|---------------------|-------------------|--------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| BANHEIRO         | BANHEIRO         | 01   | —                   | `IMG_7190.HEIC`   | vision | A imagem mostra uma pia com um espelho em um ambiente com paredes de madeira, caracterizando um banheiro.                                                                                                              |
| BANHEIRO         | BANHEIRO         | 01   | —                   | `IMG_9704.HEIC`   | vision | Ambiente com vaso sanitário, pia e bancada, caracterizando um banheiro.                                                                                                                                                |
| COZINHA          | COZINHA          | 01   | —                   | `IMG_9737.HEIC`   | vision | Ambiente com bancadas, armários, equipamentos de cozinha e área de preparo de alimentos.                                                                                                                               |
| FACHADA          | FACHADA          | 01   | —                   | `IMG_5851.HEIC`   | vision | A imagem mostra uma formação rochosa natural, não uma fachada de propriedade.                                                                                                                                          |
| FACHADA          | FACHADA          | 01   | —                   | `IMG_6402.HEIC`   | vision | A imagem mostra uma pessoa em uma praia com o mar ao fundo e um barco, não é possível identificar um ambiente específico da propriedade.                                                                               |
| FACHADA          | FACHADA          | 01   | —                   | `IMG_7075.HEIC`   | vision | A imagem mostra uma faixa de areia com vegetação e o mar ao fundo, não é possível identificar um ambiente específico da propriedade.                                                                                   |
| FACHADA          | FACHADA          | 01   | —                   | `IMG_8870.HEIC`   | vision | A imagem mostra uma praia com um barco e uma pessoa caminhando, não é possível identificar um ambiente específico da propriedade.                                                                                      |
| FACHADA          | FACHADA          | 01   | —                   | `IMG_8921.HEIC`   | vision | A imagem mostra uma pessoa sentada em uma faixa de areia com o mar ao fundo, não é possível identificar um ambiente específico da propriedade.                                                                         |
| FACHADA          | FACHADA          | 01   | —                   | `_O4A0203.JPG`    | vision | Vista externa da propriedade com a praia e o mar ao fundo.                                                                                                                                                             |
| JANTAR           | JANTAR           | 01   | —                   | `IMG_0577.HEIC`   | vision | A imagem mostra uma mesa posta com alimentos, sugerindo um ambiente de refeição.                                                                                                                                       |
| JANTAR           | JANTAR           | 01   | —                   | `IMG_0583.HEIC`   | vision | A imagem mostra uma mesa posta com alimentos e uma pessoa, sugerindo um ambiente de refeição.                                                                                                                          |
| JANTAR           | JANTAR           | 01   | —                   | `IMG_8953.HEIC`   | vision | A mesa posta com cadeiras sugere um local para refeições.                                                                                                                                                              |
| JARDIM           | JARDIM           | 01   | —                   | `IMG_2756.HEIC`   | vision | A imagem mostra uma pessoa em um ambiente aquático com vegetação e um barco ao fundo, não é possível identificar um cômodo específico da lista.                                                                        |
| JARDIM           | JARDIM           | 01   | —                   | `_O4A0633.JPG`    | vision | Pessoas em um lago com vegetação ao redor, sugerindo uma área de lazer natural.                                                                                                                                        |
| NAO_IDENTIFICADO | NAO_IDENTIFICADO | 01   | —                   | `IMG_0016.HEIC`   | vision | A imagem mostra um barco em um rio com vegetação densa ao redor, não é possível identificar um cômodo específico da lista.                                                                                             |
| NAO_IDENTIFICADO | NAO_IDENTIFICADO | 01   | —                   | `IMG_2908.HEIC`   | vision | A imagem mostra uma pessoa em um barco em um rio com vegetação densa ao redor, não é possível identificar um cômodo específico da lista.                                                                               |
| NAO_IDENTIFICADO | NAO_IDENTIFICADO | 01   | —                   | `IMG_2918.HEIC`   | vision | A imagem mostra uma pessoa em um barco em um rio com vegetação densa ao redor, não é possível identificar um cômodo específico da lista.                                                                               |
| NAO_IDENTIFICADO | NAO_IDENTIFICADO | 01   | —                   | `IMG_3153.HEIC`   | vision | A imagem mostra duas pessoas em pranchas de stand-up paddle em um rio com vegetação.                                                                                                                                   |
| NAO_IDENTIFICADO | NAO_IDENTIFICADO | 01   | —                   | `IMG_6069.HEIC`   | vision | A imagem mostra uma pessoa em um barco em um corpo d'água cercado por vegetação, não é possível identificar um ambiente específico da propriedade.                                                                     |
| NAO_IDENTIFICADO | NAO_IDENTIFICADO | 01   | —                   | `IMG_7887.HEIC`   | vision | A imagem mostra uma pessoa em um rio ou lago cercado por árvores, não é possível identificar um ambiente específico da propriedade.                                                                                    |
| PISCINA          | PISCINA          | 01   | —                   | `IMG_6151.HEIC`   | vision | A imagem mostra uma quadra de vôlei de praia com o mar ao fundo, o que pode ser uma área de lazer externa, mas não se encaixa perfeitamente em nenhuma categoria. PISCINA é a mais próxima para área de lazer externa. |
| QUARTO           | QUARTO           | 01   | —                   | `IMG_7185.HEIC`   | vision | A imagem mostra uma cama arrumada em um quarto com paredes de madeira.                                                                                                                                                 |
| QUARTO           | QUARTO           | 01   | —                   | `IMG_7187.HEIC`   | vision | A imagem mostra uma cama arrumada em um quarto com paredes de madeira.                                                                                                                                                 |
| QUARTO           | QUARTO           | 01   | —                   | `IMG_7197.HEIC`   | vision | A imagem mostra uma cama arrumada em um quarto com paredes de madeira.                                                                                                                                                 |
| QUARTO           | QUARTO           | 01   | —                   | `IMG_9648.HEIC`   | vision | Ambiente com cama de casal, ar condicionado e decoração de quarto.                                                                                                                                                     |
| QUARTO           | QUARTO           | 02   | —                   | `IMG_9660.HEIC`   | manual | Ambiente com cama de casal, ar condicionado e decoração de quarto.                                                                                                                                                     |
| QUARTO           | QUARTO           | 02   | —                   | `IMG_9661.HEIC`   | manual | Ambiente com cama de casal, ar condicionado, janela e acesso a um banheiro.                                                                                                                                            |
| QUARTO           | QUARTO           | 02   | —                   | `IMG_9692.HEIC`   | manual | Ambiente com cama de casal, ar condicionado e acesso a um banheiro.                                                                                                                                                    |
| SALA             | SALA             | 01   | —                   | `IMG_9432 2.HEIC` | vision | O ambiente possui sofás, mesas de centro e um espaço amplo para convivência.                                                                                                                                           |
| SALA             | SALA             | 01   | —                   | `IMG_9435 2.HEIC` | vision | O ambiente possui sofás, mesas de centro e um espaço amplo para convivência.                                                                                                                                           |
| SALA             | SALA             | 01   | —                   | `IMG_9449 2.HEIC` | vision | O ambiente possui sofás, mesas de centro e um espaço amplo para convivência.                                                                                                                                           |
| SALA             | SALA             | 01   | —                   | `IMG_9458 2.HEIC` | vision | O ambiente possui sofás, mesas de centro e um espaço amplo para convivência.                                                                                                                                           |
| SALA             | SALA             | 01   | —                   | `IMG_9461 2.HEIC` | vision | O ambiente possui sofás, mesas de centro e um espaço amplo para convivência.                                                                                                                                           |
| SALA             | SALA             | 01   | —                   | `IMG_9618.HEIC`   | vision | O ambiente é amplo, com piso de madeira, mesas e cadeiras, sugerindo um espaço de convivência ou jantar.                                                                                                               |
| SALA             | SALA             | 01   | —                   | `IMG_9620.HEIC`   | vision | Espaço amplo com mesas e cadeiras, área de estar com rede e decoração rústica, sugerindo um espaço de convivência.                                                                                                     |
| SALA             | SALA             | 01   | —                   | `IMG_9623.HEIC`   | vision | Vista da escada e do espaço de convivência com mesas e cadeiras, reforçando a ideia de um salão principal.                                                                                                             |
| TERRACO          | TERRACO          | 01   | —                   | `IMG_9636.HEIC`   | vision | Área externa ampla com mobiliário de estar e vista para a natureza, caracterizando um terraço.                                                                                                                         |
| TERRACO          | TERRACO          | 01   | —                   | `IMG_9691.HEIC`   | vision | Área externa com mobiliário de estar e vista para a natureza, caracterizando um terraço.                                                                                                                               |
| VARANDA          | VARANDA          | 01   | —                   | `IMG_9307 4.HEIC` | vision | A pessoa está sentada em uma varanda com vista para a natureza e redes.                                                                                                                                                |
| VARANDA          | VARANDA          | 01   | —                   | `IMG_9326 4.HEIC` | vision | A pessoa está sentada em uma varanda com vista para a natureza e redes.                                                                                                                                                |
| VARANDA          | VARANDA          | 01   | —                   | `IMG_9352 4.HEIC` | vision | A pessoa está em um nível superior de uma estrutura de madeira com vista para a natureza.                                                                                                                              |
| VISTA            | VISTA            | 01   | —                   | `IMG_2941.HEIC`   | vision | A imagem mostra uma vista de uma praia e um rio, com uma pessoa sentada em um banco ao fundo.                                                                                                                          |
| VISTA            | VISTA            | 01   | —                   | `IMG_2946.HEIC`   | vision | A imagem mostra uma vista de uma praia e um rio.                                                                                                                                                                       |
| VISTA            | VISTA            | 01   | —                   | `IMG_3194.HEIC`   | vision | A imagem mostra a proa de um barco se aproximando de uma praia em um rio.                                                                                                                                              |
| VISTA            | VISTA            | 01   | —                   | `IMG_3888.HEIC`   | vision | A imagem mostra uma pessoa sentada em uma praia, com o mar ao fundo.                                                                                                                                                   |
| VISTA            | VISTA            | 01   | —                   | `IMG_4078.HEIC`   | vision | A imagem mostra a proa de um barco em um rio com vegetação ao redor.                                                                                                                                                   |
| VISTA            | VISTA            | 01   | —                   | `IMG_9172.HEIC`   | vision | A imagem mostra uma paisagem de praia com cadeiras de descanso e o mar ao fundo.                                                                                                                                       |
| VISTA            | VISTA            | 01   | —                   | `IMG_9584.HEIC`   | vision | A imagem mostra um barco na água ao pôr do sol, com uma paisagem de rio e praia.                                                                                                                                       |
