"""Command-line entry point: python -m comc_scanner {scan|list-groups|validate-slugs|warm|capture}."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import VALID_ERAS, load_settings
from .groups import SCAN_GROUPS, VALID_GROUP_NUMBERS, describe_groups, group_sets
from .logging_setup import setup_logging
from .pipeline import Scanner

log = logging.getLogger("comc_scanner.cli")


def _add_scan_args(p: argparse.ArgumentParser) -> None:
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--group", help="grupo canônico 1-4 (ver `list-groups`) ou `all` "
                                     "(os 4 em sequência); define os sets E a era")
    sel.add_argument("--sets", help="allowlist de sets separada por vírgula (nomes/abrevs)")
    p.add_argument("--era", choices=VALID_ERAS, help="era dos sets (default: do env)")
    p.add_argument("--min-discount", type=int,
                   help="desconto mínimo em %% INTEIRO sobre a referência (default 20)")
    p.add_argument("--min-price", type=float,
                   help="piso do preço COMC em US$ (default 10 = regra R$50; 0 desliga)")
    p.add_argument("--top-n", type=int, help="máximo de deals gravados/reportados")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--raw-only", action="store_true", help="só cartas soltas NM")
    scope.add_argument("--slabs-only", action="store_true", help="só cartas gradadas")
    p.add_argument("--all-pokemon", action="store_true",
                   help="desliga o filtro de Pokémon icônicos (analisa todas as cartas)")
    p.add_argument("--chase-only", action="store_true",
                   help="só raridades de perseguição (dropa Common/Uncommon/Rare)")
    p.add_argument("--min-confidence", type=float, help="confiança mínima de match p/ a lista")
    p.add_argument("--max-pages", type=int, help="máx. de páginas COMC por set/passada (0=todas)")
    p.add_argument("--max-run-seconds", type=int, help="orçamento de tempo (0=ilimitado)")
    p.add_argument("--interval", type=int, help="segundos entre flushes parciais")
    # Compatibilidade com a skill/comandos antigos: o scan é SEMPRE headful e SEMPRE
    # começa do zero (sem cursor) — as flags são aceitas e não fazem nada.
    p.add_argument("--headful", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--restart", action="store_true", help=argparse.SUPPRESS)


def _parse_group(value: str | None) -> list[int] | None:
    if value is None:
        return None
    if str(value).lower() == "all":
        return sorted(VALID_GROUP_NUMBERS)
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--group deve ser 1-4 ou 'all' (recebi {value!r})")
    if n not in VALID_GROUP_NUMBERS:
        raise argparse.ArgumentTypeError(f"--group deve ser 1-4 ou 'all' (recebi {value!r})")
    return [n]


def _apply_overrides(settings, args) -> None:
    if getattr(args, "top_n", None) is not None:
        settings.top_n = args.top_n
    if getattr(args, "interval", None) is not None:
        settings.scan_interval_s = args.interval
    if getattr(args, "min_discount", None) is not None:
        settings.min_discount_percent = args.min_discount
    if getattr(args, "min_price", None) is not None:
        settings.min_comc_price = args.min_price
    if getattr(args, "chase_only", False):
        settings.chase_only = True
    if getattr(args, "min_confidence", None) is not None:
        settings.min_match_confidence = args.min_confidence
    if getattr(args, "sets", None):
        settings.set_allowlist = tuple(s.strip() for s in args.sets.split(",") if s.strip())
    if getattr(args, "max_pages", None) is not None:
        settings.max_pages_per_set = args.max_pages
    if getattr(args, "max_run_seconds", None) is not None:
        settings.max_run_seconds = args.max_run_seconds
    if getattr(args, "raw_only", False):
        settings.scan_slabs = False
    if getattr(args, "slabs_only", False):
        settings.scan_raw = False
    if getattr(args, "all_pokemon", False):
        settings.iconic_only = False
    settings.comc_headless = False  # Cloudflare da COMC só limpa em navegador com janela


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comc_scanner", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="scanner único: cartas soltas NM + slabs, por grupo/sets")
    _add_scan_args(p_scan)

    sub.add_parser("list-groups", help="lista os 4 grupos canônicos (sets + era); sem rede")

    p_val = sub.add_parser("validate-slugs", help="valida ao vivo slugs pendentes do catálogo")
    p_val.add_argument("--revalidate", action="store_true", help="re-testa também os validados")

    p_warm = sub.add_parser("warm", help="abre o navegador p/ limpar o Cloudflare (perfil persiste)")
    p_warm.add_argument("--wait", type=int, default=30, help="segundos com a janela aberta")
    p_warm.add_argument("--url", help="URL da COMC para aquecer (default: vitrine Pokémon)")

    p_cap = sub.add_parser("capture", help="salva uma página COMC renderizada (fixtures)")
    p_cap.add_argument("--url", help="URL da COMC (default: vitrine Pokémon)")
    p_cap.add_argument("--out", default="tests/fixtures/comc_sample.html", help="arquivo de saída")
    return parser


def _resolve_era(args, settings, group: int | None = None) -> str:
    """Era efetiva: o grupo manda (SV=recent, WotC=vintage); `--era` conflitante só avisa."""
    era = getattr(args, "era", None) or settings.default_era
    if group:
        g_era = SCAN_GROUPS[group].era
        if getattr(args, "era", None) and args.era != g_era:
            log.warning("--era %s conflita com --group %d (era efetiva do grupo: %s); "
                        "o grupo manda.", args.era, group, g_era)
        era = g_era
    return era


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list-groups":
        print(describe_groups())
        return 0
    setup_logging(logging.INFO)
    settings = load_settings()
    _apply_overrides(settings, args)

    if args.command == "warm":
        ok = Scanner(settings).warm_profile(wait_s=args.wait, url=args.url)
        print("Warm-up:", "OK — perfil pronto." if ok
              else "não confirmou a página de resultados (resolva o desafio na janela e repita).")
        return 0 if ok else 1
    if args.command == "capture":
        from .comc_scraper import build_browse_url

        Scanner(settings).capture(args.url or build_browse_url(settings, page=1), args.out)
        return 0
    if args.command == "validate-slugs":
        results = Scanner(settings).validate_slugs(revalidate=args.revalidate)
        for name, count in sorted(results.items()):
            status = "OK" if count > 0 else ("CF-BLOCK" if count < 0 else "EMPTY")
            print(f"  {status:8s} {name}  (page-1 listings: {max(count, 0)})")
        return 0 if all(c > 0 for c in results.values()) else 1

    # scan
    try:
        groups = _parse_group(args.group)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    scanner = Scanner(settings)
    if groups is None:
        era = _resolve_era(args, settings)
        era = era if era != "all" else "vintage"
        scanner.run_scan(era, label=era)
        return 0
    label = "all" if len(groups) > 1 else f"grupo{groups[0]}"
    best = None
    for n in groups:
        settings.set_allowlist = tuple(group_sets(n))
        best = scanner.run_scan(_resolve_era(args, settings, n), label=label, best=best)
        if scanner._stop:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
