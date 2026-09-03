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
 → referência de preço:  raw NM/EX-NM = TCGplayer market (tcgcsv → fallback TCGdex)
                         raw LP       = mediana de ≥3 vendas "LP" da mesma carta (PriceCharting)
                         slab         = mediana de vendas da MESMA certificadora+nota+variante
 → desconto = (ref − COMC)/ref ≥ MIN_DISCOUNT_PERCENT (20)
 → status OK / MATCH_REVIEW → ranking (ROI bruto → desconto → spread → popularidade)
 → results/comc_deals_<escopo>_latest.json → comc_summary.py (tabela modelo MYP)
```

- **Raw** = condição por igualdade **por era**: WotC (≤2003, `ERA_VINTAGE_MAX_YEAR`)
  `NM` ou `EX-NM`; 2004+ só `NM` — contra o TCGplayer market. **LP** entra SÓ com
  referência LP: mediana de ≥3 vendas concluídas cujo título diga `LP`/`Lightly Played`
  (sem nota, sem outra condição, mesma variante); pré-filtro seguro antes da consulta:
  `preço COMC ≤ ref NM × (1 − desconto mín.)` (o NM é só TETO, nunca a comparação);
  sem amostra → `lp_no_reference`. **Nunca comparar LP com NM.** `LP_WITH_REFERENCE=false` desliga.
- **Slab** = só notas da allowlist `GRADED_ALLOW` (default PSA 8/9/10, CGC 9/9.5/10 Gem/
  10 Pristine, BGS 9/9.5/10/10 Black Label, SGC 9/9.5/10, TAG 9.5/10). Um slab NUNCA é
  comparado com preço de carta solta. **Referência = mediana de vendas concluídas** (eBay
  via PriceCharting) da MESMA carta, variante, idioma, certificadora, nota e subcategoria
  (BGS 10 Black ≠ BGS 10; CGC 10 Pristine ≠ Gem Mint; TAG 10 ≠ TAG 9.5) — título cita
  SÓ essa nota e o mesmo conjunto de tokens de variante (reverse, 1st, shadowless…).
  Janelas: ≥3 vendas em 180 d → referência válida (`OK`); ≥3 só em 365 d → válida com
  nota `baixa-liquidez(365d)`; 1–2 vendas → `MATCH_REVIEW · vendas<3`; 0 → sem
  referência, sem oportunidade (`slab_no_reference`). **Colunas do PriceCharting (mesmo
  "PSA 10") e buckets genéricos ("Grade 9") NUNCA geram referência** — a coluna exata só
  entra como sanidade (`coluna÷vendas` → MATCH_REVIEW se >30% longe da mediana).
  Nota vizinha/variante diferente nunca é proxy. JP/CN/KR ficam para uma fase à parte
  (só comparáveis com vendas do mesmo idioma).
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
4. Colunas: `# | Desconto% | ROI bruto% | COMC$ | Ref$ | Spread$ | Pokémon | Carta | Set | Tipo | Ref | Conf | Status | Links`
   (nunca "lucro": Spread$ = ref − COMC bruto, sem taxas; ROI bruto% = spread/COMC)
   - `Tipo` = `Raw NM|EX-NM|LP` ou a nota (`PSA 10`, `CGC 10 Pristine`, `BGS 10 Black Label`);
   - `Ref` = `TCG market|mid|low` ou `PC vendas <nota|LP> (n=…, mês..mês)`;
   - `Status` = `OK` ou `MATCH_REVIEW · motivos` (confiança <0.90, `preço:mid/low`,
     `vendas<3(n=…)`, `coluna÷vendas`) + nota `baixa-liquidez(365d)`;
   - `Links` = `[oferta](COMC) · [referência](página da carta no PriceCharting — raw, LP e slab;
     raw cai no TCGplayer só se a carta não tiver página no PC)`. O PREÇO raw segue o TCGplayer market.
5. **Não recomende comprar.**

## Como rodar

> 🎯 **Skill `scan-comc`** (`.claude/skills/scan-comc/SKILL.md`): ao pedirem pra
> "rodar o COMC", o agente **pergunta qual dos 12 grupos** (ou `all`), roda e entrega
> via `comc_summary.py`.

