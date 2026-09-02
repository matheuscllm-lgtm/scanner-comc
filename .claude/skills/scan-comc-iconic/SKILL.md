---
name: scan-comc-iconic
description: >-
  Rodar o scan COMC de cartas Pokémon de PERSONAGENS ICÔNICOS (Charizard,
  Pikachu, Umbreon, Mewtwo, Lugia...) com preço 30-40% abaixo da referência do
  PriceCharting E do TCGplayer, e entregar via comc_summary.py. Use SEMPRE que o
  operador pedir "COMC icônicos" / "roda o COMC dos icônicos" / "cartas
  icônicas na COMC" / "scan COMC 30-40%" / "COMC personagens famosos": antes de
  rodar, PERGUNTE qual dos 4 grupos de sets rodar (mesmos grupos do scan-comc).
---

# Scan COMC — personagens icônicos, faixa 30-40% (pergunte, rode, entregue)

É o `scan-comc` com o modo **`--iconic`** ligado (pedido do operador,
2026-09-02). O que muda em relação ao scan clássico:

| | clássico (`scan-comc`) | icônicos (este skill) |
|---|---|---|
| Cartas | todas do set | só Pokémon da lista curada `comc_scanner/notorious.py` (~60 ícones; Trainer/Energy nunca) |
| Referência | TCGplayer market (tcgcsv) | TCGplayer market **+ PriceCharting** (mediana de 10 vendas reais ungraded) |
| Margem que classifica | vs TCG | a mais **CONSERVADORA** das duas (se uma diz desconto menor, vale a menor) |
| Corte | ≥ 30% | **FAIXA 30-40%**: dentro = 🟢/⚠️ · **acima de 40% = 🚨 revisar** (desconto grande demais costuma ser variante/condição errada) · abaixo = ❌ mostrado |
| Taxas | margem bruta | margem bruta — a compra fica ARMAZENADA na conta COMC do operador: sem frete/taxa por compra |
| Arquivos | `results/comc_deals_<era>_*` | `results/comc_iconic_<era>_*` (não sobrescreve o clássico) |

Tudo o mais é idêntico (NM-only, EN-only, piso US$10, threshold em FRAÇÃO,
Cloudflare headful, um grupo por vez).

## Passo 1 — SEMPRE perguntar qual grupo rodar

Pergunte ao operador (AskUserQuestion) qual dos 4 grupos rodar — nunca assuma.
**Um grupo por vez.** Os grupos são os MESMOS do `scan-comc` (fonte canônica
`comc_scanner/groups.py`; `python -m comc_scanner list-groups` lista sem rede):

- **Grupo 1 — SV recente** (7 sets, era `recent`): Destined Rivals · Journey
  Together · Prismatic Evolutions · Surging Sparks · Stellar Crown · Shrouded
  Fable · Twilight Masquerade
- **Grupo 2 — SV restante** (6 sets, `recent`): Temporal Forces · Paldean Fates ·
  Paradox Rift · Obsidian Flames · Paldea Evolved · 151
- **Grupo 3 — WotC 1999-2000** (8 sets, `vintage`): Base Set · Jungle · Fossil ·
  Base Set 2 · Team Rocket · Gym Heroes · Gym Challenge · Neo Genesis
- **Grupo 4 — WotC 2001-2003** (7 sets, `vintage`): Neo Discovery · Neo
  Revelation · Neo Destiny · Legendary Collection · Expedition · Aquapolis ·
  Skyridge

O modo icônico é mais rápido que o clássico na fase de PriceCharting (só as
cartas icônicas que passaram do corte TCG consultam o PC — ~4 s por carta
única, cache 24 h em `.cache/pricecharting/`), mas a varredura da COMC é a
mesma.

## Passo 2 — rodar (rota DETERMINÍSTICA por ambiente)

| Onde a sessão roda | Rota ÚNICA |
|---|---|
| **PC do operador** (Windows) | comando local abaixo, **headful** (janela do Chrome abre — esperado). |
| **Nuvem/container** | NÃO rodar playwright (sem display; headless não fura o Turnstile). Única rota é o workflow `scan.yml` com Firecrawl — hoje **dormente por créditos**: reporte honestamente que o scan na nuvem está indisponível e pare. (O `dry-run --iconic` com uma fixture de listings funciona na nuvem — só pra provar o pipeline, não é scan.) |

```powershell
$env:PYTHONIOENCODING="utf-8"
python -m comc_scanner targeted --group <N> --iconic --top-n 200 --fetch-mode playwright --headful --no-sheets --restart
```

- `--iconic` liga o filtro de personagens, a 2ª referência PriceCharting e a
  faixa (`--min-margin 0.30` / `--max-margin 0.40` default, FRAÇÃO). Pra
  afrouxar/apertar a faixa: `--min-margin 0.25 --max-margin 0.45`.
- `--no-pricecharting` desliga a consulta ao PC (só TCG) — use só se o PC
  estiver fora do ar; a entrega então marca todas as linhas `sem PC`.
- Demais notas (headful obrigatório, `warm`, cursor por era, `--restart` ao
  trocar de grupo) são as do `scan-comc` — valem iguais.

## Passo 3 — entregar (ritual FIXO)

O scan grava `results/comc_iconic_<era>_latest.json` (era = `recent` pros
grupos 1-2, `vintage` pros 3-4). A entrega sai SEMPRE da ferramenta, que
reconhece o modo pelo campo `mode: "iconic"` do JSON:

```powershell
python comc_summary.py results/comc_iconic_<era>_latest.json -o results/comc-iconicos-grupo<N>-<AAAA-MM-DD>.md --group <N>
```

> ⚠️ Gere o `.md` LOGO APÓS o scan do grupo: grupos da mesma era escrevem no
> MESMO `comc_iconic_<era>_latest.json`.

1. Colar o `.md` **VERBATIM** — proibido remontar a tabela, renomear colunas
   ou dropar links. Toda linha tem `[oferta]` (COMC) · `[referência]`
   (TCGplayer) · `[PC]` (PriceCharting, quando existe), lidos do JSON.
2. Os **4 baldes** aparecem sempre: 🟢 na faixa limpos · ⚠️ na faixa validar
   (`validar`/`preço:mid|low`/`sem PC`/`PC diverge`) · 🚨 acima da faixa ·
   ❌ abaixo da faixa.
3. As linhas "Cobertura de preço market" e "Cobertura PriceCharting" vão junto
   — fallback e ausência de PC nunca são apresentados como preço real.
4. **Sem recomendação de compra** — o operador decide capital.

## Notas fixas

- **`PC diverge`** (referências discordam >40%) é o sinal mais útil deste modo:
  em vintage o market do TCGplayer costuma inflar (ex.: Base Set Charizard
  market US$868 vs mediana de vendas reais US$329 em 2026-09-02); a margem
  conservadora já protege, mas confira a versão nos dois links.
- **Recorrência é MANUAL**: não criar agendamento.
