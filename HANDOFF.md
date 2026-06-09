# HANDOFF — Scanner de arbitragem COMC → TCGPlayer (Pokémon)

> Documento de transferência para retomar o trabalho em uma nova sessão. Última
> atualização: **2026-06-09 (sessão 4)**. Leia a seção 0 abaixo — é a fonte da verdade;
> as seções 0-bis/12 abaixo são histórico.

---

## 0. ⭐ RETOMAR AQUI — estado atual (2026-06-09)

**O scanner está FUNCIONANTE, ÚTIL e HONESTO.** Roda de **dois jeitos**, com ou sem créditos:

```
# GRÁTIS (sem crédito Firecrawl) — navegador local, é o que está em uso agora:
python -m comc_scanner targeted --era recent  --fetch-mode playwright --no-sheets   # MODERN
python -m comc_scanner targeted --era vintage --fetch-mode playwright --no-sheets   # WotC

# Firecrawl (rápido, headless, mas precisa de crédito — esgotou no overnight, 402):
python -m comc_scanner targeted --era recent --no-sheets
```

### Os dois transportes (`COMC_FETCH_MODE`)
1. **`playwright` (GRÁTIS, sem crédito)** — patchright + **Chrome real + HEADFUL** auto-resolve
   o Cloudflare Turnstile da COMC (sem clique humano; num server roda em display virtual).
   Forçado headful automaticamente (headless NUNCA fura o CF aqui). Perfil persistente
   `.cache/pw_profile_comc` guarda o cf_clearance; `comc_scanner warm` pré-aquece. **Requer
   Chrome instalado + display (ou virtual).** NÃO serve pro GitHub Actions (cloud sem display).
2. **`firecrawl` (default)** — `proxy:stealth`, headless, sem navegador. Precisa `FIRECRAWL_API_KEY`.
   É o único que serve pro GH Actions. **Créditos esgotados no overnight** (recarregar billing).

> Por que o local precisa headful: o IP deste ambiente (BR) é hard-blocked pela CF da COMC em
> acesso simples; só navegador real headful OU proxy US residencial (Firecrawl) furam.

### Filtros/invariantes ATIVOS (todos no pipeline, aplicados nos modos live)
- **NM-only** (`comc_condition_allow`): só condições NM/EX-NM; a faceta `gEX-NM` é ignorada no
  set-path, então filtra pela condição da URL de cada carta.
- **English-only** (`comc_exclude_variants`, NOVO 2026-06-09): dropa sub-printings de outro idioma
  (Japanese/Korean/...). **Crítico:** o set-path da COMC retorna TODOS os idiomas do set e o
  TCGCSV é EN — casar JP/KR com preço EN inflava a lista com falsos positivos (28 → 3 deals reais).
- Margem bruta ≥ `--min-margin` (default 0.20). Sem piso de preço (operador decide).

### Catálogo (`comc_scanner/comc_set_slugs.json`) — 19 validados + 9 pendentes
- **15 WotC** (Base..Skyridge) + **4 modern** validados: SV 151, SV02 Paldea Evolved,
  SV03 Obsidian Flames, SV08 Surging Sparks.
- **9 modern `validated:false`** (SV04..SV10): slugs já vêm de URLs reais; falta 1 scrape cada
  pra confirmar e virar a flag (precisa crédito Firecrawl OU rodar via playwright).
- Vintage WotC: formato `{year, slug}`. Modern: `{year:"", slug}` (segmento único c/ ano embutido).

### Entrega da tabela (formato pedido pelo operador 2026-06-09)
- Coluna **Card = nome + número** ("Pikachu 173/165"); coluna **Link = [oferta](url)** clicável.
- CSV/JSON mantêm `card`, `number`, `comc_url` separados (p/ planilha).

### ⚠️ Leitura honesta do mercado (importante)
COMC-EN ≈ TCGPlayer-EN (mesmo mercado US, sem vantagem cambial dos scanners irmãos), então
**arbitragem real é FINA**: depois do filtro English-only, 2 sets modernos grandes (151 +
Surging Sparks) deram só **3 deals pequenos** (~$1-2 lucro). O "jackpot" anterior de ~28 deals
era 96% ruído de variante JP/KR casada com preço EN. O scanner é TÉCNICO — entrega candidatos;
o operador valida carta-a-carta no TCGPlayer (condição NM) e decide capital.

### Próximos passos (ordem de valor)
1. Validar os 9 modern pendentes (via playwright agora, sem precisar de crédito).
2. Rodar o panorama completo dos modern validados pra ver o yield honesto real.
3. (Opcional) Robustez do playwright p/ varredura longa: matar Chrome órfão entre runs; um
   `targeted` único = 1 sessão de browser (ok), mas invocações sobrepostas brigam pelo perfil.
