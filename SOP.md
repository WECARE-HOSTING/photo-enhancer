# SOP — Photo Enhancer

Como tratar as fotos de um imóvel, do jeito que o cliente recebe.
Leia uma vez inteiro. Depois é só seguir os quatro passos.

---

## O que a ferramenta faz

O fotógrafo manda tudo o que fotografou — 300 fotos, um link, um zip, RAW, o que
for. A ferramenta:

1. **escolhe** as ~50 que valem a pena e dá nome de ambiente a cada uma
2. **melhora** cada uma com IA — luz, cor, nitidez, verticais
3. **assina** com a marca WeCare
4. **arquiva** o trabalho inteiro, com os originais

O resultado é um conjunto de fotos prontas para o anúncio.

**A regra que manda em tudo:** a ferramenta *melhora a foto real*, ela não cria
uma foto nova. Mesmo quarto, mesmos móveis, mesma planta — só fotografado
melhor. Uma foto bonita de um quarto *diferente* é um trabalho reprovado, porque
engana quem vai alugar ou comprar o imóvel. **É por isso que você olha as fotos
em três momentos antes de qualquer coisa sair daqui.**

---

## Antes de começar (uma vez só, na máquina)

- A pasta do projeto na máquina.
- A chave da fal.ai em `_config/.env` (é o que paga a IA). Sem ela o passo 2 não
  roda.
- O ambiente Python instalado (`_config/.venv`).

Se algum desses três não existe, chame quem instalou. Não tem como contornar.

---

## Regras de ouro

| | |
|---|---|
| **Sempre entre pelo `drop/`** | Toda entrega começa em `0 - selection/drop/`, até uma que já vem escolhida. Não existe atalho. |
| **Coloque todo caminho entre aspas** | Os nomes das pastas têm espaço. Sem aspas o comando quebra. |
| **Rode o comando direto** | Não existe simulação, prévia nem teste. O comando é o trabalho. |
| **Só você aprova** | Aprovar é dizer "isso pode ir para o cliente". Ninguém e nada aprova no seu lugar. |
| **Cada comando abre uma página no navegador e fica esperando** | Ele só volta quando você aperta Ctrl-C no terminal. Isso é normal. Fechar a aba não perde nada. |

---

## Passo 1 — Escolher as fotos

**Custa centavos.** É a IA olhando as fotos para dizer que ambiente é cada uma.

```bash
# a) coloque as pastas/zips do fotógrafo dentro de "0 - selection/drop/", depois:
./_config/.venv/bin/python "0 - selection/fetch.py" --name "Casa Lagoa"

# b) analisar e montar a folha de contato:
./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/Casa Lagoa" --vision
```

Abre o `review-selection.html`. **É aqui que você trabalha:**

- **Marque as fotos que vão para o anúncio.** A IA já deixa umas pré-marcadas com
  o motivo escrito embaixo — é sugestão, você decide. O contador do ambiente fica
  vermelho quando você passa da cota dele.
- **Confira o ambiente embaixo de cada foto.** Esse nome vai no arquivo até o
  cliente. Se estiver errado, corrija ali e aperte **'Salvar e re-cortar'** —
  é de graça.
- **Dois quartos que viraram um só?** Aperte `+ novo QUARTO` na foto do segundo.
  Sua decisão sempre vence a da IA, e ela não é mais consultada sobre aquele
  ambiente.
- **Uma marca vermelha na foto** quer dizer que as duas passagens da IA
  discordaram entre si — vale olhar essa foto com atenção.

Quando as marcações estiverem do jeito que você quer: **'Revelar o trabalho'**.
Isso cria o `Job_NNNN` — o trabalho nasce aqui, com número próprio.

> A pasta da entrega **fica guardada para sempre**, com todas as fotos, mesmo as
> que você não escolheu. Só sai de lá quando alguém apagar de propósito.

---

## Passo 2 — Melhorar com IA

**É o único passo que custa dinheiro de verdade.** Cada foto é uma chamada paga
na fal.ai, um ou dois minutos, várias ao mesmo tempo.

```bash
./_config/.venv/bin/python "1 - edit/batch.py"
```

Abre o `review-edit.html` — antes e depois, lado a lado, agrupado por ambiente.

**Como olhar (isso importa):** clique na foto e aperte `a` / `b`. As duas trocam
de lugar no mesmo tamanho e posição. Lado a lado você só vê *se mudou*; a
troca mostra *se mudou certo* — uma parede 3° torta ou uma cadeira inventada não
aparecem no lado a lado, mas não sobrevivem à troca.

Para cada foto ruim:

1. marque ela
2. **escreva na caixa embaixo o que tem que mudar** — em português, na sua
   língua, do jeito que você falaria. *"a pessoa na janela sumiu, põe de volta"*
