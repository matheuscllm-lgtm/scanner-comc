# Changelog

## 0.4.2 — 2026-09-02 — preço do tile vizinho (leilão eBay) + browser fechado aborta o run

- **Bug de alinhamento no parser da COMC**: um tile de leilão eBay promovido (link
  `/Promotions/eBay_Auction/…`, "3d left") não tem link `/Cards/`; o parser roubava o
  link-imagem do tile seguinte e colava nele o preço do leilão (Sylveon VMAX PSA 10 a
  US$15,50 em vez de US$341,10 — falso "83%" no diagnóstico). Agora o link próprio só é
  aceito ANTES do `listprice` e tiles `auctionItem` são descartados. Fixture real nova
  `comc_graded_evs_auction_capture.html`.
- **Chrome/contexto fechado** durante o scan vira `ComcAccessError` (run aborta com
  `comc_errors`), em vez de "varrer" os sets restantes com 0 listagens.
- Todo scan anterior a esta versão pode conter preços trocados em tiles vizinhos de
  leilões: re-rodar.

## 0.4.1 — 2026-09-02 — catálogo 2004–2023 (grupos 5–12) + `validate-slugs` por pertencimento ao set

### PR B — catálogo (regras do operador)
- **Grupos 5–12** em `groups.py`: EX 2004-05 · EX 2006-07 + DP 2007 · DP/Platinum 2008-10 ·
  HGSS + BW 2010-13 · XY 2014-16 · SM 2017-19 · SWSH 2020-21 · SWSH 2022 + Pokémon GO +
  Crown Zenith. `--group 1-12|all`; `list-groups` e a skill listam todos.
- **Catálogo**: 95 sets 2004-2023 (85 sets principais + 10 subsets com grupo tcgcsv próprio: Trainer Gallery ×4, Shiny Vault ×2, Radiant Collection ×2, Classic Collection, Galarian Gallery) validados ao vivo (página 1 raw + slabs) com o path
  ASCII exato da COMC (`<ano>/Pokemon_<Série>_-_<Set>_-_Base`, descoberto pelas URLs das
  listagens). Sem slug COMC (ficam fora, listados aqui): **EX Battle Stadium** e **Champion's Path**. Fora do escopo 2004-2022: SV01 Scarlet & Violet Base Set (2023).
- **`validate-slugs` só valida se ≥80% da página 1 for do próprio set** (`page1_own_share`):
  slug com acento (`Pokémon_…`) ou inexistente cai na categoria-pai da COMC (ano inteiro) e
  mistura sets — 57 dos 85 candidatos iniciais caíram nisso. `_set_key` mantém as
  palavras de série quando o nome só tem elas ("XY Base Set").
- `build_browse_url` percent-encoda o path como a COMC (hex minúsculo, sem re-encodar).

## 0.4.0 — 2026-09-02 — comparáveis EXATOS (mediana de vendas), raw LP com referência LP, sensibilidade

### Regras do operador (PR A — mecanismo)
- **Slab: referência = mediana de vendas concluídas** da MESMA carta, variante, idioma,
  certificadora, nota e subcategoria (BGS 10 Black ≠ BGS 10; CGC 10 Pristine ≠ Gem Mint;
  TAG 10 ≠ TAG 9.5). Colunas do PriceCharting (mesmo "PSA 10") e buckets genéricos
  NUNCA geram referência; a coluna exata só entra como sanidade (`coluna÷vendas`).
  Janelas: ≥3 vendas/180 d = OK; ≥3 só em 365 d = OK + `baixa-liquidez(365d)`;
  1–2 vendas = `MATCH_REVIEW · vendas<3`; 0 = sem referência (`slab_no_reference`).
- **Allowlist de slabs**: PSA 8/9/10, CGC 9/9.5/10 Gem/10 Pristine, BGS 9/9.5/10/10 Black
  Label, SGC 9/9.5/10, TAG 9.5/10. Todas as tabelas de vendas da página são lidas
  (dedupe por id de venda); tokens de variante (reverse, 1st, shadowless, promo…) têm
  de coincidir exatamente — nunca associação aproximada.
- **Raw**: WotC ≤2003 NM/EX-NM (`ERA_VINTAGE_MAX_YEAR=2003`); 2004+ só NM. **LP** entra
  só com referência LP (≥3 vendas "LP"/"Lightly Played", sem nota/outra condição), após
  o pré-filtro seguro `preço ≤ ref NM × (1 − desconto mín.)`; nunca LP vs NM
  (`LP_WITH_REFERENCE`; contadores `lp_prefilter`, `lp_no_reference`, `lp_pc_error`).
- **Nomes**: `Lucro$` → `Spread$` (ref − COMC, bruto) e `ROI%` → `ROI bruto%`; JSON
  `profit_abs` → `spread_abs` (+ `ref_liquidity`, `ref_window_days`, `ref_column_price`).
- **`comc_summary.py --sensitivity 10,15,20`**: tabela de contagens por limiar; ≥20% =
  candidato comercial; 15–19,99% e 10–14,99% = diagnóstico, NÃO oportunidade.
  Diagnóstico do operador: `scan --group all --min-price 5 --min-discount 10`.
- Teste de regressão: páginas iniciais só japonesas não interrompem a busca das
  inglesas; `--max-english` conta só inglesas válidas. Fixture real nova do PriceCharting
  (Charizard 4/102 Base Set, 375 vendas).

## 0.3.0 — 2026-09-02 — scanner ÚNICO (raw NM + slabs, Pokémon icônicos, 20%)

