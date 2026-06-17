# Changelog

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
