"""PriceCharting (comc_scanner/pricecharting.py) — parsing e guardas, OFFLINE.

Trava a honestidade da 2ª referência do --iconic: nome+número+set+variante têm
que casar o slug, senão None (nunca a mediana de OUTRA carta)."""
from comc_scanner import pricecharting as pc


def test_norm_number():
    assert pc.norm_number("004/102") == "4"
    assert pc.norm_number("199/165") == "199"
    assert pc.norm_number("TG12/TG30") == "12"
    assert pc.norm_number(None) == "" and pc.norm_number("abc") == ""


def test_split_product_name_strips_number_suffix_and_parens():
    assert pc.split_product_name("Charizard ex - 199/165") == ("Charizard ex", "")
    assert pc.split_product_name("Charizard (Black Dot Error)") == ("Charizard", "Black Dot Error")
    assert pc.split_product_name("Pikachu - 173/165") == ("Pikachu", "")


def test_set_tokens_drop_code_prefix_and_ampersand():
    assert pc.set_tokens("SV: Scarlet & Violet 151") == {"scarlet", "violet", "151"}
    assert pc.set_tokens("SV09: Journey Together") == {"journey", "together"}
    assert pc.set_tokens("EX Emerald") == {"emerald"}
    assert pc.set_tokens("Base Set") == {"base", "set"}


def test_console_matches_exact_bidirectional_and_unescapes():
    assert pc.console_matches("/game/pokemon-scarlet-&amp;-violet-151/charizard-ex-199",
                              "SV: Scarlet & Violet 151")
    assert pc.console_matches("/game/pokemon-base-set/charizard-4", "Base Set")
    assert not pc.console_matches("/game/pokemon-japanese-aquapolis/x-1", "Aquapolis")
    assert not pc.console_matches("/game/pokemon-base-set-2/charizard-4", "Base Set")


def test_slug_guard_number_first_token_and_all_tokens():
    assert pc.slug_matches("/game/pokemon-base-set/charizard-4", "Charizard", "004/102")
    assert not pc.slug_matches("/game/pokemon-base-set/charizard-4", "Charizard", "006/102")
    assert not pc.slug_matches("/game/pokemon-base-set/dark-charizard-4", "Charizard", "4/82")
    # 'charizard-6' não casa 'Charizard ex' (falta o 'ex')
    assert not pc.slug_matches("/game/pokemon-x/charizard-6", "Charizard ex - 006/165", "006/165")
    assert pc.slug_matches("/game/pokemon-scarlet-&amp;-violet-151/charizard-ex-199",
                           "Charizard ex - 199/165", "199/165")


def test_slug_guard_paren_variant_never_collapses_to_base_page():
    # produto COM parêntese exige token do parêntese no slug (senão seria a
    # mediana da versão base — carta diferente, preço diferente)
    assert not pc.slug_matches("/game/pokemon-base-set/charizard-4",
                               "Charizard (Black Dot Error)", "004/102")
    # e a página base não aceita tokens extras que não sejam de variante
    assert not pc.slug_matches("/game/pokemon-base-set/charizard-promo-4", "Charizard", "4")
    assert pc.slug_matches("/game/pokemon-neo-genesis/lugia-1st-edition-9", "Lugia", "009/111")


def test_pick_path_selects_variant_and_shortest_base():
    paths = ["/game/pokemon-neo-genesis/lugia-1st-edition-9",
             "/game/pokemon-neo-genesis/lugia-9",
             "/game/pokemon-neo-genesis/lugia-reverse-holo-9",
             "/game/pokemon-neo-genesis/lugia-10"]
    assert pc.pick_path(paths, "Lugia", "009/111", "Neo Genesis") == \
        "/game/pokemon-neo-genesis/lugia-9"
    assert pc.pick_path(paths, "Lugia", "9/111", "Neo Genesis", sub_type="1st Edition Holofoil") == \
        "/game/pokemon-neo-genesis/lugia-1st-edition-9"
    assert pc.pick_path(paths, "Lugia", "9/111", "Neo Genesis", sub_type="Reverse Holofoil") == \
        "/game/pokemon-neo-genesis/lugia-reverse-holo-9"
    assert pc.pick_path(paths, "Lugia", "9/111", "Neo Discovery") is None  # set errado


_PAGE = """
<div class="completed-auctions-used" id="x"><table>
<tr id="ebay-1"><td class="date">2026-08-30</td><td><span class="js-price">$120.00</span></td></tr>
<tr id="ebay-2"><td class="date">2026-08-29</td><td><span class="js-price">$1,000.00</span></td></tr>
<tr id="tcgplayer-3"><td class="date">2026-08-28</td><td><span class="js-price">$110.00</span></td></tr>
</table></div>
<div class="completed-auctions-graded"><table>
<tr id="ebay-9"><td class="date">2026-08-30</td><td><span class="js-price">$900.00</span></td></tr>
</table></div>
"""


def test_parse_sold_listings_only_ungraded_and_median():
    sales = pc.parse_sold_listings(_PAGE)
    assert [s["price"] for s in sales] == [120.0, 1000.0, 110.0]  # graded tab excluída
    median, n = pc.median_recent_sold(sales)
    assert (median, n) == (120.0, 3)  # mediana, não média (o $1000 não puxa)
    assert pc.median_recent_sold([]) == (None, 0)  # sem vendas → nunca inventa


def test_resolve_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(pc, "search_card_urls", lambda q, cache_dir=None: ["/game/pokemon-x/other-1"])
    assert pc.resolve_pc_ref("Charizard", "4/102", "Base Set") is None


def test_resolve_never_raises_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(pc, "search_card_urls", boom)
    assert pc.resolve_pc_ref("Charizard", "4/102", "Base Set") is None
