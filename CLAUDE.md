# CLAUDE.md — scanner-comc

Instruções para qualquer sessão do Claude Code que trabalhe neste repositório
(inclui uma sessão da nuvem que só clonou o GitHub e não tem a memória local).
O operador é médico, **não-programador**: explique termos técnicos em linguagem
simples e seja preciso ao mesmo tempo.

**Este arquivo é a documentação técnica canônica do projeto.** O `README.md` é
minimalista **de propósito** (release público discreto: título neutro
"price-compare", sem citar COMC/Pokémon) e aponta de volta pra cá. Notas de
sessão ficam num `HANDOFF.md` local, fora do repositório (gitignored).

## 🛰️ Convenções da frota (cross-scanner)

> **Manual completo** (repo privado): https://github.com/matheuscllm-lgtm/scanners-commons — erros comuns, referências de preço, chaves, GitHub Actions e modelo de entrega de TODOS os scanners. Cópia-mestra local (PC do operador): `C:\Users\mathe\scanners-commons\`.

Invariantes que valem para TODOS os scanners:

- **Piso de relevância R$50 (~US$10)** para cartas avulsas.
- **Só Near Mint** (cartas soltas) — condição por match EXATO `== "NM"`, nunca substring.
- **Nunca inventar preço** — fonte falhou → marca/descarta e segue; jamais fabrica número.
- **Nunca recomendar compra** — o scanner reporta; a decisão de capital é do operador.
- **Entrega = tabela markdown no chat** (nunca XLSX/CSV por padrão), gerada pela ferramenta do repo — nunca montada à mão —, mostrando TODAS as linhas. Coluna `Carta` = nome + número; coluna `Links` = `[oferta](url) · [referência](url)`.
- ⚠️ **Threshold deste scanner = percentual INTEIRO** (`--min-discount 20`, env `MIN_DISCOUNT_PERCENT`), como MYP/Liga/eBay. (Até a v0.2 era fração `0.30`; mudou na consolidação de 2026-09-02.)

Erros recorrentes (3 famílias — detalhe no manual):

1. **Segredo/ambiente:** BOM/zero-width numa chave → crash. `config.clean_secret` remove.
2. **Git:** `main` local defasado por squash-merge PARECE pendência; teste real = `git diff --stat origin/main <branch>` vazio.
3. **Honestidade de preço:** inflação de referência, fallback tratado como real, NM frouxo → sempre validar versão/condição e rotular fallback.

## O que este projeto é (v0.3, scanner ÚNICO — spec do operador 2026-09-02)

Scanner de arbitragem da **COMC** para cartas de Pokémon, num único fluxo:

```
COMC (set-path browse, 2 passadas por set: cartas soltas + slabs)
 → só Pokémon da lista icônica (comc_scanner/iconic_pokemon.csv, top-100 do operador)
 → identificar a carta (matcher: set + número + total do set + nome; confiança 0-1)
 → referência de preço:  raw  = TCGplayer market (tcgcsv → fallback TCGdex)
                         slab = PriceCharting, preço da NOTA (PSA 10, BGS 10, CGC 10 Pristine…)
 → desconto = (ref − COMC)/ref ≥ MIN_DISCOUNT_PERCENT (20)
 → status OK / MATCH_REVIEW → ranking (ROI → desconto → lucro → popularidade)
 → results/comc_deals_<escopo>_latest.json → comc_summary.py (tabela modelo MYP)
```

- **Raw** = condição por igualdade **por era**: moderno só `NM`; vintage WotC `NM` ou
  `EX-NM` (a COMC gradua o raw WotC como EX-NM — decisão do operador 2026-09-02).
- **Slab** = só notas da allowlist `GRADED_ALLOW` (default PSA 10/9, BGS 10/9.5,
  TAG 10/9.5, **CGC só 10 Pristine**). Um slab NUNCA é comparado com preço de carta
  solta. Referência do slab, nesta ordem: (1) **coluna exata** da certificadora+nota
  na página do PriceCharting (só existe na nota 10: PSA 10, BGS 10, **TAG 10**, ACE 10,
  SGC 10, CGC 10 Pristine) — pode ser `OK`; a mediana das vendas recentes da mesma nota
  vai junto como sanidade (coluna >30% longe → `MATCH_REVIEW · ref÷vendas`); (2) sem
  coluna exata (**qualquer nota 9 ou 9.5** — "Grade 9"/"Grade 9.5" do PC são buckets
  genéricos que misturam certificadoras) → **mediana de ≥3 vendas concluídas dos
  últimos 180 dias** da mesma certificadora+nota, cujo título cite SÓ essa nota
  (tabelas de vendas eBay da própria página; `Ref` = `PC vendas PSA 9 (n=…, mês..mês)`)
  — pode ser `OK`; (3) sem amostra → bucket genérico **só para triagem** (`PC GRADE
  9.5~`, sempre `MATCH_REVIEW`, nunca oportunidade de compra); (4) nada → descarta.
