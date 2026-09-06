---
name: scan-comc
description: >-
  Rodar o scanner ÚNICO da COMC (cartas soltas NM + slabs PSA/BGS/TAG/CGC
  Pristine 10, só Pokémon da lista icônica, desconto ≥20% sobre a referência) por
  GRUPOS de sets e entregar via comc_summary.py. Use SEMPRE que o operador pedir
  para rodar o scanner do COMC / "roda o COMC" / "scan COMC" / "escaneia a COMC" /
  "roda o grupo X do COMC": antes de rodar, PERGUNTE qual dos 12 grupos (ou todos)
  ele quer.
---

REGRA VIGENTE 2026-09-06: ler ACQUISITION_POLICY.md na raiz. Todos os Pokémon e eras por padrão; NM/LP com referências próprias, EX-NM em revisão sem preço presumido; entrega completa. Substitui regras históricas conflitantes abaixo.

REGRA VIGENTE DO OPERADOR: ler DELIVERY_CHAT.md na raiz do repositório. Entrega somente no chat, preço de referência clicável, coleta nova sob demanda; não executar scans no GitHub Actions nem publicar resultados. Esta regra substitui instruções antigas conflitantes abaixo.



# Scan do COMC por grupos — pergunte, rode, entregue

O catálogo validado (sets `validated: true` de `comc_scanner/comc_set_slugs.json`)
está dividido em **12 grupos** (SV, WotC, EX, DP/Platinum, HGSS/BW, XY, SM, SWSH) — fonte canônica `comc_scanner/groups.py`
(`python -m comc_scanner list-groups` lista sem rede). Cada set é varrido em
**duas passadas**: cartas soltas (NM em todas as eras; EX-NM vai para revisão sem preço; LP só com
referência LP = mediana de ≥3 vendas "LP") e slabs (PSA 8-10, CGC 9-10 Gem/Pristine,
BGS 9-10/Black Label, SGC 9-10, TAG 9.5/10 — referência = mediana de vendas da MESMA
certificadora+nota+variante; coluna do PriceCharting nunca é referência). Só cartas de Pokémon da lista
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

### Grupo 5 — EX 2004-2005 (8 sets, era `middle`, ~32-64 min*)
EX Team Magma vs Team Aqua · EX Hidden Legends · EX FireRed & LeafGreen · EX Team Rocket Returns · EX Deoxys · EX Emerald · EX Unseen Forces · EX Delta Species

### Grupo 6 — EX 2006-2007 + DP 2007 (8 sets, era `middle`, ~32-64 min*)
EX Legend Maker · EX Holon Phantoms · EX Crystal Guardians · EX Dragon Frontiers · EX Power Keepers · Diamond and Pearl · Mysterious Treasures · Secret Wonders

### Grupo 7 — DP/Platinum 2008-2010 (8 sets, era `middle`, ~32-64 min*)
Great Encounters · Majestic Dawn · Legends Awakened · Stormfront · Platinum · Rising Rivals · Supreme Victors · Arceus

### Grupo 8 — HGSS + BW 2010-2013 (17 sets, era `middle`, ~68-136 min*)
HeartGold SoulSilver · Unleashed · Undaunted · Triumphant · Call of Legends · Black and White · Emerging Powers · Noble Victories · Next Destinies · Dark Explorers · Dragons Exalted · Boundaries Crossed · Plasma Storm · Plasma Freeze · Plasma Blast · Legendary Treasures · Legendary Treasures: Radiant Collection

### Grupo 9 — XY 2014-2016 (14 sets, era `middle`, ~56-112 min*)
XY Base Set · XY - Flashfire · XY - Furious Fists · XY - Phantom Forces · XY - Primal Clash · XY - Roaring Skies · XY - Ancient Origins · XY - BREAKthrough · XY - BREAKpoint · Generations · XY - Fates Collide · XY - Steam Siege · XY - Evolutions · Generations: Radiant Collection

### Grupo 10 — SM 2017-2019 (17 sets, era `middle`, ~68-136 min*)
SM Base Set · SM - Guardians Rising · SM - Burning Shadows · Shining Legends · SM - Crimson Invasion · SM - Ultra Prism · SM - Forbidden Light · SM - Celestial Storm · Dragon Majesty · SM - Lost Thunder · SM - Team Up · Detective Pikachu · SM - Unbroken Bonds · SM - Unified Minds · Hidden Fates · SM - Cosmic Eclipse · Hidden Fates: Shiny Vault

### Grupo 11 — SWSH 2020-2021 (12 sets, era `recent`, ~48-96 min*)
SWSH01: Sword & Shield Base Set · SWSH02: Rebel Clash · SWSH03: Darkness Ablaze · SWSH04: Vivid Voltage · Shining Fates · SWSH05: Battle Styles · SWSH06: Chilling Reign · SWSH07: Evolving Skies · Celebrations · SWSH08: Fusion Strike · Shining Fates: Shiny Vault · Celebrations: Classic Collection

### Grupo 12 — SWSH 2022 + Crown Zenith (11 sets, era `recent`, ~44-88 min*)
SWSH09: Brilliant Stars · SWSH10: Astral Radiance · Pokemon GO · SWSH11: Lost Origin · SWSH12: Silver Tempest · SWSH: Crown Zenith · SWSH09: Brilliant Stars Trainer Gallery · SWSH10: Astral Radiance Trainer Gallery · SWSH11: Lost Origin Trainer Gallery · SWSH12: Silver Tempest Trainer Gallery · SWSH: Crown Zenith: Galarian Gallery

### `all` — os 12 em sequência (~6-12 h; um único JSON `comc_deals_all_latest.json`)

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
   mid/low, `vendas<3` = só 1–2 vendas comparáveis, `coluna÷vendas`) — nenhuma linha
   escondida; `baixa-liquidez(365d)` é nota, não muda status. Ordem = ranking
   (ROI bruto → desconto % → spread US$ → popularidade do Pokémon). Nunca "lucro".
   **Diagnóstico** (pedido do operador): `scan --group all --min-price 5 --min-discount 10`
   e depois `comc_summary.py … --sensitivity 10,15,20`: faixas 10–14,99% e 15–19,99%
   são diagnóstico, NÃO oportunidade; ≥20% = candidato comercial.
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