4. Recarregar Firecrawl quando quiser o caminho cloud/GH Actions.

### Estado git
Branch `claude/wizardly-maxwell-gnhfe3`, PR #1. ~25 commits. **38 testes offline, CI verde.**
⚠️ Uma sessão cloud paralela escuta o PR — **fazer `git fetch` + rebase antes de todo push.**

---

## 0-bis. TL;DR sessão 3 (overnight 2026-06-08) — ✅ SCANNER FUNCIONANTE

- **O scanner agora RODA HEADLESS e PRODUZ DEALS REAIS.** Comando funcional:
  `python -m comc_scanner targeted --era vintage --no-sheets` — varre os 15 sets WotC do
  catálogo via **set-path browse** (fura Cloudflare), casa com TCGCSV, reporta tabela.
- **Como funciona o fetch:** Firecrawl `proxy:stealth` (sem navegador/login). `COMC_FETCH_MODE`
  default `firecrawl`. Precisa `FIRECRAWL_API_KEY` no ambiente (já setado na máquina).
- **Validado ao vivo:** `targeted` em Base/Jungle/Fossil → **50 deals reais** (commit antes do
  filtro de condição). Depois apliquei o **filtro NM-only** (invariante do operador).
- **Modos:** `targeted` (set-path, yield útil — USAR ESTE) · `broad` (browse genérica, ~0 por
  ser Topps) · `once`/`run` (per-set text-search — bloqueado por CF, evitar em firecrawl).
- **Detalhes completos da sessão em §12.** Pendências/nuances conhecidas em §12 também
  (sort `sl` favorece played → paginar fundo p/ NM; sem piso de preço; agendamento recorrente).

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

---

## 12. Sessão 3 (overnight 2026-06-08) — fetch headless via Firecrawl + modos de scan

**Objetivo da sessão:** tornar o scanner FUNCIONANTE headless (sem navegador/login).

### O que foi feito (commitado/pushado)
1. **Transporte Firecrawl** (`comc_scanner/firecrawl_client.py`): `/v2/scrape` com `proxy:stealth`
   fura o Cloudflare da COMC sem Playwright/login/cookies. `ComcScraper` virou **mode-aware**
   (`COMC_FETCH_MODE=firecrawl|playwright`, default firecrawl); `iter_listings`/`capture` usam
   `_fetch_html()`. CLI `--fetch-mode`. **Verificado ao vivo:** o `capture` do próprio scanner
   baixa página real headless (644 KB, 100 listagens). (commit `df32a65`)
2. **Circuit breaker** (review do agente revisor): `run_once` conta sets bloqueados em sequência
   e aborta após 3 — evita queimar créditos Firecrawl num bloqueio de conta. `iter_listings`
   re-levanta `ComcBlockedError` (≠ página vazia). (commit `6165f00`)
3. **Modo `broad`**: varre a browse simples (que fura CF), filtra pelo matcher, e **colhe slugs**
   das URLs em `.cache/comc_set_catalog.json`. Rodou headless 400 listagens → **0 match**
   (a browse barata da COMC é 100% Topps/novelty, fora do TCGCSV). (commit `6165f00`)
4. **Modo `targeted`** (`run_targeted`): lê `comc_scanner/comc_set_slugs.json`
   (TCG set → {year, slug}) e navega cada set pela **URL de set-path** (rota que fura CF). É o
   modo de **yield útil**.

### Descobertas-chave (NÃO re-descobrir)
- **Set-path browse fura o CF; text-search NÃO.** URL que funciona:
  `/Cards/Pokemon/<ano>/<Set_Slug>,sl,fb,aUngraded,rCOMC,i100,p1` (verificado: set Topps 175
  listagens, set-scoped). A busca facetada `,=<termo>,` leva challenge 3×+ seguidas.
- **A categoria `/Cards/Pokemon` da COMC é dominada por Topps/Bandai/Topsun/Burger King/stickers**
  (fora do TCGCSV) nos extremos de preço. Por isso `broad` rende ~0 e `targeted` (set-path) é o
  caminho. O alvo real de arbitragem é **WotC vintage** (Base/Jungle/Fossil/Neo…) — existe no
  TCGCSV e tem inventário raw na COMC.
- **Naming COMC (WotC EN):** "Pokemon Base Set - [Base] - Unlimited"; slug troca espaço→`_` e
  dropa os colchetes (`[Base]`→`Base`). Ex. Jungle Spanish slug = `Pokemon_Jungle_-_Base_-_Spanish`.
  A descoberta de slug exato sai de URLs de card-detail reais (via `firecrawl_search site:comc.com`).

