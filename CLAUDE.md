# CLAUDE.md — scanner-comc

Instruções para qualquer sessão do Claude Code que trabalhe neste repositório
(inclui uma sessão da nuvem que só clonou o GitHub e não tem a memória local).
O operador é médico, **não-programador**: explique termos técnicos em linguagem
simples e seja preciso ao mesmo tempo.

## 🛰️ Convenções da frota (cross-scanner)

> **Manual completo** (repo privado): https://github.com/matheuscllm-lgtm/scanners-commons — erros comuns, referências de preço, chaves, GitHub Actions e modelo de entrega de TODOS os scanners. Cópia-mestra local: `C:\Users\mathe\scanners-commons\`.

Invariantes que valem para TODOS os scanners:
- **Margem BRUTA, mínimo 30%** — só `(revenda − compra)/compra`, sem taxa embutida; piso de relevância R$50 (~US$10).
- **Só Near Mint** — condição por match EXATO `== "NM"`, nunca substring (já vazou SP).
- **Nunca inventar preço** — fonte falhou → marca fallback/erro e segue; jamais fabrica número.
- **Entrega = tabela markdown no chat** (nunca XLSX por padrão), gerada pela ferramenta do repo, mostrando TODAS as linhas (aprovadas + rejeitadas). Coluna `Carta` = nome + número; coluna `Links` combinada = `[oferta](url) · [TCG/referência](url)`.
- ⚠️ **Convenção de threshold:** percentual inteiro (`30`) = MYP, Liga, eBay; fração (`0.30`) = CardTrader, COMC, Selados.

Erros recorrentes (3 famílias — detalhe no manual):
1. **Segredo/ambiente:** BOM/zero-width numa chave → crash latin-1 no header → scan "verde mas vazio". Setar sem BOM (`printf '%s' 'KEY' | gh secret set`) **e** sanitizar ao ler no código (`.strip()` NÃO tira BOM).
2. **Git:** galho ou `main` local defasado por squash-merge PARECE pendência. O teste real de "já mergeado" é `git diff --stat origin/main <galho>` estar vazio (não `git merge-base`).
3. **Honestidade de preço:** inflação de referência, fallback tratado como real, NM frouxo → sempre validar versão/condição e rotular fallback.

**Este scanner:** referência de preço = `tcgcsv.com` (primário; campo market → mid → low, rastreado em `price_field`), com **fallback automático pro TCGdex** (`tcgdex_client.py`) se o tcgcsv cair/vier vazio num set — o TCGdex serve o MESMO `marketPrice` do TCGplayer, casado pelo MESMO `productId` (não é preço inventado nem estimativa; é outro espelho). É fallback de emergência (1 request/carta → lento); liga sozinho só na falha, desliga com `TCGDEX_FALLBACK=0`. Chaves = `FIRECRAWL_API_KEY` (só pro scan na nuvem, hoje dormente; roda local headful).

## O que este projeto é

Scanner de arbitragem **COMC → TCGPlayer** de cartas avulsas de Pokémon (o 5º
scanner de singles, irmão de CardTrader / MYP / Liga). Procura cartas listadas na
COMC mais baratas que o preço habitual no TCGPlayer e reporta os melhores deals
por **margem bruta**. Tese atual = **VALUE-BUY**: comprar boas cartas com desconto
e potencial de valorização (segurar), não só flip imediato. Roda **grátis** via
navegador real (Playwright headful). Detalhes técnicos completos: `README.md` e
este arquivo. (Notas de sessão ficam num `HANDOFF.md` local, fora do repositório.)

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
   - `Links` = **dois links clicáveis numa coluna só** — **[oferta](url COMC)** (a
     listagem na COMC) **·** **[referência](url TCGPlayer)** (onde conferir o preço).
     Formato canônico cross-scanner (igual ao MYP/Liga); lidos do deal, nunca
     inventados (`—` se faltarem);
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
