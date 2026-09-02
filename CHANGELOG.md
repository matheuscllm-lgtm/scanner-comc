# Changelog

## 0.3.0 — 2026-09-02

### Modo `--iconic`: personagens icônicos, faixa 30-40%, 2ª referência PriceCharting
Pedido do operador (2026-09-02): scanner COMC só de cartas de Pokémon icônicos
com preço 30-40% abaixo da referência do PriceCharting e do TCGplayer; como a
compra fica na conta COMC, sem frete/taxa embutida (margem bruta, já a default).
- `comc_scanner/notorious.py` (novo): lista curada de ~60 Pokémon icônicos +
  matcher por palavra inteira (portado do `integrated-scanner`); Trainer/Energy
  nunca contam (`Card Type` do tcgcsv).
- `comc_scanner/pricecharting.py` (novo): mediana das 10 vendas REAIS ungraded
  da carta no PriceCharting (metodologia do card-trader-scanner, 2026-08-28) com
  guardas de slug (nome+número+variante 1st/reverse) e de console (set exato,
  bidirecional); falha → None, nunca inventa. Cache 24 h em `.cache/pricecharting/`.
- `comc_scanner/iconic.py` (novo): margem que classifica = a mais CONSERVADORA
  entre TCG e PC; faixa `[--min-margin, --max-margin]` (default 0.30–0.40);
  `acima` = desconto maior que o teto → 🚨 revisar; flags `sem PC` / `PC diverge`
  (>40% entre referências).
- CLI: `--iconic`, `--max-margin` (FRAÇÃO), `--no-pricecharting`; env
  `ICONIC_ONLY` / `MAX_GROSS_MARGIN` / `PRICECHARTING_ENABLED`.
- Reporter: no modo icônico grava `results/comc_iconic_<era>_*` (não sobrescreve
  o clássico), payload com `mode`/`max_gross_margin`/`pricecharting`, tabela com
  as duas referências e 3º link `[PC]`. `Deal` ganhou `notorious`/`pc_*`.
- `comc_summary.py`: reconhece `mode: "iconic"` e entrega 4 baldes (🟢 na faixa
  limpos · ⚠️ na faixa validar · 🚨 acima · ❌ abaixo) + linha "Cobertura
  PriceCharting". Payloads antigos seguem no formato clássico.
- Skill nova `.claude/skills/scan-comc-iconic/SKILL.md`; 32 testes novos
  (`test_notorious.py`, `test_pricecharting.py`, `test_iconic.py`); prova real
  via `dry-run --iconic` (tcgcsv + PriceCharting ao vivo, 2026-09-02).

### Entradas retroativas (mergeadas após 0.2.0 sem bump)
- Fallback TCGdex + cross-validação de set-total no matcher (#8); sufixo
  `preço:<campo>` na Flag (#9); fixes de revisão (#10); sanitização BOM da key
  Firecrawl (#13); `comc_summary.py` + grupos + skill `scan-comc` (#22);
  margem-sobre-venda documentada (#24).

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