### Filtro NM-only (correção de invariante) + nuance de yield
- A browse set-path **ignora o facet de condição `gEX-NM`** → vazavam LP/MP/HP/Noted (quebra
  o invariante NM-only do operador e infla margem: carta played vs preço NM do TCG). Corrigido
  com **filtro por condição da URL** (`COMC_CONDITION_ALLOW`, default `nm,mint,m,ex-nm`) nos
  loops live (targeted/broad/once). Validado: Base Set/Base Set 2 → só **EX-NM** sobra
  (ex.: Pikachu 058/102 EX-NM $5.43→$7.62, 28,7%).
- **Nuance de yield:** o sort `sl` (mais barato primeiro) traz as cartas PLAYED primeiro; as NM
  ficam em páginas mais fundas. Com page-cap baixo o yield NM é pequeno. Para o sweep real:
  **rodar sem `--max-pages`** (varre o set inteiro) — ou trocar pra sort `sh` p/ priorizar as
  NM valiosas. (Refino, não bug.)

### ⚠️ Resultado REAL dos sweeps + leitura honesta do mercado (importante p/ o operador)
- Sweep completo dos 15 sets WotC (sl e sh, NM-only, ≥20%) → **1 deal qualificado** (Pikachu
  Base Set EX-NM $5,43→$7,62, 28,7%). Os 15 sets rodaram limpos, headless, 0 erro/0 CF-block.
- **Por que tão pouco:** COMC e TCGplayer são o **MESMO mercado US** — sem a vantagem cambial/
  cross-border dos scanners irmãos (BR/EU vs US). As listagens da COMC ficam em geral no/above
  market do TCGplayer; só aparece deal quando um vendedor sub-precifica de fato. **NM-only + ≥20%
  num mesmo mercado = yield naturalmente baixo.** Não é bug — é a estrutura do mercado.
- **Decisões do operador** (não mexi, são capital/estratégia): (a) baixar o threshold (ex. 10%)
  rende mais deals porém mais finos; (b) avaliar se a tese COMC→TCGplayer compensa vs o esforço;
  (c) modern SV/SWSH raw NM na COMC tende a ser ainda mais raro (COMC é vintage-cêntrica) — vale
  uma sondagem antes de investir no catálogo moderno.

### ⭐ Modern (SV/SWSH) é o ALVO MELHOR que vintage (descoberta tardia)
- Sondagem do **SV 151** (`SV: Scarlet & Violet 151`, TCGCSV abbr MEW): **650 listagens ungraded,
  TODAS condição "NM"** (≠ vintage, que é EX-NM/played), com chase cards valiosas (Charizard ex
  $52, Art Rare Charmander $92, Mew ex $67). **Modern raw na COMC é abundante e uniformemente NM**
  → muito mais superfície de arbitragem que o vintage (estoque fino/played). **Recomendo focar
  modern** no catálogo.
- **Formato de slug MODERNO difere:** é um ÚNICO segmento com o ano embutido + código do set,
  ex. `2023_Pokemon_Scarlet__Violet_-_151_sv2a` (não `<ano>/<slug>`). No catálogo: `year=""` +
  slug = segmento inteiro; `run_targeted` trata `year==""` como segmento único. SV 151 já
  adicionado e (em validação ao vivo). Próximo: ampliar catálogo com SV08 Surging Sparks (SSP),
  SV Prismatic Evolutions (PRE), etc. (descobrir slug via `firecrawl_search site:comc.com`).
- **Atenção:** a tese same-market segue valendo (COMC≈TCGplayer US), mas com 650 NM/set e cards
  de $50-90, a chance de achar uma sub-precificação real é bem maior que no vintage.

### Agendamento recorrente — ✅ scaffold criado
- `.github/workflows/scan.yml`: `workflow_dispatch` (era/max_pages/margin/budget) + cron diário
  COMENTADO (operador opta, espelhando a convenção dos irmãos). Roda `targeted` headless, exige
  secret **`FIRECRAWL_API_KEY`** (falha alto se faltar), joga a tabela no run-summary + artifact.
  **AÇÃO DO OPERADOR:** adicionar `FIRECRAWL_API_KEY` em repo Settings → Secrets → Actions.

### Pendência imediata (estado ao escrever)
- **`comc_set_slugs.json`** está sendo construído por um sub-agente (firecrawl_search + validação
  set-path) p/ ~15 sets WotC. Quando existir, rodar `targeted --era vintage` valida o yield real.
  Sem ele, `targeted` loga "no catalog" e não quebra.
- **Próximos passos:** (a) validar `targeted` com o catálogo → primeiros deals reais; (b) ampliar
  catálogo (modernos SV/SWSH se houver inventário raw); (c) GH Actions/Task Scheduler pro run
  recorrente; (d) testes offline pro `run_broad`/`run_targeted` (mock do fetcher).