3. **'Refazer as marcadas'**

O que você escreve **é o pedido inteiro** para aquela foto. Pode pedir coisas que
o tratamento padrão não faz. Uma foto marcada sem comentário para o processo —
não há o que pedir.

A foto que volta de um retoque mostra **três painéis** (original / edição
anterior / retoque, teclas `a` / `c` / `b`) e a frase que você escreveu. Assim
você confere o resultado contra o pedido, e não só se ficou bonito.

Quando estiver bom: **'Aprovar e mandar adiante'**.

> **Se a mesma coisa errada aparece toda vez, em toda foto**, não fique
> refazendo: peça para ajustar o `1 - edit/1 - edicao/PROMPT.md`. Ele vale para
> todas as fotos futuras; o comentário vale só para uma.

---

## Passo 3 — Marca d'água

**Local e de graça.** Errar aqui não custa nada, então refaça à vontade.

```bash
./_config/.venv/bin/python "2 - marca dagua/batch.py"
```

Abre o `review-marca.html`. A marca tem menos de 1% da foto, então a página
mostra o **canto superior esquerdo em tamanho real** — é a única pergunta desta
tela: *a marca está legível onde caiu?*

A ferramenta mede o fundo de cada foto e escolhe a tinta (preta ou branca)
sozinha. Quando ela erra — quase sempre porque a marca caiu na divisa entre uma
parte clara e uma escura — marque a foto, force a tinta no botão de rádio e
**'Refazer as marcadas'**.

- **'Re-marcar todas'** refaz o trabalho inteiro, de graça (use depois de mexer
  no tamanho ou na posição da marca).
- Quando estiver bom: **'Aprovar e arquivar'**.

Os arquivos `_final.jpg` são **o que o cliente recebe**.

---

## Passo 4 — Arquivo

Não tem nada para fazer. O trabalho aprovado vai para `3 - completed/Job_NNNN/`
com tudo dentro: as fotos originais, as editadas, as finais, o histórico de cada
decisão que você tomou, e a entrega inteira do fotógrafo em `originais/`.

Para achar um trabalho antigo: `3 - completed/index.md`.

Se algo parecer fora de lugar (alguém arrastou uma pasta?):

```bash
./_config/.venv/bin/python "3 - completed/archive.py" --check   # de graça, só lê
```

---

## Como os arquivos se chamam

A foto ganha nome **uma vez**, no passo 1, e leva esse nome até o fim:

```
SALA_01_0002.jpg          ambiente · qual sala dessas · qual foto
SALA_01_0002_edit.jpg     o que a IA devolveu
SALA_01_0002_final.jpg    com a marca — é isto que o cliente recebe
SALA_01_0002_log.md       o que foi pedido e o que voltou
```

---

## Resumo de uma tela

```
1. "0 - selection/fetch.py" --name "<nome>"        centavos
   "0 - selection/cull.py" "0 - selection/<nome>" --vision
   → marque as fotos, confira os ambientes → 'Revelar o trabalho'

2. "1 - edit/batch.py"                             CUSTA DINHEIRO
   → a/b em cada foto, escreva o que mudar → 'Refazer as marcadas'
   → quando estiver bom → 'Aprovar e mandar adiante'

3. "2 - marca dagua/batch.py"                      de graça
   → confira o canto em tamanho real → 'Aprovar e arquivar'

4. nada a fazer. está em "3 - completed/".
```

---

## Quando dá problema

| O que aconteceu | O que fazer |
|---|---|
| Os botões da página não fazem nada | A página foi aberta do disco, não do servidor. Rode o comando da etapa de novo — ou use os botões de "Copiar" ao lado e cole no arquivo à mão. |
| Uma foto não tem `_edit` | Ela falhou. Rode `"1 - edit/batch.py"` de novo: ele repete só as que faltam, sem cobrar pelas que já deram certo. |
| Falhou tudo igual, de uma vez | É chave, cota ou a fal.ai fora do ar. Não adianta repetir — o próprio comando avisa isso. |
| O ambiente de uma foto está errado | Corrija na página do passo 1 e 'Salvar e re-cortar'. De graça. |
| A marca ficou grande, pequena ou no lugar errado | São seis números no começo de `2 - marca dagua/marca.py`. Mude e rode `--rebrand`. De graça. |
| Quero trocar o logo | Substitua os arquivos em `_config/logos/` mantendo os mesmos nomes. A próxima rodada re-marca tudo sozinha. |
| Preciso de espaço em disco | Só depois do trabalho arquivado: `"3 - completed/archive.py" --purge-source "0 - selection/<nome>"`. **Apaga fotografias e não tem volta** — leia o que ele imprime antes de confirmar. |
