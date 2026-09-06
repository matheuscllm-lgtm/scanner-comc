# Política de aquisição e cobertura — 2026-09-06

- Universo padrão: todas as cartas Pokémon identificáveis no catálogo, em todas as eras; raw e slabs habilitados. Lista icônica e chase são filtros opcionais, não obrigatórios.
- Não significa cobertura integral de todo o inventário COMC: o coletor trabalha com cartas e sets cadastrados. Selados, acessórios e produtos fora do catálogo não têm avaliação automática neste scanner. Sets sem caminho validado são informados no relatório; cartas sem match aparecem em revisão sem referência.
- Raw NM pode usar TCGplayer market, com fallback mid/low marcado para revisão. EX-NM nunca recebe preço NM ou LP por presunção: vai para seção própria sem margem calculada, inclusive se um .env antigo incluir EX-NM na allowlist. LP exige pelo menos 3 vendas LP da mesma carta e variante.
- Slabs mantêm as notas permitidas, referência por certificadora/nota/variante exatas e avisos de liquidez. Não há filtro automático de baixa população.
- Desconto mínimo 20%, piso US$10, sem teto de compra padrão. Valores e ranking são brutos; fotos, estado físico, vendedor, custos e população de slabs permanecem explicitamente pendentes. OK é validação do match/preço, não aprovação de aquisição.
- Vendedor só é mostrado quando fornecido pelos dados coletados; ausência vira “não identificado”. Não inferir reputação nem nota futura a partir de NM. Conferir frente/verso da cópia exata pelo link da oferta antes de aquisição; registrar custos reais antes de calcular retorno líquido.
- TOP_N=0 significa todos os resultados, inclusive revisão; limite positivo é opção explícita. Nenhuma coleta é iniciada por atualização de código. Resultados somente no chat conforme DELIVERY_CHAT.md.
- `scan --era all` respeita todas as eras do catálogo; `--group all` percorre os 12 grupos. `--iconic-only` restringe a lista; `--chase-only` restringe raridades; `--all-pokemon` mantém todos.

## Execução sob solicitação

`python -m comc_scanner scan --era all` — todas as eras, cartas soltas e slabs.

`python -m comc_scanner scan --era all --raw-only` — cartas soltas, todas as eras.

Usar cache novo por execução, gerar com comc_summary.py e colar a entrega no chat. A revisão sem referência é separada dos candidatos com preço validado. Não publicar resultados no GitHub.
