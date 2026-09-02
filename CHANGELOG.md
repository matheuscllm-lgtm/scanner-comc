# Changelog

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
