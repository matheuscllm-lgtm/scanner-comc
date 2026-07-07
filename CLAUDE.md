# CLAUDE.md — scanner-comc

Instruções para qualquer sessão do Claude Code que trabalhe neste repositório
(inclui uma sessão da nuvem que só clonou o GitHub e não tem a memória local).
O operador é médico, **não-programador**: explique termos técnicos em linguagem
simples e seja preciso ao mesmo tempo.

**Este arquivo é a documentação técnica canônica do projeto.** O `README.md` é
minimalista **de propósito** (release público discreto: título neutro
"price-compare", sem citar COMC/Pokémon) e aponta de volta pra cá — não
"conserte" o README re-adicionando o caso de uso. Notas de sessão ficam num
`HANDOFF.md` local, fora do repositório (gitignored — a ausência dele num clone
limpo é esperada, não é erro).

## 🛰️ Convenções da frota (cross-scanner)

> **Manual completo** (repo privado): https://github.com/matheuscllm-lgtm/scanners-commons — erros comuns, referências de preço, chaves, GitHub Actions e modelo de entrega de TODOS os scanners. Cópia-mestra local (PC do operador): `C:\Users\mathe\scanners-commons\`.

Invariantes que valem para TODOS os scanners:

- **Margem BRUTA, mínimo 30%** — só `(revenda − compra)/compra`, sem nenhuma taxa embutida (frete, cartão, IOF — o operador calcula por fora).
- **Piso de relevância R$50 (~US$10) — SÓ para cartas avulsas (singles).** Produtos SELADOS não têm piso (decisão do operador, 2026-06-27); lá o único critério é a margem ≥30%.
- **Só Near Mint** — condição por match EXATO `== "NM"`, nunca substring (já vazou SP).
- **Nunca inventar preço** — fonte falhou → marca fallback/erro e segue; jamais fabrica número.
- **Nunca recomendar compra** — o scanner reporta margem, flags e fontes; a decisão de capital é do operador.
- **Entrega = tabela markdown no chat** (nunca XLSX/CSV por padrão), gerada pela ferramenta do repo — nunca montada à mão —, mostrando TODAS as linhas (aprovadas + rejeitadas). Coluna `Carta` = nome + número; coluna `Links` combinada = `[oferta](url) · [TCG/referência](url)`.
- ⚠️ **Convenção de threshold:** percentual inteiro (`30`) = MYP, Liga, eBay; fração (`0.30`) = CardTrader, COMC, Selados.

Erros recorrentes (3 famílias — detalhe no manual):

1. **Segredo/ambiente:** BOM/zero-width numa chave → crash latin-1 no header → scan "verde mas vazio". Setar sem BOM (`printf '%s' 'KEY' | gh secret set`) **e** sanitizar ao ler no código (`.strip()` NÃO tira BOM).
2. **Git:** branch ou `main` local defasado por squash-merge PARECE pendência. O teste real de "já mergeado" é `git diff --stat origin/main <branch>` estar vazio (não `git merge-base`).
3. **Honestidade de preço:** inflação de referência, fallback tratado como real, NM frouxo → sempre validar versão/condição e rotular fallback.

**Este scanner:** referência de preço = `tcgcsv.com` (campo market → mid → low, rastreado em `price_field` e sinalizado no chat) → **fallback TCGdex** (mesmo marketPrice do TCGplayer por productId, quando o tcgcsv falha num set); chave = `FIRECRAWL_API_KEY` — usada por **qualquer run no fetch-mode default `firecrawl`** (local ou nuvem); só `--fetch-mode playwright` (navegador local de verdade) dispensa a key.

## O que este projeto é

Scanner de arbitragem **COMC → TCGPlayer** de cartas avulsas de Pokémon (o 5º
scanner de singles, irmão de CardTrader / MYP / Liga). Procura cartas listadas
na COMC mais baratas que o preço habitual no TCGPlayer e reporta os melhores
deals por **margem bruta**. Tese atual = **VALUE-BUY**: comprar boas cartas com
desconto e potencial de valorização (segurar), não só flip imediato. Pode rodar
**grátis** via navegador real (Playwright headful) ou via Firecrawl (o
fetch-mode default, que consome créditos da key).