- **Fonte falhou ≠ sem venda**: rede/bloqueio/página sem tabelas no PriceCharting vira
  `PcError` → contador `Slabs com ERRO na fonte` (nunca "sem referência"); 5 falhas
  seguidas suspendem a passada de slabs no run; página de bloqueio/vazia NUNCA entra no
  cache do dia. Erro interno numa listagem é contado (`listing_errors`) e pulado; o JSON
  `_latest` é gravado SEMPRE (`finally`), e em `--group all` um grupo quebrado não
  cancela os seguintes.
- **Só dados do dia**: sem cursor de retomada; snapshot tcgcsv re-baixado a cada run;
  cache PriceCharting em `.cache/pc/<AAAA-MM-DD>/`. Cada run começa do zero.
- Roda **grátis**, no PC do operador, via Chrome real **headful** (patchright resolve o
  Cloudflare Turnstile; headless NUNCA fura). Recorrência **manual**.

## 📤 COMO ENTREGAR RESULTADOS (regra dura — não improvisar)

1. **Entrega = uma tabela markdown colada AQUI no chat.** Nunca arquivo por padrão.
2. **Sai da ferramenta `comc_summary.py` — NUNCA monte tabela à mão:**
   ```bash
   python comc_summary.py results/comc_deals_grupo<N>_latest.json -o results/comc-grupo<N>-<data>.md --group <N>
   ```
   Cole o `.md` **VERBATIM**. Ele traz cabeçalho (contagens, limiares, slabs aceitos,
   **funil** do scan) e DUAS seções — 🟢 **OK** e ⚠️ **MATCH_REVIEW** (validar
   manualmente) — ambas na ordem do ranking. A formatação de linha tem UMA fonte:
   `comc_scanner/reporter.py` (`render_rows_table`/`render_row_line`/`classify_row`).
3. **Mostre TODAS as linhas.**
4. Colunas: `# | Desconto% | ROI% | COMC$ | Ref$ | Lucro$ | Pokémon | Carta | Set | Tipo | Ref | Conf | Status | Links`
   - `Tipo` = `Raw NM` ou a nota (`PSA 10`, `CGC 10 Pristine`);
   - `Ref` = `TCG market|mid|low` ou `PC <nota>` (`~` = proxy);
   - `Status` = `OK` ou `MATCH_REVIEW · motivos` (confiança <0.90, `preço:mid/low`, `ref~proxy`);
   - `Links` = `[oferta](COMC) · [referência](TCGplayer p/ raw · PriceCharting p/ slab)`.
5. **Não recomende comprar.**

## Como rodar

> 🎯 **Skill `scan-comc`** (`.claude/skills/scan-comc/SKILL.md`): ao pedirem pra
> "rodar o COMC", o agente **pergunta qual dos 4 grupos** (ou `all`), roda e entrega
> via `comc_summary.py`.

```bash
pip install -r requirements.txt && playwright install chromium   # 1ª vez
python -m comc_scanner list-groups                               # sem rede
python -m comc_scanner scan --group 1                             # raw + slabs, 20%, lista icônica
python -m comc_scanner scan --group all                           # 4 grupos em sequência
python -m comc_scanner scan --sets "Base Set,Jungle" --era vintage
```

