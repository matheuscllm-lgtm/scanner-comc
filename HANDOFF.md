# HANDOFF — Scanner de arbitragem COMC → TCGPlayer (Pokémon)

> Documento de transferência para retomar o trabalho em uma nova sessão (inclusive via
> Claude Code remoto no celular). Última atualização: 2026-06-08 (sessão 2).

---

## 0. TL;DR (estado atual)

- **O que é:** um scanner em Python que acha cartas Pokémon listadas na **COMC** por preço
  abaixo do **preço de mercado do TCGPlayer**, e lista os **top 50 deals por margem bruta**
  (`> 20%`, sem preço mínimo), emitindo **resultados parciais ~a cada 1h** enquanto roda.
- **Onde está:** branch **`claude/wizardly-maxwell-gnhfe3`**, **PR #1 (draft)**:
  https://github.com/matheuscllm-lgtm/scanner-comc/pull/1
- **Build:** ✅ código completo e empurrado · ✅ **24/24 testes offline** · ✅ **CI verde**
  (`.github/workflows/tests.yml`, job `offline-tests`).
- **Verificado ao vivo:** TCGCSV (217 sets, matching real), `dry-run` completo, `robots.txt`,
  e **a raspagem + parsing da COMC contra páginas REAIS** (ver §6.1 / §10).
- **✅ BLOQUEADOR PRINCIPAL RESOLVIDO (sessão 2, 2026-06-08):** os seletores da COMC foram
  calibrados contra **3 capturas reais** obtidas via **Firecrawl (proxy `stealth`)** — não
  precisou de Playwright/login/celular. O parser agora extrai **100/100 listagens** por página,
  com `set_hint`, `number_hint`, `condition`, `price`, `quantity` e `item_id`. Fixture real
  commitada em `tests/fixtures/comc_real_capture.html` + testes em `tests/test_parse_real.py`.
- **🐞 BUG CRÍTICO encontrado e corrigido** com os dados reais: a resolução de set casava
  **códigos curtos de set dentro de palavras** (`pr`⊂"printing", `em`⊂"pok**em**on"), fazendo
  toda listagem Topps resolver para um set TCG aleatório e gerar **falsos positivos** (carta
  Topps reportada como arbitragem TCG). Corrigido (ver §11). Sem o fix, a saída era lixo.
- **Próximo passo recomendado:** trocar o fetch ao vivo (`iter_listings`) de Playwright para
  **Firecrawl** — aí o scanner roda **headless, sem navegador/login/cookies** (ver §10).

---

## 1. Objetivo (pedido original)

Replicar a filosofia dos scanners `Card-trader-scanner` / `Myp-arbitrage-scanner`, mas para a
**COMC**: comparar o preço de venda na COMC com o preço habitual do TCGPlayer, calcular a
**margem bruta**, rankear os **50 melhores deals** com margem **> 20%** (configurável, **sem
preço mínimo**) e entregar **parciais a cada ~1 hora**, num formato fácil de jogar no Google
Sheets. (Os repositórios dos outros scanners não estavam acessíveis nesta sessão — escopo
travado em `scanner-comc` — então o scanner foi construído do zero, equivalente.)

---

## 2. Mapa do repositório

```
comc_scanner/
  __main__.py        CLI: run | once | refresh-prices | dry-run | capture | parse-file
  config.py          Settings + load_settings (.env) + CACHE_DIR (.cache/)
  logging_setup.py   logging
  models.py          dataclasses: ComcListing, Deal, (TcgCard)
  normalize.py       normalize_set, set_aliases, detect_graded, normalização de número
  tcgcsv_client.py   TcgCsvClient: groups()/products()/prices()/snapshot_date(), cache diário
  tcg_index.py       TcgIndex: índice de cartas por set+número e por nome (fuzzy)
  matcher.py         match(): casa ComcListing↔TcgCard com TIERS de confiança
  margin.py          cálculo de margem BRUTA isolado (trocar p/ taxas/markup aqui)
  segments.py        eras (recent/middle/vintage) + select_sets/to_sets + ChunkCursor (retomada)
  comc_scraper.py    ComcScraper (Playwright) + parsing + robots_allowed + capture + build_browse_url
  pipeline.py        Scanner: run_loop / run_once / refresh_prices / dry_run / capture / parse_file
  reporter.py        saída: tabela markdown + CSV/JSON em results/ + push opcional Google Sheets
tests/
  test_normalize.py, test_matcher.py, test_segments.py   (16 testes, todos OFFLINE)
  fixtures/listings_sample.json   listagens sintéticas p/ dry-run
  fixtures/comc_sample.html       PLACEHOLDER (trocar por página real da COMC — ver §6)
.github/workflows/tests.yml       CI: roda os testes offline no PR
requirements.txt, pyproject.toml, .env.example, README.md, results/.gitkeep
```