## 📤 COMO ENTREGAR RESULTADOS (regra dura — não improvisar)

Quando o operador pedir "resultados", "deals", "panorama" ou similar:

1. **Entrega = uma tabela markdown colada AQUI no chat.** Nunca mande arquivo
   (`.csv`/`.xlsx`/`.json`) por padrão. O operador lê na conversa. Só gere/envie
   arquivo se ele **pedir explicitamente** ("me manda o CSV").
2. **A entrega sai da ferramenta `comc_summary.py` — NUNCA monte uma tabela à mão**
   (espelho do `myp_summary.py` do MYP; substitui a instrução antiga de regenerar
   via `render_markdown` na mão):
   ```bash
   python comc_summary.py results/comc_deals_<era>_latest.json -o results/comc-grupo<N>-<data>.md --group <N>
   ```
   Cole o `.md` gerado **VERBATIM**. Ele traz o cabeçalho com contagens + a linha
   de honestidade "Cobertura de preço market" (market/mid/low) e DUAS seções —
   🟢 deals confiáveis (confiança ≥0.90 E preço market) e ⚠️ validar manualmente
   (confiança baixa e/ou preço mid/low, incluindo o balde low-confidence) — todas
   ordenadas por margem desc. A formatação das linhas tem UMA fonte:
   `comc_scanner/reporter.py` (`render_rows_table`/`render_row_line`, as mesmas
   funções do `render_markdown` que o scanner imprime a cada flush). Montar à mão
   arrisca esquecer um link ou a flag e diverge do arquivo gravado.
3. **Mostre TODAS as linhas** (ordenadas por margem desc.), não uma amostra curada.
4. Cada linha traz, automaticamente:
   - `Card` = **nome + número de coleção** da carta (ex.: `Pikachu 173/165`);
   - `Links` = **dois links clicáveis numa coluna só** — **[oferta](url COMC)** (a
     listagem na COMC) **·** **[referência](url TCGPlayer)** (onde conferir o
     preço). Formato canônico cross-scanner (igual ao MYP/Liga); lidos do deal,
     nunca inventados (`—` se faltarem);
   - `Flag` = `ok` ou **`validar`** (match com confiança < 0.90, constante
     `TRUST_CONFIDENCE` — **suspeito, conferir manualmente**; a linha aparece
     sempre, nunca é escondida). Quando o preço de referência não é o campo
     `market` (venda real observada), a flag ganha o sufixo **`preço:<campo>`**
     (ex.: `preço:mid`) — sinalização honesta de preço menos confiável.
5. **Não recomende comprar.** O scanner reporta dados; a decisão de capital é do
   operador. Pode comentar quais linhas estão `validar`, mas não diga "compre".

## Como rodar

> 🎯 **Skill `scan-comc`** (`.claude/skills/scan-comc/SKILL.md`): quando o
> operador pedir pra "rodar o COMC", o agente **pergunta qual dos 4 grupos**
> rodar (2 grupos SV moderno + 2 grupos WotC vintage — fonte canônica:
> `comc_scanner/groups.py`), roda um por vez e entrega via `comc_summary.py`.

```bash
# preparo (1ª vez):
pip install -r requirements.txt
playwright install chromium     # só pro fetch ao vivo via navegador local
cp .env.example .env            # variáveis opcionais (defaults comentados no arquivo)

# listar os 4 grupos canônicos (sem rede):
python -m comc_scanner list-groups

# rodar POR GRUPO (allowlist + era derivadas do grupo; SV=recent, WotC=vintage);
# piso $10 + margem 0.30 já são default:
python -m comc_scanner targeted --group 1 --fetch-mode playwright --headful --no-sheets --restart

# rota antiga por era continua funcionando (backward compat):
python -m comc_scanner targeted --era recent  --fetch-mode playwright --no-sheets --restart
python -m comc_scanner targeted --era vintage --fetch-mode playwright --no-sheets --restart
```

