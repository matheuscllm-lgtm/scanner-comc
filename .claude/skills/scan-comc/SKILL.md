---
name: scan-comc
description: >-
  Rodar o scanner ÚNICO da COMC (cartas soltas NM + slabs PSA/BGS/TAG/CGC
  Pristine 10, só Pokémon da lista icônica, desconto ≥20% sobre a referência) por
  GRUPOS de sets e entregar via comc_summary.py. Use SEMPRE que o operador pedir
  para rodar o scanner do COMC / "roda o COMC" / "scan COMC" / "escaneia a COMC" /
  "roda o grupo X do COMC": antes de rodar, PERGUNTE qual dos 4 grupos (ou todos)
  ele quer.
---

# Scan do COMC por grupos — pergunte, rode, entregue

O catálogo validado (sets `validated: true` de `comc_scanner/comc_set_slugs.json`)
está dividido em **4 grupos** — fonte canônica `comc_scanner/groups.py`
(`python -m comc_scanner list-groups` lista sem rede). Cada set é varrido em
**duas passadas**: cartas soltas (moderno só NM; WotC NM ou EX-NM) e slabs (só PSA 10/9, BGS 10/9.5,
TAG 10/9.5, CGC 10 Pristine). Só cartas de Pokémon da lista
`comc_scanner/iconic_pokemon.csv` (top-100 do operador) entram; desconto mínimo
**20%** (`(ref − COMC)/ref`); piso US$10.

## Passo 1 — SEMPRE perguntar qual grupo rodar

Pergunte ao operador (AskUserQuestion) qual grupo rodar — nunca assuma. Um por vez
(nunca 2 scans no mesmo IP). Opções:

### Grupo 1 — SV recente (7 sets, era `recent`, ~40-80 min*)
SV10: Destined Rivals · SV09: Journey Together · SV: Prismatic Evolutions ·
SV08: Surging Sparks · SV07: Stellar Crown · SV: Shrouded Fable · SV06: Twilight Masquerade

### Grupo 2 — SV restante (6 sets, era `recent`, ~40-80 min*)
SV05: Temporal Forces · SV: Paldean Fates · SV04: Paradox Rift · SV03: Obsidian Flames ·
SV02: Paldea Evolved · SV: Scarlet & Violet 151

### Grupo 3 — WotC 1999-2000 (8 sets, era `vintage`, ~20-40 min*)
Base Set · Jungle · Fossil · Base Set 2 · Team Rocket · Gym Heroes · Gym Challenge · Neo Genesis

### Grupo 4 — WotC 2001-2003 (7 sets, era `vintage`, ~20-40 min*)
Neo Discovery · Neo Revelation · Neo Destiny · Legendary Collection · Expedition · Aquapolis · Skyridge

### `all` — os 4 em sequência (~2-4 h; um único JSON `comc_deals_all_latest.json`)

(*estimativas: 2 passadas por set, ~100 listagens/página, delay 4 s/página; slabs de
Pokémon icônicos ainda consultam o PriceCharting a 2 s/carta.)

## Passo 2 — rodar (só na máquina local do operador, Windows, headful)

Sessão na nuvem/container **não roda** (sem display; headless não fura o Cloudflare):
reporte honestamente e pare.

```powershell
$env:PYTHONIOENCODING="utf-8"
python -m comc_scanner scan --group <N|all>
```

- **Headful é OBRIGATÓRIO** — a janela do Chrome abre; não feche. O perfil
  persistente `.cache/pw_profile_comc` guarda o `cf_clearance`; se um run começar
  bloqueado, rode antes `python -m comc_scanner warm` e resolva o desafio na janela.
- Cada run começa **do zero** e usa **só dados do dia** (snapshot tcgcsv de hoje,
  cache PriceCharting de hoje, sem cursor de retomada). Se um run morrer no meio,
  rode o grupo de novo.
- Variações: `--min-discount 25` (inteiro), `--max-price 300` (teto por carta),
  `--max-english 300` (para o set após 300 inglesas válidas), `--raw-only` /
  `--slabs-only`, `--all-pokemon` (ignora a lista icônica), `--chase-only`,
  `--max-pages 3` (smoke rápido), `--top-n 400`.

## Passo 3 — entregar (ritual FIXO, contrato do repo, não negociável)

O scan grava `results/comc_deals_grupo<N>_latest.json` (ou `comc_deals_all_latest.json`).
A entrega sai SEMPRE da ferramenta:

```powershell
python comc_summary.py results/comc_deals_grupo<N>_latest.json -o results/comc-grupo<N>-<AAAA-MM-DD>.md --group <N>
```

1. Colar o `.md` **VERBATIM** no chat — **PROIBIDO** remontar a tabela à mão,
   renomear/reordenar colunas ou dropar o link `[referência]`. Toda linha tem os
   DOIS links: `[oferta]` (COMC) · `[referência]` (TCGplayer para raw; PriceCharting
   para slab), lidos do JSON — nunca inventados.
2. TODOS os baldes aparecem: 🟢 OK e ⚠️ MATCH_REVIEW (confiança <0.90, preço
   mid/low, ou slab só com bucket genérico "Grade 9.5" — triagem, sem vendas
   comparáveis suficientes) — nenhuma linha escondida. Ordem = ranking
   (ROI → desconto % → lucro US$ → popularidade do Pokémon).
3. O cabeçalho traz o **funil** (analisadas / ignoradas por motivo / OK / revisão)
   — vai junto sempre.
4. A única moldura fora do verbatim: uma linha de contexto antes ("Grupo N, data")
   e notas de leitura depois que NÃO alterem nem resumam a tabela.
5. **Sem recomendação de compra** — a decisão de capital é do operador.

## Notas fixas

- **Logística COMC**: compras ficam armazenadas na conta COMC do operador
  (mailbox = hub de recebimento; consolidação/envio é decisão dele, fora do scanner).
- **Recorrência é MANUAL** (decisão do operador): não criar agendamento.
- Invariantes: desconto `(ref − COMC)/ref` ≥ 20% (inteiro em `--min-discount`),
  raw NM-only por match exato, English-only, piso US$10, slabs só nas notas da
  allowlist, referência de slab = PriceCharting por nota (nunca preço raw).