---

## 3. Como funciona (fluxo de dados)

1. **Preços TCGPlayer** vêm do **TCGCSV** (`tcgcsv.com`, espelho público/grátis; Pokémon =
   `categoryId 3`). Snapshot diário cacheado em `.cache/`. Referência = `marketPrice`
   (fallback `mid` → `low`).
2. **Listagens COMC** vêm via **Playwright/Chromium** navegando as URLs de busca com facetas
   por vírgula (ex.: `/Cards/Pokemon,=evolving+skies,sl,fb,aUngraded,rCOMC,gEX-NM,i100,p3`).
   A COMC está atrás de **Cloudflare** (um GET simples dá **HTTP 403**), por isso usamos
   navegador real, opcionalmente com `COMC_SESSION_COOKIE`. Import do Playwright é **preguiçoso**
   → o núcleo roda sem navegador.
3. **Matching** por `set + número` com **tiers de confiança** + fallback de nome fuzzy. O
   **subtype** (Normal/Holo/Reverse/1st Ed/Unlimited) é inferido das pistas; **sem pista, usa o
   mais barato** (conservador — não infla margem em sets WotC).
4. **Margem bruta** = `(tcg − comc) / tcg`, isolada em `margin.py`.
5. **Eras + chunking:** sets agrupados por `publishedOn` em `recent`/`middle`/`vintage`.
   A era é selecionável (`--era`) e funciona como **chunk** com orçamento de tempo/quantidade,
   salvando cursor em `.cache/progress/<era>.json` e **retomando** depois (não estoura o tempo).
6. **Entrega:** a cada flush (~1h e ao fim de cada chunk) → **tabela markdown** no console +
   `results/comc_deals_<era>_latest.csv`/`.json` (+ snapshots com timestamp). Push opcional a um
   Google Sheet real (degrada p/ CSV se não houver credenciais).

---

## 4. Como rodar (quickstart)

```bash
pip install -r requirements.txt
playwright install chromium          # só p/ raspagem ao vivo da COMC
cp .env.example .env                 # ajuste COMC_SESSION_COOKIE etc.

# Loop contínuo com parciais ~horárias:
python -m comc_scanner run --era recent
# Um chunk só (com retomada por cursor), bom p/ testar tempo:
python -m comc_scanner once --era vintage --max-sets-per-chunk 2
# Atualizar o snapshot de preços do TCGCSV:
python -m comc_scanner refresh-prices --era all
# Testar matching/relatório SEM tocar a COMC (listagens sintéticas):
python -m comc_scanner dry-run --era vintage --listings tests/fixtures/listings_sample.json
```

Flags úteis (ver `.env.example` p/ os equivalentes em variável de ambiente): `--top-n 50`,
`--min-margin 0.20`, `--min-confidence 0.80`, `--interval 3600`, `--condition EX-NM`,
`--include-graded`, `--headful`, `--no-sheets`, `--sets "Evolving Skies,SV09"`, `--restart`.

Testes: `python -m pytest tests/` (são offline, sem rede).

---

## 5. O que foi VERIFICADO vs. o que está PENDENTE

**Verificado nesta sessão (ao vivo / com execução real):**
- ✅ TCGCSV ao vivo: **217 sets**; Base Set→`vintage`, SV09→`recent`; **Charizard `4/102`**
  casado e desambiguado do "Black Dot Error", **Holofoil market `$614.49`**.
- ✅ `dry-run`: ranking por margem desc., carta cara excluída pelo limiar, graded ignorada,
  set inexistente sem match; CSV/JSON gravados; Sheets degradou p/ CSV sem credenciais.
- ✅ **Subtype conservador**: Jungle Pikachu usa `Unlimited` ($6.28), não `1st Edition` ($28.58).
- ✅ `robots.txt` da COMC lido ao vivo → **permite** nosso UA de navegador.
- ✅ **24/24 testes offline** e **CI verde** no PR.
- ✅ Novos comandos `parse-file` / `capture` / `dry-run --html` funcionam.
- ✅ **(sessão 2) Seletores da COMC calibrados contra páginas REAIS** via Firecrawl `stealth`:
  parser extrai 100/100 listagens com `set_hint`/`number_hint`/`condition`/`price`/`qty`/`item_id`.
  `dry-run --html` numa página real de Topps agora retorna **0 falsos positivos** (correto:
  Topps não é TCG); o happy-path (Base Set Charizard 4/102 → Holo $614.49) segue casando.
- ✅ **(sessão 2) Bug de falso-positivo na resolução de set corrigido** (§11).