`--group` e `--sets` são mutuamente exclusivos; `--group` dispensa `--era`
(se passar um `--era` conflitante, o grupo manda e sai um warning).
Variações úteis: `--min-margin 0.20` (afrouxa o limiar p/ value-buy),
`--chase-only` (só raridades de perseguição), `--min-margin 0.0` (captura a
distribuição inteira pra ler depois). `python -m comc_scanner --help` lista tudo.

**Threshold `--min-margin` é FRAÇÃO** (`0.30` = 30%), igual ao CardTrader e ao
contrário do MYP/Liga — ver a tabela de convenções no bloco da frota acima.

### Subcomandos da CLI (todos em `comc_scanner/__main__.py`)

| Subcomando | O que faz |
|---|---|
| `targeted` | scan por set (`--sets`) ou por **grupo** (`--group N`), usando os slugs de `comc_set_slugs.json` (o modo do dia a dia) |
| `list-groups` | lista os 4 grupos canônicos de sets (`comc_scanner/groups.py`) — sem rede |
| `broad` | varredura ampla da vitrine COMC por páginas (cursor de página próprio) |
| `run` | loop contínuo incremental (um chunk por vez, sem parar) |
| `once` | escaneia UM chunk, grava resultado e sai |
| `refresh-prices` | força re-download do snapshot de preços do tcgcsv |
| `dry-run` | casa/reporta uma fixture local (`--listings` JSON ou `--html` salvo), sem COMC ao vivo |
| `capture` | salva uma página COMC renderizada em disco (precisa de Playwright) |
| `warm` | **aquecimento headful**: abre janela do navegador pra limpar o Cloudflare uma vez; depois disso runs `--fetch-mode playwright` continuam **HEADFUL** (o código força headful — Turnstile só resolve em navegador real com janela; em servidor exige display virtual), mas ficam **grátis e sem intervenção** (o cookie `cf_clearance` fica no perfil e é reusado — sem Firecrawl) |
| `parse-file` | imprime os listings parseados de uma página COMC salva (`--html`) |
| `validate-slugs` | valida ao vivo entradas pendentes de `comc_set_slugs.json` (scrape da página 1 de cada; `--revalidate` re-testa as já validadas) |

Flags comuns a todos: `--era` (`recent`/`middle`/`vintage`/`all` — corte:
vintage ≤ 2010, middle ≤ 2019; ajustável via env `ERA_VINTAGE_MAX_YEAR`/
`ERA_MIDDLE_MAX_YEAR`), `--top-n`, `--interval`, `--min-margin`, `--min-price`,
`--chase-only`, `--min-confidence`, `--margin-mode gross|markup`, `--sets`
(allowlist), `--group N` (grupo canônico; mutuamente exclusivo com `--sets`,
dispensa `--era`), `--max-pages`, `--max-sets-per-chunk`, `--max-run-seconds`,
`--condition` (banda COMC, ex. `EX-NM`), `--include-graded`,
`--fetch-mode firecrawl|playwright`, `--headful`, `--no-sheets`.

- **Checkpoint/retomada:** o progresso por era fica em `.cache/progress/<era>.json`
  (`ChunkCursor` em `segments.py`). `--restart` = ignora o cursor salvo e
  recomeça a era do zero; sem ele, o scan retoma de onde parou.
- **Configuração por env vars:** `config.py` lê ~32 variáveis de ambiente (via
  `.env` local — `DEFAULT_ERA`, `COMC_CONDITION_BAND`, `COMC_FETCH_MODE`,
  `TCGDEX_FALLBACK`, `FIRECRAWL_*`, `GOOGLE_SHEETS_*` etc.); `.env.example` na
  raiz lista quase todas com os defaults (`TCGDEX_FALLBACK` e
  `COMC_EXCLUDE_VARIANTS` existem só como env, sem entrada no exemplo). O `.env`
  é gitignored (nunca versionar chave).
