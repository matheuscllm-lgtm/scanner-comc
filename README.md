# scanner-comc

Scanner de arbitragem **COMC → TCGPlayer** para cartas avulsas de Pokémon TCG.

Procura cartas listadas na [COMC](https://www.comc.com) por preço abaixo do preço
habitual do **TCGPlayer** e reporta os **melhores deals por margem bruta**. Como as
cartas já estão na COMC e você tem conta lá, o único filtro é **margem bruta > 20%**
(configurável). Lista o **top 50** por margem desc., **sem preço mínimo**.

## Como funciona

1. **Preço TCGPlayer** vem do [TCGCSV](https://tcgcsv.com) — espelho público e grátis
   da API do TCGplayer (Pokémon = `categoryId 3`). Baixamos o snapshot diário 1×/dia e
   cacheamos em `.cache/`. Preço de referência = `marketPrice` (fallback `mid` → `low`).
2. **Listagens da COMC** são raspadas com **Playwright (Chromium)**, porque o site fica
   atrás de um desafio Cloudflare (um GET simples devolve HTTP 403). Opcionalmente usa os
   cookies da sua conta (`COMC_SESSION_COOKIE`). A navegação usa a gramática de facetas
   por vírgula da COMC, ex.:
   `https://www.comc.com/Cards/Pokemon,=evolving+skies,sl,fb,aUngraded,rCOMC,gEX-NM,i100,p3`.
3. **Matching** carta↔TCGPlayer por `set + número` (com fallback de nome fuzzy) e
   **confiança** explícita por tier. Subtype (Normal/Holo/Reverse/1st Ed/Unlimited) é
   inferido das pistas do anúncio; sem pista, usa o subtype mais barato (conservador).
4. **Margem bruta** = `(preço_TCG − preço_COMC) / preço_TCG`. Limiar e fórmula em
   `comc_scanner/margin.py` (troca para `markup` ou taxas/frete num só lugar).
5. **Eras + chunking**: os sets são agrupados por ano de lançamento em
   `recent` / `middle` / `vintage`. Você escolhe a era (`--era`), e ela também serve de
   *chunk* — a varredura para no orçamento (`--max-run-seconds` / `--max-sets-per-chunk`),
   salva o cursor em `.cache/progress/<era>.json` e **retoma** na próxima execução.

## Entrega dos resultados

A cada flush (a cada ~1h e ao fim de cada chunk) o scanner:
- imprime uma **tabela markdown** no console (renderizada aqui no Claude Code / terminal);
- grava em `results/`: `comc_deals_<era>_latest.csv` + `.json` (sobrescritos) e snapshots
  com timestamp UTC. O CSV é amigável p/ **Google Sheets** (é só importar);
- se houver credenciais, faz push opcional para um **Google Sheet** (degrada p/ CSV se não).

## Instalação

```bash
pip install -r requirements.txt
playwright install chromium      # necessário só para a raspagem ao vivo da COMC
cp .env.example .env             # ajuste as variáveis
```

O núcleo (preços TCGCSV, matching, ranking, relatório) roda só com `requests` + stdlib.
`playwright`, `selectolax`, `rapidfuzz` e `gspread` são opcionais em runtime (há fallbacks).

## Uso

```bash
# Loop contínuo (resultados parciais ~a cada hora), era recente:
python -m comc_scanner run --era recent

# Uma rodada (um chunk), retomando o cursor:
python -m comc_scanner once --era vintage

# Quebrar em pedaços p/ não estourar o tempo (2 sets por rodada, 3 páginas por set):
python -m comc_scanner once --era vintage --max-sets-per-chunk 2 --max-pages 3
python -m comc_scanner once --era vintage   # próxima rodada retoma de onde parou

# Forçar atualização do snapshot de preços do TCGCSV:
python -m comc_scanner refresh-prices --era all

# Dry-run: testa matching/relatório com listagens sintéticas (sem tocar a COMC):
python -m comc_scanner dry-run --era vintage --listings tests/fixtures/listings_sample.json
```

Flags úteis: `--top-n 50`, `--min-margin 0.20`, `--min-confidence 0.80`,
`--interval 3600`, `--condition EX-NM`, `--include-graded`, `--headful`,
`--no-sheets`, `--sets "Evolving Skies,SV09"`, `--restart`. Variáveis equivalentes
estão em `.env.example`.

## Testes

```bash
python -m pytest tests/        # se o pytest estiver instalado
```
Os testes em `tests/` são offline (sem rede): normalização, matching/tiers,
preço de referência conservador, eras e cursor de chunk.

## Limitações conhecidas / avisos

- **COMC + Cloudflare + Termos de Uso**: a raspagem exige navegador real e pode infringir
  os Termos da COMC. Use volume baixo, ritmo conservador e trate como ferramenta de uso
  pessoal. O DOM exato das listagens da COMC não é público — valide/ajuste os seletores em
  `comc_scanner/comc_scraper.py` contra uma página real salva (use `parse_html_file`).
- **Acurácia de match**: cada deal traz `confidence` e `match_reason`; matches abaixo de
  `MIN_MATCH_CONFIDENCE` ficam só no JSON (campo `low_confidence`), fora do top-50.
- **Condição/subtype**: por padrão compara COMC ungraded `EX-NM` com o `marketPrice` (NM)
  do TCG; graded (PSA/BGS/CGC) é excluído por padrão. Confira o `sub_type` de cada deal.
- **Preços USD** (COMC e TCGPlayer); sem conversão de moeda.