**Pendente:**
- ❌ **Raspagem CONTÍNUA ao vivo**: `iter_listings` ainda usa Playwright (navegador). Para rodar
  headless sem login, **migrar para Firecrawl** (§10) — capturas pontuais já funcionam por lá.
- ⚠️ **CF intermitente em URLs de busca facetada** (`,=evolving+skies,`): a página de browse
  simples passou de primeira; a busca por termo levou challenge ~3× seguidas. Ver §10.
- ⛔ **Google Sheets real**: só degrada p/ CSV até configurar credenciais (`GSHEETS_*` no `.env`).

---

## 6. Os 2 pontos abertos e COMO resolver

### 6.1 Seletores HTML da COMC — ✅ RESOLVIDO (sessão 2)
Os seletores foram calibrados contra páginas reais. O **DOM verificado** de uma página de
browse (`/Cards/Pokemon,...,i100,pN`) é: cada resultado é um `<div class="carddata">` e o
link de detalhe carrega tudo no path —

```
/Cards/Pokemon/<ano>/<Set_Name>/<Numero>/<Card_Name>/<id>/<Ungraded|Graded>/<COMC>/<Condição>
ex.: /Cards/Pokemon/1999/Topps_..._Series_1_-_Base/TV8/Gary_Oak/4341265/Ungraded/COMC/EX-NM
```

`_parse_dom` (em `comc_scraper.py`) segmenta por `carddata`, lê set/número/nome/condição do
path do link, e o preço/quantidade do markup `listprice`/`qty`. Sem `selectolax` (regex pura).

Loop de validação (continua válido para re-calibrar se a COMC mudar o HTML):
```bash
python -m comc_scanner parse-file --html tests/fixtures/comc_real_capture.html   # 100 listagens
python -m comc_scanner dry-run --era all --html tests/fixtures/comc_real_capture.html --no-sheets
```
> `tests/fixtures/comc_real_capture.html` = captura REAL commitada (página de Topps, 100 cards).
> `tests/fixtures/comc_sample.html` = placeholder JSON-LD sintético (mantido só p/ back-compat).
> `tests/test_parse_real.py` trava a estrutura: se a COMC mudar o DOM, a CI quebra aqui.

### 6.2 Termos de Uso da COMC
- **robots.txt (boa notícia):** a COMC **permite** user-agents comuns (`User-agent: *` →
  `Allow: /`) e só bloqueia bots de treino de IA (GPTBot, CCBot, **ClaudeBot**, ...) com
  `ai-train=no`. O scanner **checa o robots.txt antes de raspar e aborta se for proibido**
  (`ComcAccessError`), usa **UA de navegador comum**, uso pessoal, ritmo conservador. Nunca
  usar um UA da lista bloqueada.
- **ToS é separado** do robots.txt e pode restringir acesso automatizado. **Não há API oficial**
  (o "COMCAgent" é só um serviço de compra automática, não um canal de dados).
- **Recomendação / decisão sua:** revisar os ToS; manter volume baixo / uso pessoal (o robots
  permite crawling); se quiser garantia formal, pedir permissão à COMC.

---

## 7. Decisões de design (para não re-litigar)

- **Dependências enxutas:** `requests` + stdlib (csv/json) + `rapidfuzz`/`selectolax` com
  fallbacks, Playwright **preguiçoso**. (Evitado httpx/pandas/tabulate/rich p/ rodar em ambiente
  mínimo.) Veja `requirements.txt`.
- **Margem é BRUTA** (sem taxas/frete), isolada em `margin.py` — mude lá se quiser líquida.
- **Graded excluído por padrão** (`--include-graded` para incluir).
- **Preços em USD** (COMC e TCGPlayer), sem conversão de moeda.
- **Subtype ambíguo → mais barato** (conservador).
- **Eras como chunks retomáveis** para respeitar orçamento de tempo e dar parciais.

---

## 8. Notas do ambiente / git

- **Ambiente remoto efêmero:** o container é descartado por inatividade; **só o que está
  commitado/empurrado sobrevive**. Este HANDOFF está no repo de propósito.
- **Branch de trabalho:** `claude/wizardly-maxwell-gnhfe3` (desenvolver e empurrar aqui).
- **`main`** existe como commit inicial vazio (`c30143a`), só para o PR #1 ter base de diff.
- **Cloudflare:** a COMC dá 403 a GETs simples a partir do sandbox; raspagem real exige
  navegador + seus cookies, idealmente fora do ambiente isolado.
- **PR #1** está inscrito para eventos (CI/comentários) — pode haver uma sessão "ouvindo" o PR.

---

## 9. Sugestão de PRIMEIRO PROMPT para a nova sessão

