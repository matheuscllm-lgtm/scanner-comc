# HANDOFF — Scanner de arbitragem COMC → TCGPlayer (Pokémon)

> Documento de transferência para retomar o trabalho em uma nova sessão (inclusive via
> Claude Code remoto no celular). Última atualização: 2026-06-08.

---

## 0. TL;DR (estado atual)

- **O que é:** um scanner em Python que acha cartas Pokémon listadas na **COMC** por preço
  abaixo do **preço de mercado do TCGPlayer**, e lista os **top 50 deals por margem bruta**
  (`> 20%`, sem preço mínimo), emitindo **resultados parciais ~a cada 1h** enquanto roda.
- **Onde está:** branch **`claude/wizardly-maxwell-gnhfe3`**, **PR #1 (draft)**:
  https://github.com/matheuscllm-lgtm/scanner-comc/pull/1
- **Build:** ✅ código completo e empurrado · ✅ **16/16 testes offline** · ✅ **CI verde**
  (`.github/workflows/tests.yml`, job `offline-tests`).
- **Verificado ao vivo:** TCGCSV (217 sets, matching real), `dry-run` completo, `robots.txt`.
- **NÃO verificado ao vivo:** a **raspagem da COMC** (o Cloudflare bloqueia o sandbox; precisa
  de navegador real + seus cookies + ajuste dos seletores contra uma página real).
- **Próximo passo que destrava tudo:** capturar **uma página real da COMC** e ajustar os
  seletores (ver §6). É a única coisa que não pôde ser feita no ambiente isolado.

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
- ✅ **16/16 testes offline** e **CI verde** no PR.
- ✅ Novos comandos `parse-file` / `capture` / `dry-run --html` funcionam (no fixture placeholder).

**Pendente (NÃO pôde ser feito no ambiente isolado):**
- ❌ **Raspagem ao vivo da COMC**: o Cloudflare bloqueia o sandbox e não há display/cookies aqui.
- ❌ **Seletores de listagem da COMC**: o DOM exato **não é público**; os seletores em
  `comc_scraper.py` (`_parse_dom`/`_parse_jsonld`) são **best-effort** e precisam ser calibrados
  contra uma página real — principalmente para extrair o **`set_hint`** (sem ele o match não casa).
- ⛔ **Google Sheets real**: só degrada p/ CSV até configurar credenciais (`GSHEETS_*` no `.env`).

---

## 6. Os 2 pontos abertos e COMO resolver

### 6.1 Seletores HTML da COMC (o bloqueador principal)
A forma de resolver é **calibrar contra uma página real**. O ferramental já está no código:

```bash
# 1) Capturar uma página renderizada (logado, passando o Cloudflare):
python -m comc_scanner capture --headful --out tests/fixtures/comc_sample.html \
    --url "https://www.comc.com/Cards/Pokemon,sl,fb,aUngraded,rCOMC,gEX-NM,i100,p1"
# 2) Ver o que o parser extrai (nome/preço/número/condição/set):
python -m comc_scanner parse-file --html tests/fixtures/comc_sample.html
# 3) Ajustar _parse_dom() em comc_scraper.py até extrair tudo (INCLUSIVE set_hint) e validar
#    o pipeline completo (matching real vs preços do TCG) contra a página salva:
python -m comc_scanner dry-run --era vintage --html tests/fixtures/comc_sample.html
```
> `tests/fixtures/comc_sample.html` hoje é um **placeholder** (JSON-LD sintético). Substitua por
> uma captura real. Se não conseguir rodar o `capture`, basta salvar o HTML da página pelo
> navegador (ou colar o HTML de um card no chat) que dá pra ajustar os seletores.

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
