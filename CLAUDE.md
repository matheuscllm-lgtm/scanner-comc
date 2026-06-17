# CLAUDE.md — scanner-comc

Instruções para qualquer sessão do Claude Code que trabalhe neste repositório
(inclui uma sessão da nuvem que só clonou o GitHub e não tem a memória local).
O operador é médico, **não-programador**: explique termos técnicos em linguagem
simples e seja preciso ao mesmo tempo.

## O que este projeto é

Scanner de arbitragem **COMC → TCGPlayer** de cartas avulsas de Pokémon (o 5º
scanner de singles, irmão de CardTrader / MYP / Liga). Procura cartas listadas na
COMC mais baratas que o preço habitual no TCGPlayer e reporta os melhores deals
por **margem bruta**. Tese atual = **VALUE-BUY**: comprar boas cartas com desconto
e potencial de valorização (segurar), não só flip imediato. Roda **grátis** via
navegador real (Playwright headful). Detalhes técnicos completos: `README.md` e
`HANDOFF.md` (a seção 0 do HANDOFF é a fonte da verdade do estado).

## ⭐ COMO ENTREGAR RESULTADOS (regra dura — não improvisar)

Quando o operador pedir "resultados", "deals", "panorama" ou similar:

1. **Entrega = uma tabela markdown colada AQUI no chat.** Nunca mande arquivo
   (`.csv`/`.xlsx`/`.json`) por padrão. O operador lê na conversa. Só gere/envie
   arquivo se ele **pedir explicitamente** ("me manda o CSV").
2. **A tabela vem do gerador do scanner — NUNCA monte uma tabela à mão.** A função
   `comc_scanner/reporter.py::render_markdown(deals, era, top_n)` é a fonte única
   do formato. O scanner já a imprime a cada flush. Para regerar de um resultado
   salvo, carregue `results/comc_deals_<era>_latest.json` e passe os deals por
   `render_markdown`. Montar à mão arrisca esquecer um link ou a flag e diverge do
   arquivo gravado.
3. **Mostre TODAS as linhas** (ordenadas por margem desc.), não uma amostra curada.
4. Cada linha traz, automaticamente:
   - `Card` = **nome + número de coleção** da carta (ex.: `Pikachu 173/165`);
   - `Oferta` = link clicável **[oferta](url COMC)** (a listagem na COMC);
   - `Referência` = link clicável **[referência](url TCGPlayer)** (onde conferir o
     preço de referência);
   - `Flag` = `ok` ou **`validar`** (match com confiança < 0.90 = **suspeito, conferir
     manualmente** — a linha aparece sempre, nunca é escondida).
5. **Não recomende comprar.** O scanner reporta dados; a decisão de capital é do
   operador. Pode comentar quais linhas estão `validar`, mas não diga "compre".

A especificação completa das colunas está no `README.md`, seção
**"Entrega dos resultados (FORMATO CANÔNICO — OBRIGATÓRIO)"**. Os testes em
`tests/test_reporter.py` travam esse formato (links + flag + nome+número).

## Como rodar (grátis, navegador local headful)

```bash
# modern (SV) e vintage (WotC); piso $10 + margem 0.30 já são default:
python -m comc_scanner targeted --era recent  --fetch-mode playwright --no-sheets --restart
python -m comc_scanner targeted --era vintage --fetch-mode playwright --no-sheets --restart
```

Variações úteis: `--min-margin 0.20` (afrouxa o limiar p/ value-buy),
`--chase-only` (só raridades de perseguição), `--min-margin 0.0` (captura a
distribuição inteira pra ler depois). `python -m comc_scanner --help` lista tudo.
**Threshold `--min-margin` é FRAÇÃO** (`0.30` = 30%), igual ao CardTrader e ao
contrário do MYP/Liga.

## Convenções que não mudam

- **Recorrência é MANUAL** (decisão do operador, 2026-06-09): o operador aciona o
  scan; **não** crie Task Scheduler / GitHub Actions / agendamento.
- **NM-only** e **English-only** são invariantes do pipeline (cartas de outra
  condição ou idioma viram falso positivo).
- **Margem bruta pura**, limiar **30%**, **sem** taxas embutidas (frete/câmbio/IOF o
  operador calcula por fora). Piso de preço **US$ 10** (≈ regra "carta valiosa ≥ R$50").

## Testes

```bash
python -m pytest tests/    # offline, sem rede
```