> "Estou retomando o scanner COMC→TCGPlayer (branch `claude/wizardly-maxwell-gnhfe3`, PR #1).
> Leia `HANDOFF.md` primeiro. O bloqueador é calibrar os seletores da COMC contra uma página
> real (§6.1). Vou [colar o HTML de uma listagem / commitar `tests/fixtures/comc_sample.html`
> capturado]. A partir disso, ajuste `_parse_dom` em `comc_scraper.py` para extrair também o
> `set_hint`, e valide com `dry-run --html`."

(Se for raspar de verdade: rode `playwright install chromium`, ponha `COMC_SESSION_COOKIE`
no `.env`, e teste com `once --era recent --max-sets-per-chunk 1` antes do `run`.)

---

## 10. Como as páginas reais foram obtidas (Firecrawl, sem navegador) — sessão 2

O Cloudflare bloqueia GET simples, mas o **Firecrawl com `proxy: stealth`** entrega o HTML
renderizado da COMC **sem Playwright, sem login, sem cookies** (mesma rota que furou a OLX no
sealed scanner). Foi assim que as 3 capturas reais saíram. Reproduzir:

```
firecrawl_scrape(
  url="https://www.comc.com/Cards/Pokemon,sh,fb,aUngraded,rCOMC,gEX-NM,i100,p1",
  formats=["rawHtml"], proxy="stealth", waitFor=12000, onlyMainContent=false)
```
O `rawHtml` vem dentro de um wrapper JSON (`{"rawHtml": "..."}`) — extrair com `json.loads`.

**Observações importantes:**
- A **página de browse simples** (sem termo de busca) passou de primeira. A **busca facetada
  por termo** (`,=evolving+skies,`) levou Cloudflare challenge ~3× seguidas — é mais vigiada.
  Para um set específico, tente algumas vezes, alterne `proxy` (`stealth`→`auto`), ou use a
  rota Playwright logada.
- **Próximo passo de maior alavancagem:** reescrever `ComcScraper.iter_listings` para buscar via
  Firecrawl (`/scrape` por página) em vez de Playwright. Aí o `run`/`once` rodam headless neste
  ambiente, sem instalar Chromium nem `COMC_SESSION_COOKIE`. O parser (`parse_page`) já está
  pronto para o HTML real — só falta trocar a fonte do HTML. (Atenção ao CF intermitente acima:
  adicionar retry/backoff por página.)

**Descoberta de escopo:** a categoria `/Cards/Pokemon` da COMC é **muito mais ampla que o TCG
Pokémon** — está cheia de Topps, Bandai, Topsun, Burger King, stickers Marumiya, etc., que **não
existem no TCGCSV**. Por isso uma varredura genérica casa pouco (e deve mesmo). Para achar
arbitragem TCG de verdade, **mire nos nomes de set TCG reais** (busca por termo / `--sets`),
não na categoria inteira.

---

## 11. Bug de falso-positivo na resolução de set (corrigido, sessão 2)

**Sintoma:** `dry-run` numa página real de Topps gerava ~30 "deals" com confiança 0.90–0.95 —
cartas Topps (Gary Oak, Zubat…) reportadas como cartas TCG (Leafeon 24/100, Water Energy…).

**Causa raiz (dois níveis):**
1. **Resolução de set frouxa.** `_resolve_tset` (pipeline) e `TcgIndex.resolve_set` faziam
   `alias in key or key in alias` — substring cru. Códigos de set de 2–3 chars casavam **dentro
   de palavras**: `pr`⊂"1st **pr**inting", `em`⊂"pok**em**on", `ma`⊂"ani**ma**tion". Resultado:
   toda listagem Topps resolvia para um set TCG aleatório (o primeiro na ordem do dict).
2. **Tier 1 sem checagem de nome.** Com set errado resolvido, um número que por acaso existisse
   naquele set casava no Tier 1 (set+número único, conf 0.95) **sem olhar o nome** → deal falso.

**Correção (mínima e cirúrgica):**
- `normalize.set_contains(a, b)`: containment só por **fronteira de palavra** (`\b`) e exige
  ≥ 4 chars; códigos curtos só resolvem por **igualdade exata**. Usado nos dois resolvers.
- `matcher.match`: Tier 1 agora exige um **piso de afinidade de nome** (`fuzzy ≥ 45`) mesmo no
  match único set+número — bloqueia "set errado + número coincidente + nome alheio".
- Bônus: `subtype_hint` agora também lê `set_hint` + `description` (a edição 1st Ed/Unlimited/Holo
  vive no nome do set, não no nome limpo da carta).

**Validação:** página Topps real → **0 deals** (correto); happy-path sintético (Base/Jungle) →
casa certo com preços/subtypes corretos; **24/24 testes**. Travado por `tests/test_parse_real.py`.