```bash
pip install -r requirements.txt && playwright install chromium   # 1ª vez
python -m comc_scanner list-groups                               # sem rede
python -m comc_scanner scan --group 1                             # raw + slabs, 20%, lista icônica
python -m comc_scanner scan --group all                           # 12 grupos em sequência (1999-2023)
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
- **NM-only** (raw) por igualdade com `COMC_CONDITION_ALLOW` (2004+: `nm`) /
  `COMC_CONDITION_ALLOW_VINTAGE` (WotC ≤2003: `nm,ex-nm`); LP só com referência LP própria; e
  **English-only** (descarta sub-impressões JP/KR/…): casar outra condição/idioma com o
  preço EN NM seria falso positivo.
- **Desconto sobre a referência**: `(ref − COMC)/ref` (`margin.py`), limiar inteiro
  `MIN_DISCOUNT_PERCENT` (default 20). ROI bruto `(ref − COMC)/COMC` e spread US$ vêm de
  `ranking.compute_metrics` e só ordenam. Sem taxas embutidas. **Diagnóstico** (operador):
  `scan --group all --min-price 5 --min-discount 10` + `comc_summary.py … --sensitivity 10,15,20`
  → faixas 10–14,99% e 15–19,99% são diagnóstico, NÃO oportunidade; ≥20% = candidato.
- **Slug de set = path ASCII exato da COMC** (`<ano>/Pokemon_<Série>_-_<Set>_-_Base`, sem
  acento). Slug com acento ou inexistente cai numa **categoria-pai** (o ano inteiro) e
  mistura sets — foi assim com o Neo Revelation antigo (paginação infinita) e com
  `Pokémon_EX_Hidden_Legends`. `validate-slugs` só valida se ≥80% da página 1 for do
  próprio set (`page1_own_share` no catálogo); a guarda de paginação é a segunda rede.
- **Lista de Pokémon fora do código** (`iconic_pokemon.csv`); nada hardcoded.
- **Referência de slab = PriceCharting por nota**; TCGplayer não precifica slab.

## Testes

```bash
python -m pytest tests/    # 161 testes — offline, sem rede, sem browser
```

`tests/fixtures/` traz páginas REAIS: vitrine ungraded (2026-06-08), duas vitrines
`aGraded` (151 e Base Set, 2026-09-02) e duas páginas + uma busca do PriceCharting
(Charizard ex 151; Charizard 4/102 Base Set com 375 vendas, títulos LP e PSA 8).

## Arquitetura

```
comc_scanner/
  __main__.py            CLI: scan | list-groups | validate-slugs | warm | capture
  config.py              Settings (+ env) — MIN_DISCOUNT_PERCENT, GRADED_ALLOW, ICONIC_ONLY…
  groups.py              os 12 grupos canônicos de sets (SV, WotC, EX, DP/Platinum, HGSS/BW, XY, SM, SWSH)
  comc_set_slugs.json    slugs de set validados na COMC (1999-2023; `validate-slugs` confere ao vivo)
  iconic_pokemon.csv     lista do operador (rank, pokemon, score, sources) — EDITÁVEL
  iconic.py              match por palavra inteira contra a lista
  grading.py             parse da nota do slab (/Graded/<grader>/<nota> + título) + allowlist + coluna PC
  comc_scraper.py        navegação COMC via patchright headful; parse de raw E slabs
  pipeline.py            Scanner.run_scan (2 passadas/set) + process_listing (funil único) + FunnelStats
  matcher.py / normalize.py / tcg_index.py   identificação da carta no TCGplayer (confiança 0-1)
  tcgcsv_client.py / tcgdex_client.py        referência raw (market → mid → low; fallback TCGdex)
  pricecharting_client.py                    mediana de vendas comparáveis (slab por nota exata; raw LP) + guardas nome/número/set
  margin.py              desconto (ref − comc)/ref
  ranking.py             métricas (desconto, ROI bruto, spread) + ordem de ranking
  reporter.py            tabela canônica + classify_row (OK/MATCH_REVIEW) + JSON/CSV + funil
  models.py              dataclasses (listing com grade, deal com pokemon/ref_source/status)
comc_summary.py          ENTREGA canônica (JSON → markdown, 2 baldes, funil)
tests/                   suíte offline (fixtures reais)
results/                 saídas (gitignored)
```

## Fluxo de desenvolvimento

- Código = **branch + PR**; nunca push direto na `main`.
- Dados de scan, `.env`, caches e perfis de navegador não entram no repo.
- Versão: **0.4.1** (`pyproject.toml` + `CHANGELOG.md`, 2026-09-02).