- **Google Sheets (opcional):** o reporter pode empurrar os deals pra uma
  planilha Google (`GOOGLE_SHEETS_CREDENTIALS_JSON`/`GOOGLE_SHEETS_ID`/
  `GOOGLE_SHEETS_WORKSHEET`). `--no-sheets` desliga esse push — é o que os
  comandos de exemplo fazem. A entrega ao operador continua sendo a tabela no
  chat, nunca a planilha.
- **Skill `/auto`** (`.claude/commands/auto.md`): agente master autônomo da
  frota — modo ponta a ponta (corrigir + aprimorar, PR, checkpoints). É a única
  skill/command deste repo.

### GitHub Actions (existem, mas SEM agendamento — ver "Convenções que não mudam")

- **`.github/workflows/scan.yml` ("COMC Scan")**: scan funcional **headless via
  Firecrawl** na nuvem. Disparo **manual** (`workflow_dispatch`) com inputs
  `era` / `max_pages` / `min_margin` / `max_run_seconds`. Exige o secret
  `FIRECRAWL_API_KEY` (sem ele o run falha alto — o scanner nunca fabrica dado).
  O cron diário está **COMENTADO de propósito** (opt-in do operador, que
  controla o gasto de créditos).
- **`.github/workflows/tests.yml` ("tests")**: pytest offline em push na `main`,
  PR e dispatch (Python 3.12, sem browser, sem secrets — a fixture commitada
  substitui a vitrine ao vivo).

## Convenções que não mudam

- **Recorrência é MANUAL** (decisão do operador, 2026-06-09): o operador aciona
  o scan; **não crie agendamento automático** (Task Scheduler, cron local, nem
  descomentar o cron do `scan.yml`). Os workflows manuais acima **não violam** a
  regra — o que é proibido é o disparo automático recorrente, e por isso o cron
  do `scan.yml` fica comentado.
- **NM-only** (via banda `EX-NM` + allowlist por igualdade — ver a nuance no
  fim desta seção) e **English-only** são invariantes do pipeline: o browse por
  set-path da COMC devolve sub-impressões em todas as línguas (japonês,
  coreano...), mas o preço do tcgcsv é do produto EM INGLÊS — casar JP/KR com
  preço EN geraria falso positivo, então `pipeline.py` descarta listings cujo
  set nomeia outro idioma (desligável só via `COMC_EXCLUDE_VARIANTS=""`).
- ⚠️ **Margem sobre a venda por DEFAULT** (divergência real vs. a fórmula da
  frota — preservar): `gross_margin = (ref_TCG − preço_COMC) / ref_TCG`
  (`comc_scanner/margin.py`), limiar **30%** (fração `0.30`), **sem** taxas
  embutidas (frete/câmbio/IOF o operador calcula por fora). É **mais estrito**
  que o markup da frota (`0.30` sobre a venda ≈ **42,8%** de markup). Para a
  fórmula da frota `(revenda − compra)/compra`, use `--margin-mode markup`.
  Piso de preço **US$ 10** (≈ regra "carta valiosa ≥ R$50"). **Nunca recomendar
  compra** — idem bloco da frota.
- **Chave sanitizada contra BOM**: `config.py::clean_secret` remove BOM (U+FEFF)
  e zero-width (U+200B) da `FIRECRAWL_API_KEY` ao ler — a família de erro nº 1
  da frota já está tratada no código; mantenha esse guard.

### Como o invariante NM se traduz na COMC (nuance deste repo)

A COMC não tem um facet "NM" puro: a vitrine é filtrada pela **banda de
condição** `EX-NM` (a banda near-mint da COMC — `comc_condition_band` em
`config.py`, env `COMC_CONDITION_BAND`), e a condição por listing é aceita só
se o valor, em minúsculas, estiver **exatamente** na allowlist fechada
`("nm", "mint", "m", "ex-nm", "exnm", "near mint")` (`comc_condition_allow`).
Ou seja: o espírito do invariante da frota se mantém — **igualdade contra uma
lista fechada de tokens near-mint, NUNCA substring** (é assim que LP/SP não
vazam) —, só que o mecanismo é banda + allowlist, não a string literal `"NM"`.