Flags do `scan`: `--group N|all` xor `--sets` (igualdade exata do nome/alias/abreviação
do set — nunca substring: `"Base Set"` não pega "Base Set 2"; `"151"` NÃO casa
"SV: Scarlet & Violet 151" — use o nome completo, `"Scarlet & Violet 151"` ou `--group`); `--era`; `--min-discount 20` (inteiro); `--min-price 10`; `--max-price`
(teto de orçamento por carta, corta antes do PriceCharting); `--max-english N`
(encerra o set após N listagens INGLESAS válidas — japonesas não contam; 0 = todas as
páginas); `--raw-only` / `--slabs-only`; `--all-pokemon`; `--chase-only`;
`--min-confidence`; `--max-pages`; `--max-run-seconds`; `--interval`; `--top-n`.
Outros subcomandos: `list-groups`, `validate-slugs [--revalidate]`, `warm`, `capture`.
`--headful`/`--restart` são aceitos por compatibilidade e não fazem nada (sempre
headful; sempre do zero).

Configuração por env (`.env.example` lista tudo): `MIN_DISCOUNT_PERCENT`,
`MIN_COMC_PRICE`, `ICONIC_ONLY`, `SCAN_RAW`, `SCAN_SLABS`, `GRADED_ALLOW`,
`COMC_CONDITION_ALLOW`, `TCGCSV_FORCE_REFRESH`, `PC_CACHE_DIR`…

## Convenções que não mudam

- **Recorrência é MANUAL** (operador, 2026-06-09): não criar Task Scheduler / cron /
  GitHub Actions de scan. (O workflow `scan.yml` via Firecrawl foi removido na v0.3.)
- **NM-only** (raw) por igualdade com `COMC_CONDITION_ALLOW` (moderno: `nm`) /
  `COMC_CONDITION_ALLOW_VINTAGE` (WotC: `nm,ex-nm`) e
  **English-only** (descarta sub-impressões JP/KR/…): casar outra condição/idioma com o
  preço EN NM seria falso positivo.
- **Desconto sobre a referência**: `(ref − COMC)/ref` (`margin.py`), limiar inteiro
  `MIN_DISCOUNT_PERCENT` (default 20). ROI `(ref − COMC)/COMC` e lucro US$ vêm de
  `ranking.compute_metrics` e só ordenam. Sem taxas embutidas.
- **Lista de Pokémon fora do código** (`iconic_pokemon.csv`); nada hardcoded.
- **Referência de slab = PriceCharting por nota**; TCGplayer não precifica slab.

## Testes

```bash
python -m pytest tests/    # 157 testes — offline, sem rede, sem browser
```

`tests/fixtures/` traz páginas REAIS: vitrine ungraded (2026-06-08), duas vitrines
`aGraded` (151 e Base Set, 2026-09-02) e uma página/busca do PriceCharting.

## Arquitetura

```
comc_scanner/
  __main__.py            CLI: scan | list-groups | validate-slugs | warm | capture
  config.py              Settings (+ env) — MIN_DISCOUNT_PERCENT, GRADED_ALLOW, ICONIC_ONLY…
  groups.py              os 4 grupos canônicos de sets (2 SV + 2 WotC)
  comc_set_slugs.json    slugs de set validados na COMC (28 sets)
  iconic_pokemon.csv     lista do operador (rank, pokemon, score, sources) — EDITÁVEL
  iconic.py              match por palavra inteira contra a lista
  grading.py             parse da nota do slab (/Graded/<grader>/<nota> + título) + allowlist + coluna PC
  comc_scraper.py        navegação COMC via patchright headful; parse de raw E slabs
  pipeline.py            Scanner.run_scan (2 passadas/set) + process_listing (funil único) + FunnelStats
  matcher.py / normalize.py / tcg_index.py   identificação da carta no TCGplayer (confiança 0-1)
  tcgcsv_client.py / tcgdex_client.py        referência raw (market → mid → low; fallback TCGdex)
  pricecharting_client.py                    referência de slab por nota (busca + guardas nome/número/set)
  margin.py              desconto (ref − comc)/ref
  ranking.py             métricas (desconto, ROI, lucro) + ordem de ranking
  reporter.py            tabela canônica + classify_row (OK/MATCH_REVIEW) + JSON/CSV + funil
  models.py              dataclasses (listing com grade, deal com pokemon/ref_source/status)
comc_summary.py          ENTREGA canônica (JSON → markdown, 2 baldes, funil)
tests/                   suíte offline (fixtures reais)
results/                 saídas (gitignored)
```

## Fluxo de desenvolvimento

- Código = **branch + PR**; nunca push direto na `main`.
- Dados de scan, `.env`, caches e perfis de navegador não entram no repo.
- Versão: **0.3.0** (`pyproject.toml` + `CHANGELOG.md`, 2026-09-02).
