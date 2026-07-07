---
name: scan-comc
description: >-
  Rodar o scan de arbitragem COMC → TCGplayer (singles Pokémon) por GRUPOS de
  sets e entregar via comc_summary.py. Use SEMPRE que o operador pedir para
  rodar o scanner do COMC / "roda o COMC" / "scan COMC" / "escaneia a COMC" /
  "roda o grupo X do COMC": antes de rodar, PERGUNTE qual dos 4 grupos ele quer
  (o catálogo validado é dividido em 4 grupos — 2 de SV moderno, 2 de WotC
  vintage — para o scan ser curto, terminar e entregar).
---

# Scan do COMC por grupos — pergunte, rode, entregue

O catálogo validado do COMC (os sets `validated: true` de
`comc_scanner/comc_set_slugs.json`) está dividido em **4 grupos** — a fonte
canônica dos grupos é `comc_scanner/groups.py` (o teste
`tests/test_groups.py` trava união exata sem sobreposição; se o catálogo
crescer, o teste força atualizar os grupos e ESTE arquivo). Para listar sem
rede: `python -m comc_scanner list-groups`.

## Passo 1 — SEMPRE perguntar qual grupo rodar

Ao ser invocado, **pergunte ao operador** (AskUserQuestion) qual dos 4 grupos
rodar nesta sessão — nunca assuma. **Um grupo por vez, sequencial** (nunca 2
scans no mesmo IP). Apresente:

### Grupo 1 — SV recente (7 sets, era `recent`, ~30-60 min*)
SV10: Destined Rivals · SV09: Journey Together · SV: Prismatic Evolutions ·
SV08: Surging Sparks · SV07: Stellar Crown · SV: Shrouded Fable ·
SV06: Twilight Masquerade

### Grupo 2 — SV restante (6 sets, era `recent`, ~30-60 min*)
SV05: Temporal Forces · SV: Paldean Fates · SV04: Paradox Rift ·
SV03: Obsidian Flames · SV02: Paldea Evolved · SV: Scarlet & Violet 151

### Grupo 3 — WotC 1999-2000 (8 sets, era `vintage`, ~15-30 min*)
Base Set · Jungle · Fossil · Base Set 2 · Team Rocket · Gym Heroes ·
Gym Challenge · Neo Genesis

### Grupo 4 — WotC 2001-2003 (7 sets, era `vintage`, ~15-30 min*)
Neo Discovery · Neo Revelation · Neo Destiny · Legendary Collection ·
Expedition · Aquapolis · Skyridge

(*estimativas grosseiras: ~100 listagens/página, delay 4 s/página; sets SV têm
~400-650 listagens, WotC ~35-325. O primeiro run pode pedir interação com o
desafio Cloudflare.)

## Passo 2 — rodar (rota DETERMINÍSTICA por ambiente)

| Onde a sessão está rodando | Rota ÚNICA |
|---|---|
| **Máquina local do operador** (Windows) | O comando local abaixo, **headful** (janela do Chrome VAI abrir — é esperado e obrigatório). |
| **Sessão na nuvem / container** (sem display) | **NÃO rodar playwright** (não há display; headless não fura o CF Turnstile). Única rota é o workflow `scan.yml` (dispatch manual) com Firecrawl — hoje **dormente por créditos**: se for o caso, reporte honestamente que o scan na nuvem está indisponível e pare. |

### Rota local (sempre este comando)

```powershell
$env:PYTHONIOENCODING="utf-8"
python -m comc_scanner targeted --group <N> --top-n 200 --fetch-mode playwright --headful --no-sheets --restart
```

- **Headful é OBRIGATÓRIO** — headless não fura o Cloudflare Turnstile
  (headless = 0 produtos, aprendizado do operador). A janela do Chrome abre;
  não feche. O perfil persistente `.cache/pw_profile_comc` guarda o
  `cf_clearance`; se um run começar bloqueado, rode antes
  `python -m comc_scanner warm --fetch-mode playwright --headful` e resolva o
  desafio na janela.
- `--group <N>` já define o allowlist de sets E a era (SV=recent,
  WotC=vintage) — não precisa de `--era` nem `--sets`. `--group` só existe no
  modo `targeted` (nos outros modos o filtro é por substring e vazaria pra
  sets parecidos; use `--sets` lá).
- `--top-n 200` evita o corte silencioso do teto default (50): o Reporter só
  grava os top-N deals no JSON. Se mesmo assim a entrega avisar "Lista cheia
  no teto top_n", re-rode com um valor maior.
- `--restart` ignora o cursor salvo (scan do grupo completo). Se um run morrer
  no meio, re-rodar SEM `--restart` retoma do set onde parou — **mas SÓ se for
  o MESMO grupo da run interrompida**: grupos da mesma era (1 e 2 = `recent`;
  3 e 4 = `vintage`) compartilham o MESMO cursor (`targeted_<era>_idx.txt`).
  Trocar de grupo exige `--restart`, senão o scan "retoma" no índice do grupo
  errado.
- Threshold `--min-margin` é **FRAÇÃO** (`0.30` = 30%, default) — convenção
  CardTrader/COMC/Selados, oposta ao MYP/Liga (percent inteiro).

## Passo 3 — entregar (ritual FIXO, contrato do repo, não negociável)

O scan grava `results/comc_deals_<era>_latest.json` (era = `recent` para
grupos 1-2, `vintage` para 3-4). A entrega sai SEMPRE da ferramenta:

```powershell
python comc_summary.py results/comc_deals_<era>_latest.json -o results/comc-grupo<N>-<AAAA-MM-DD>.md --group <N>
```

> ⚠️ **Gere o `.md` LOGO APÓS o scan do grupo, antes de rodar outro grupo da
> mesma era**: grupos 1 e 2 (e 3 e 4) escrevem no MESMO
> `comc_deals_<era>_latest.json` — rodar o grupo seguinte sobrescreve o
> resultado do anterior. Scan do grupo → summary do grupo → colar → só então
> o próximo grupo.

1. Colar o conteúdo do `.md` **VERBATIM** no chat — **PROIBIDO** remontar a
   tabela à mão, renomear/reordenar colunas ou dropar o link `[referência]`.
   Toda linha tem os DOIS links: `[oferta]` (COMC) · `[referência]`
   (TCGplayer), lidos do JSON — nunca inventados.
2. TODOS os buckets aparecem: 🟢 deals confiáveis E ⚠️ validar (confiança
   baixa e/ou preço mid/low) — nenhuma linha escondida.
3. A linha "Cobertura de preço market" (market/mid/low) sempre vai junto —
   fallback nunca é apresentado como preço real.
4. A única moldura fora do verbatim: uma linha de contexto antes ("Grupo N,
   data") e notas de leitura depois que NÃO alterem nem resumam a tabela.
5. **Sem recomendação de compra** — a decisão de capital é do operador.

## Notas fixas

- **Logística COMC**: as compras ficam **armazenadas na conta COMC do
  operador** (o Ship To / mailbox da COMC é o hub de recebimento da operação
  — não há frete por compra individual; consolidação/envio é decisão do
  operador, fora do scanner).
- **Recorrência é MANUAL** (decisão do operador): não criar Task Scheduler /
  GitHub Actions / agendamento.
- Invariantes do pipeline: margem BRUTA `(TCG − COMC)/TCG`, NM-only match
  exato, English-only, piso US$10, chase via `--chase-only`.