### Consolidação (spec do operador `scanner_comc.md`)
- **Um só subcomando `scan`** (`--group 1-4|all` ou `--sets`). Removidos `targeted`,
  `run`, `once`, `broad`, `dry-run`, `refresh-prices`, `parse-file`, o transporte
  Firecrawl (`firecrawl_client.py`, workflow `scan.yml`) e o push Google Sheets.
- **Sem estado de dias anteriores**: cursores de retomada apagados; snapshot tcgcsv
  sempre re-baixado; cache PriceCharting por dia. Cada run começa do zero.
- **Slabs**: 2ª passada por set com `aGraded`; parse de `/Graded/<grader>/<nota>` +
  título `[CGC 10 Pristine]` (`grading.py`); allowlist PSA 10/9, BGS 10/9.5,
  TAG 10/9.5, CGC 10 Pristine (`GRADED_ALLOW`). Referência de slab =
  **PriceCharting por nota** (`pricecharting_client.py`, portado do eBay/CT) —
  nunca comparado com preço raw; nota sem coluna exata = proxy sinalizado.
- **Pokémon icônicos**: `comc_scanner/iconic_pokemon.csv` (top-100 do operador,
  rank + score) + `iconic.py` (match por palavra inteira). `--all-pokemon` desliga.
- **Desconto mínimo 20%** (`MIN_DISCOUNT_PERCENT`, inteiro; `--min-discount`),
  fórmula `(ref − COMC)/ref`. Raw só condição **NM exata** (EX-NM deixou de passar).
- **Ranking** (`ranking.py`): ROI → desconto % → lucro US$ → rank do Pokémon.
- **Status** `OK` / `MATCH_REVIEW` (confiança <0.90, preço mid/low, proxy) gravado
  no JSON; `classify_row` é a fonte única (reporter + comc_summary).
- **Funil** (spec §13) contado por etapa e impresso no fim + cabeçalho da entrega.
- Tabela: `# | Desconto% | ROI% | COMC$ | Ref$ | Lucro$ | Pokémon | Carta | Set |
  Tipo | Ref | Conf | Status | Links` (`[oferta] · [referência]`; referência do slab
  aponta pro PriceCharting).
- **Ajustes pós-revisão do operador**: condição por era (WotC aceita `EX-NM`);
  colunas `TAG 10`/`ACE 10` lidas do PriceCharting (TAG 10 = referência exata);
  BGS/TAG 9.5 = mediana de ≥3 vendas concluídas da mesma certificadora+nota
  (`PC vendas BGS 9.5 (n=…)`), senão bucket "Grade 9.5" só para triagem
  (`MATCH_REVIEW`); `--sets` por igualdade exata; `--max-price` (teto antes do
  PriceCharting) e `--max-english` (corte por listagens inglesas, não brutas).
- **Revisões adversariais (2 lentes) aplicadas**: "Grade 9" também é bucket genérico
  (PSA 9 → mediana de vendas, senão triagem); venda comparável exige título com UMA só
  nota e ≤180 dias; `PcError` separa erro de fonte de "sem venda" (contador próprio,
  breaker após 5 falhas, página de bloqueio nunca cacheada); sanidade coluna×vendas
  (`ref÷vendas`); erro de listagem pulado e contado; flush garantido em `finally`;
  `--group all` tolera grupo quebrado; `funnel_lines` mostra contadores desconhecidos.
- **Pós-primeiro panorama (operador, 2026-09-02)**: funil conta `dedup_dropped` e rotula
  OK/MATCH_REVIEW como "antes da dedupe" (funil bate com a tabela); rótulo da condição
  vira "fora do permitido (moderno NM; WotC NM/EX-NM)"; coluna exata do PriceCharting
  sem NENHUMA venda recente da mesma nota → `MATCH_REVIEW · sem-vendas-recentes`.
- Fixtures reais novas: `comc_graded_151_capture.html`, `comc_graded_base_capture.html`,
  `pc_product_charizard_ex_151.html`, `pc_search_charizard_ex_151.html`. 136 testes.

## 0.2.0 — 2026-06-17

### Entrega canônica de resultados (tabela no chat com links verificáveis)
- `reporter.render_markdown` agora inclui **duas** colunas de link clicável por
  linha: `Oferta` = `[oferta](url COMC)` (já existia) e **`Referência` =
  `[referência](url TCGPlayer)`** (novo — o `tcg_url` já estava no `as_row()`, mas
  só ia para o CSV/JSON; agora viaja na tabela do chat para o operador conferir o
  preço de referência).
- Nova coluna **`Flag`**: marca `validar` quando a confiança do match está abaixo
  de `0.90` (constante `TRUST_CONFIDENCE`) — linhas suspeitas ficam **sinalizadas
  e visíveis**, nunca escondidas. Casa com a regra "mostrar todos os deals".
- `tests/test_reporter.py` (5 testes) trava o formato canônico: links de oferta e
  referência, `Card` = nome + número, e a flag `validar` para baixa confiança.
- **README.md**: seção "Entrega dos resultados" reescrita como **FORMATO CANÔNICO —
  OBRIGATÓRIO**, com a tabela de colunas e a regra "tabela no chat, nunca arquivo,
  sempre via `render_markdown`, todas as linhas".
- **CLAUDE.md** (novo): canal cross-env de "como rodar + como entregar" para
  qualquer sessão (inclui Claude Code da nuvem que só clona o GitHub). Linguagem
  acessível para operador não-programador.

## 0.1.0
- Versão inicial (PR #1): scanner COMC → TCGPlayer, tese value-buy, 28 sets
  validados, transporte Playwright headful grátis + Firecrawl, suíte offline.
