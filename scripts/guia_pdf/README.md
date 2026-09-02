# Gerador do guia de primeiro acesso (PDF)

Produz `public/assets/tutorial/Toca-do-Coelho-Primeiro-Acesso.pdf` — o guia que
o app oferece no pop-up de abertura e em **Configurações › Ajuda e Atualizações**.

## Como regerar

**1. Suba uma instância isolada.** Nunca gere contra o banco de produção: o
script navega pelo sistema, abre modais e o app grava (backup automático, logs,
migrações). Redirecione o banco **e** o `USERPROFILE`, porque `TOCA_DB_PATH`
só troca o `.db` — logs, uploads, backups e a pasta da extensão continuam
saindo de `Path.home()`.

```bash
PORT=3111 \
TOCA_DB_PATH=/tmp/guia/toca-guia.db \
USERPROFILE='C:\tmp\guia\fakehome' \
python app.py
```

Use uma cópia de `BD_teste/toca-do-coelho-ficticio-reduzido.db` como banco: as
telas saem povoadas (uma base vazia não mostra estrutura nenhuma) e nenhum dado
real vai para o PDF distribuído.

**2. Valide os seletores antes de capturar.** O modo `--probe` percorre o
roteiro e imprime o retângulo de cada destaque, sem gravar imagem — é como se
descobre que um seletor morreu depois de uma mudança de UI:

```bash
python scripts/guia_pdf/capturar_telas.py --probe
```

Retângulo `0x0` significa alvo invisível (quase sempre um cartão de
Configurações que não foi aberto, ou um modal duplicado no DOM).

**3. Capture e monte.**

```bash
python scripts/guia_pdf/capturar_telas.py
python scripts/guia_pdf/montar_pdf.py
```

## O que cada script faz

**`capturar_telas.py`** — dirige o app com Playwright e captura 29 telas em 2×.
O efeito de foco é um `<div>` posicionado sobre o retângulo real do elemento
(`getBoundingClientRect`) com `box-shadow: 0 0 0 99999px rgba(6,14,11,.55)`:
o entorno escurece, o alvo fica em cores normais. Como é injetado na página
antes do print, o recorte acompanha exatamente o elemento.

Três detalhes que já custaram depuração:

- **Os cartões de Configurações são um acordeão e iniciam todos fechados.** Sem
  clicar no `<h3>` antes, os campos internos medem `0x0` e o destaque sai vazio.
  É o campo `card=` de cada item do roteiro.
- **`#accountModal` é criado via JS a cada abertura.** Sem remover a cópia
  anterior, `querySelector` acerta a versão antiga e oculta. `close_modals()`
  chama os fechadores do próprio app e depois remove o que sobrou.
- **Destaque de campo deve unir o `.form-group`, não o `<input>`.** Unir só os
  inputs corta o `<label>` ao meio — é para isso que existe `__spotUnionUp`.

**`montar_pdf.py`** — monta o PDF em A4 paisagem (capa, aviso sobre o banco,
índice e uma página por captura), reaproveitando as legendas de
`capturar_telas.py`. Também:

- reduz os PNG de 3000px para JPEG 1800px (~203 DPI na largura usada); sem isso
  o PDF vai a 12 MB e entra assim no repositório e no instalador;
- **aborta se algum texto usar glifo que a fonte não tem.** Georgia não tem
  `→` nem `✦`; Consolas não tem `✦`. O modo de falha é silencioso — o PDF sai
  com quadradinhos —, então `SUBST` troca os caracteres e `checar_glifos()`
  falha o build se sobrar algum.

## Ao mexer no roteiro

`PASSOS`, em `montar_pdf.py`, é a fonte dos títulos, selos e caminhos de UI; o
`SHOTS`, em `capturar_telas.py`, é a fonte das telas e legendas. Um passo pode
ter várias telas (o número do passo repetido gera "1 de 2" no título).

Se o número de passos mudar, atualize também: o texto da capa, o título da
página de índice e a cópia do pop-up em `public/js/scheduled-sends.js`
(`_showTutorialPdfModal`) — os três citam a quantidade.
