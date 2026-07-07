"""Command-line entry point: python -m comc_scanner {run|once|refresh-prices|dry-run}."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import VALID_ERAS, load_settings
from .groups import SCAN_GROUPS, VALID_GROUP_NUMBERS, describe_groups, group_sets
from .logging_setup import setup_logging
from .pipeline import Scanner

log = logging.getLogger("comc_scanner.cli")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--era", choices=VALID_ERAS, help="set era to scan (default from env)")
    p.add_argument("--top-n", type=int, help="number of deals to keep/report")
    p.add_argument("--interval", type=int, help="seconds between partial flushes")
    p.add_argument("--min-margin", type=float, help="min gross margin (e.g. 0.30)")
    p.add_argument("--min-price", type=float,
                   help="min COMC ask in USD (default 10 = the R$50 floor; 0 disables)")
    p.add_argument("--chase-only", action="store_true",
                   help="value-buy mode: keep only chase rarities (drops Common/Uncommon/Rare)")
    p.add_argument("--min-confidence", type=float, help="min match confidence for top list")
    p.add_argument("--margin-mode", choices=["gross", "markup"], help="margin formula")
    # --sets and --group are two ways to build the same set allowlist — never both.
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--sets", help="comma-separated set allowlist (names/abbrevs)")
    sel.add_argument("--group", type=int, choices=VALID_GROUP_NUMBERS,
                     help="canonical scan group 1-4 (TARGETED MODE ONLY; see `list-groups`); "
                          "sets the allowlist AND derives the era (SV=recent, WotC=vintage)")
    p.add_argument("--max-pages", type=int, help="max COMC pages per set (0=until empty)")
    p.add_argument("--max-sets-per-chunk", type=int, help="sets to process per run (0=all)")
    p.add_argument("--max-run-seconds", type=int, help="time budget per run (0=unlimited)")
    p.add_argument("--condition", help="COMC condition band facet, e.g. EX-NM, LP")
    p.add_argument("--include-graded", action="store_true", help="include graded cards")
    p.add_argument("--fetch-mode", choices=["firecrawl", "playwright"],
                   help="COMC transport (default firecrawl: headless, no browser)")
    p.add_argument("--headful", action="store_true", help="show the browser window (playwright)")
    p.add_argument("--no-sheets", action="store_true", help="never push to Google Sheets")


def _apply_overrides(settings, args) -> None:
    if args.top_n is not None:
        settings.top_n = args.top_n
    if args.interval is not None:
        settings.scan_interval_s = args.interval
    if args.min_margin is not None:
        settings.min_gross_margin = args.min_margin
    if args.min_price is not None:
        settings.min_comc_price = args.min_price
    if args.chase_only:
        settings.chase_only = True
    if args.min_confidence is not None:
        settings.min_match_confidence = args.min_confidence
    if args.margin_mode:
        settings.margin_mode = args.margin_mode
    if args.sets:
        settings.set_allowlist = tuple(s.strip() for s in args.sets.split(",") if s.strip())
    if getattr(args, "group", None):
        # Group -> set-name allowlist, fed through the same substring/alias
        # matcher as --sets (segments._matches_allowlist is NOT exact-match: e.g.
        # "Team Rocket" also contains-matches "EX Team Rocket Returns"). That is
        # why --group is restricted to `targeted` (enforced in main()), where the
        # final target list is an EXACT-name intersection with the slug catalog.
        settings.set_allowlist = tuple(group_sets(args.group))
    if args.max_pages is not None:
        settings.max_pages_per_set = args.max_pages
    if args.max_sets_per_chunk is not None:
        settings.max_sets_per_chunk = args.max_sets_per_chunk
    if args.max_run_seconds is not None:
        settings.max_run_seconds = args.max_run_seconds
    if args.condition:
        settings.comc_condition_band = args.condition
    if args.include_graded:
        settings.comc_include_graded = True
    if args.fetch_mode:
        settings.comc_fetch_mode = args.fetch_mode
    if args.headful:
        settings.comc_headless = False
        settings.comc_fetch_mode = "playwright"  # headful only makes sense with a browser
    if args.no_sheets:
        settings.gsheets_credentials_json = ""
        settings.gsheets_id = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comc_scanner", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="continuous incremental loop")
    _add_common(p_run)
    p_run.add_argument("--restart", action="store_true", help="ignore saved cursor")

    p_once = sub.add_parser("once", help="scan one chunk, flush, exit")
    _add_common(p_once)
    p_once.add_argument("--restart", action="store_true", help="ignore saved cursor")

    p_broad = sub.add_parser(
        "broad", help="headless functional scan: sweep the plain COMC browse, keep TCG matches"
    )
    _add_common(p_broad)
    p_broad.add_argument("--restart", action="store_true", help="ignore saved page cursor")

    p_targeted = sub.add_parser(
        "targeted", help="scan specific TCG sets via COMC set-path browse (uses comc_set_slugs.json)"
    )
    _add_common(p_targeted)
    p_targeted.add_argument("--restart", action="store_true", help="ignore saved cursor")

    p_refresh = sub.add_parser("refresh-prices", help="force re-download the TCGCSV snapshot")
    _add_common(p_refresh)

    p_dry = sub.add_parser("dry-run", help="match/report a local fixture or saved page (no live COMC)")
    _add_common(p_dry)
    g = p_dry.add_mutually_exclusive_group(required=True)
    g.add_argument("--listings", help="path to a listings JSON fixture")
    g.add_argument("--html", help="path to a saved COMC page (parsed, then matched)")

    p_cap = sub.add_parser("capture", help="save a rendered COMC page to disk (needs Playwright)")
    _add_common(p_cap)
    p_cap.add_argument("--url", help="COMC URL to capture (default: Pokemon browse page)")
    p_cap.add_argument("--out", default="tests/fixtures/comc_sample.html", help="output HTML path")

    p_warm = sub.add_parser(
        "warm", help="headful browser warm-up: clear Cloudflare once so later playwright "
                     "runs work headless+free (no Firecrawl)"
    )
    _add_common(p_warm)
    p_warm.add_argument("--wait", type=int, default=30,
                        help="seconds to keep the window open for the challenge to clear")
    p_warm.add_argument("--url", help="COMC URL to warm on (default: Pokemon browse page)")

    p_parse = sub.add_parser("parse-file", help="print listings parsed from a saved COMC page")
    _add_common(p_parse)
    p_parse.add_argument("--html", required=True, help="path to a saved COMC page")

    sub.add_parser(
        "list-groups", help="print the 4 canonical scan groups (sets + era) and exit; no network"
    )

    p_val = sub.add_parser(
        "validate-slugs", help="live-validate pending comc_set_slugs.json entries "
                               "(page-1 scrape each; flips validated flag in place)"
    )
    _add_common(p_val)
    p_val.add_argument("--revalidate", action="store_true",
                       help="re-check every slug, not just the pending ones")

    return parser


def _resolve_era(args, settings) -> str:
    """Effective era for the run. A `--group` implies its era (SV=recent,
    WotC=vintage); a conflicting explicit `--era` only warns — the group wins."""
    era = getattr(args, "era", None) or settings.default_era
    group = getattr(args, "group", None)
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
    if args.command == "list-groups":  # pure catalog print — no settings/network needed
        print(describe_groups())
        return 0
    if getattr(args, "group", None) and args.command != "targeted":
        # Outside `targeted` the allowlist is applied by substring/alias matching
        # only (no exact slug-catalog intersection), so a group name like
        # "Team Rocket" would leak onto e.g. "EX Team Rocket Returns" (2004).
        parser.error("--group só é suportado no modo targeted; use --sets nos demais modos")
    setup_logging(logging.INFO)
    settings = load_settings()
    _apply_overrides(settings, args)
    era = _resolve_era(args, settings)

    if args.command == "parse-file":
        Scanner(settings).parse_file(args.html)
        return 0

    if args.command == "warm":
        ok = Scanner(settings).warm_profile(wait_s=args.wait, url=args.url)
        print("Warm-up:", "OK — profile ready for headless playwright runs." if ok
              else "did not confirm a results page (solve the challenge in the window, then retry).")
        return 0 if ok else 1

    scanner = Scanner(settings)
    if args.command == "validate-slugs":
        results = scanner.validate_slugs(revalidate=args.revalidate)
        for name, count in sorted(results.items()):
            status = "OK" if count > 0 else ("CF-BLOCK" if count < 0 else "EMPTY")
            print(f"  {status:8s} {name}  (page-1 listings: {max(count, 0)})")
        return 0 if results and all(c > 0 for c in results.values()) else (0 if not results else 1)
    if args.command == "refresh-prices":
        scanner.refresh_prices(era)
    elif args.command == "dry-run":
        scanner.dry_run(listings_path=args.listings, era=era, html_path=args.html)
    elif args.command == "capture":
        from .comc_scraper import build_browse_url

        url = args.url or build_browse_url(settings, page=1)
        scanner.capture(url, args.out)
    elif args.command == "once":
        scanner.run_once(era, resume=not args.restart)
    elif args.command == "broad":
        scanner.run_broad(era, resume=not args.restart)
    elif args.command == "targeted":
        scanner.run_targeted(era if era != "all" else "vintage", resume=not args.restart)
    elif args.command == "run":
        if args.restart:
            from .segments import ChunkCursor

            ChunkCursor(era, scanner.client.snapshot_date()).clear()
        scanner.run_loop(era)
    return 0


if __name__ == "__main__":
    sys.exit(main())