## Testes

```bash
python -m pytest tests/    # 110 testes — offline, sem rede, sem browser
```

(Contagem verificada em 2026-07-07 via `pytest --collect-only`; se divergir,
vale o que o comando disser.) `tests/fixtures/` traz páginas COMC reais salvas;
`tests/test_reporter.py` trava o formato canônico de entrega.

## Arquitetura

```
comc_scanner/
  __main__.py          CLI: subcomandos (targeted/list-groups/broad/run/once/warm/...) + flags
  config.py            Settings + ~30 env vars + clean_secret (anti-BOM) + paths (.cache/, results/)
  groups.py            os 4 grupos canônicos de sets (2 SV moderno + 2 WotC vintage) — usados por --group
  pipeline.py          orquestra scan → match → filtros (NM/EN) → flush de resultados
  comc_scraper.py      navegação COMC via Playwright (sempre HEADFUL — o código força; warm-up limpa o CF e o cf_clearance é reusado do perfil)
  firecrawl_client.py  fetch via Firecrawl (o fetch-mode DEFAULT; fura o Cloudflare na nuvem)
  segments.py          eras (recent/middle/vintage) + ChunkCursor (checkpoint retomável por era)
  comc_set_slugs.json  slugs de set validados na COMC (28 sets: WotC clássicos + era SV)
  tcgcsv_client.py     snapshot diário de preços TCGPlayer via tcgcsv.com (market → mid → low)
  tcgdex_client.py     fallback TCGdex (mesmo marketPrice por productId, quando o tcgcsv falha num set)
  tcg_index.py         índice de cartas/preços de referência pro matcher
  matcher.py           casa listing COMC ↔ carta TCG (confiança 0-1; <0.90 = flag validar)
  normalize.py         normalização de nomes/números/sets
  margin.py            cálculo de margem (gross/markup)
  reporter.py          render_markdown + render_rows_table/render_row_line (formatação de linha, fonte única) + JSON/CSV + push opcional Google Sheets
  models.py            dataclasses (listing, deal, ...)
  logging_setup.py     logging
comc_summary.py        ENTREGA canônica ao operador (XLSX/JSON de scan → markdown por grupo, 2 seções); espelho do myp_summary.py
tests/                 suíte offline (fixtures reais commitadas)
results/               saídas de scan (gitignored; só o .gitkeep é versionado)
```

## Fluxo de desenvolvimento e segurança

- Mudança de código = **branch + PR** (não dar push direto na `main`); teste
  real de "já mergeado" = família de erro nº 2 do bloco da frota.
- **Dados de scan não entram no repo** (release público): `results/*` é
  gitignored, assim como `.env`, caches, perfis de navegador e cookies/estado de
  sessão (`storage_state*.json`, `cookies*.json` — nunca commitar segredo nem
  cookie de sessão). `HANDOFF.md` (notas locais) também é gitignored.
- Secrets: `FIRECRAWL_API_KEY` local no `.env`; na nuvem, como secret do GitHub
  Actions. Setar sempre sem BOM (ver família de erro nº 1).

## Estado, pendências e histórico

- **Versão: 0.2.0** (`pyproject.toml` + `CHANGELOG.md`, 2026-06-17 — entrega
  canônica com 2 links + flag `validar`). 0.1.0 = versão inicial (scanner
  COMC → TCGPlayer, tese value-buy, 28 sets validados, Playwright headful
  grátis + Firecrawl, suíte offline).
- ⚠️ **CHANGELOG desatualizado**: há features mergeadas DEPOIS de 0.2.0 sem bump
  nem entrada — fallback TCGdex + cross-validação de set-total no matcher (#8),
  sufixo `preço:<campo>` na Flag do chat (#9), fixes de revisão (#10),
  sanitização BOM da key Firecrawl (#13). No próximo bump, registrar essas
  entradas no `CHANGELOG.md`.
- Detalhe de cada mudança: `CHANGELOG.md` + histórico de PRs no GitHub
  (`matheuscllm-lgtm/scanner-comc`).
