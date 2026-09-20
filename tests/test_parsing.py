"""Egyszerű, függőségmentes smoke-tesztek a parsing-logikára.

Mivel a fejlesztői sandboxból nem érhetők el a malmok élő oldalai
(kimenő hálózat csak engedélyezett listára megy), ezek a tesztek
szintetikus, a valós oldalak megfigyelt struktúráját utánzó HTML-en/
JSON-on futnak - így legalább a parsing-logika helyessége ellenőrizhető
hálózat nélkül is, gyorsan, minden módosítás után.

Futtatás:
    python3 tests/test_parsing.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import biom_malom, common, csaladellato, csoroszlya_farm, garat_malom  # noqa: E402


def test_parse_huf_price():
    assert common.parse_huf_price("3 750 Ft") == 3750
    assert common.parse_huf_price("790Ft") == 790
    assert common.parse_huf_price("Ártartomány: 600 Ft - 3000 Ft") == 600
    assert common.parse_huf_price("nincs ár") is None


def test_parse_package_kg():
    assert common.parse_package_kg("BL-80 Kenyérliszt 2kg") == 2.0
    assert common.parse_package_kg("Bio BL80 Wheat Bread Flour 2 kg") == 2.0
    assert common.parse_package_kg("1,5 kg") == 1.5
    assert common.parse_package_kg("nincs kiszerelés") is None


def test_make_product_price_per_kg():
    p = common.make_product(
        mill_id="teszt",
        mill_name="Teszt Malom",
        product_name="Teszt liszt",
        package_kg=2,
        price_huf=1000,
        in_stock=True,
        source_url="https://example.com",
    )
    assert p["price_per_kg_huf"] == 500
    assert p["data_source"] == "direct"


def test_extract_technical_specs():
    r1 = common.extract_technical_specs("Ez a liszt 14% feletti fehérjetartalom! Kiváló kenyérsütéshez.")
    assert r1["protein_percent_min"] == 14.0
    assert r1["protein_percent_max"] is None

    r2 = common.extract_technical_specs("Fehérjetartalom: 12-14%, 32-38% sikértartalom!, W-érték(350-370)")
    assert r2["protein_percent_min"] == 12.0
    assert r2["protein_percent_max"] == 14.0
    assert r2["gluten_percent_min"] == 32.0
    assert r2["gluten_percent_max"] == 38.0
    assert r2["w_value_min"] == 350.0
    assert r2["w_value_max"] == 370.0

    r3 = common.extract_technical_specs("Fehérje: 9,8 g / 100 g")
    assert r3["protein_percent_min"] == 9.8
    assert r3["protein_percent_max"] == 9.8

    r4 = common.extract_technical_specs("Nincs semmilyen műszaki adat ebben a szövegben.")
    assert r4["protein_percent_min"] is None
    assert r4["gluten_percent_min"] is None
    assert r4["w_value_min"] is None


def test_csaladellato_product_page_parsing():
    fake_html = """
    <html><body>
      <main>
        <h1>Kecskeméti Kerecsen KENYÉR liszt BL-80 1kg</h1>
        <div class="price">790 Ft</div>
        <p>Elérhetőség: Raktáron</p>
        <p>18% feletti fehérjetartalom, kiváló sütőipari érték.</p>
      </main>
    </body></html>
    """
    product = csaladellato.parse_product_page("https://www.csaladellato.hu/termekek/x-1kg", fake_html)
    assert product["product_name"].startswith("Kecskeméti Kerecsen")
    assert product["package_kg"] == 1.0
    assert product["price_huf"] == 790
    assert product["price_per_kg_huf"] == 790
    assert product["in_stock"] is True
    assert product["protein_percent_min"] == 18.0


def test_garat_malom_variable_product_parsing():
    variations = [
        {
            "attributes": {"attribute_kiszereles": "1kg"},
            "display_price": 600,
            "is_in_stock": True,
        },
        {
            "attributes": {"attribute_kiszereles": "5kg"},
            "display_price": 3000,
            "is_in_stock": False,
        },
    ]
    variations_json = html.escape(json.dumps(variations), quote=True)
    fake_html = f"""
    <html><body>
      <h1 class="product_title">BL-80 Kenyérliszt</h1>
      <p>Ez egy nélkülözhetetlen összetevő a kenyérsütéshez.
      Adalékanyag-mentes, glutént tartalmaz. Fehérjetartalom: 12-14%,
      33-36% sikértartalom!, W-érték 300-330.</p>
      <form class="variations_form" data-product_variations="{variations_json}"></form>
    </body></html>
    """
    products = garat_malom.parse_product_page("https://garatmalom.hu/shop/bl-80-kenyerliszt/", fake_html)
    assert len(products) == 2
    by_kg = {p["package_kg"]: p for p in products}
    assert by_kg[1.0]["price_huf"] == 600
    assert by_kg[1.0]["in_stock"] is True
    assert by_kg[5.0]["price_huf"] == 3000
    assert by_kg[5.0]["in_stock"] is False
    for p in products:
        assert p["additive_free"] == "yes"
        assert p["additive_free_source"] == "scraped_page_text"
        assert p["price_per_kg_huf"] == 600  # mindkét kiszerelésnél kb. ugyanaz kg-onként
        assert p["protein_percent_min"] == 12.0
        assert p["protein_percent_max"] == 14.0
        assert p["gluten_percent_min"] == 33.0
        assert p["gluten_percent_max"] == 36.0
        assert p["w_value_min"] == 300.0
        assert p["w_value_max"] == 330.0


def test_csoroszlya_farm_products_json_parsing():
    fake_payload = {
        "products": [
            {
                "title": "Bio BL80 Wheat Bread Flour",
                "handle": "bio-bl80-wheat-bread-flour",
                "body_html": "<p>Kiváló kenyérliszt. <strong>13-15%</strong> fehérjetartalom.</p>",
                "variants": [
                    {"title": "2 kg", "price": "1400.00", "available": True},
                    {"title": "5 kg", "price": "3500.00", "available": False},
                ],
            }
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return fake_payload

    with patch.object(csoroszlya_farm.common, "get_session") as mock_get_session:
        mock_session = mock_get_session.return_value
        mock_session.get.return_value = FakeResponse()
        products = csoroszlya_farm.fetch_products()

    assert len(products) == 2
    by_kg = {p["package_kg"]: p for p in products}
    assert by_kg[2.0]["price_huf"] == 1400
    assert by_kg[2.0]["price_per_kg_huf"] == 700
    assert by_kg[2.0]["in_stock"] is True
    assert by_kg[5.0]["in_stock"] is False
    assert by_kg[2.0]["additive_free"] == "likely_organic"
    assert by_kg[2.0]["protein_percent_min"] == 13.0
    assert by_kg[2.0]["protein_percent_max"] == 15.0


def test_biom_malom_fallback_kovaszshop_parsing():
    fake_html = """
    <html><body>
      <div class="product-card" itemtype="http://schema.org/Product">
        <h3 itemprop="name">Biom Bio Liszt BL-55 2kg</h3>
        <span class="price" itemprop="price" content="1200">1 200 Ft</span>
        <p>Raktáron. 13-14% fehérjetartalom, 30-33% sikértartalom!</p>
      </div>
    </body></html>
    """

    class FakeResponse:
        status_code = 200
        text = fake_html

        def raise_for_status(self):
            return None

    with patch.object(biom_malom.common, "get_session") as mock_get_session:
        mock_session = mock_get_session.return_value
        mock_session.get.return_value = FakeResponse()
        products = biom_malom.try_fallback_kovaszshop()

    assert len(products) >= 1
    p = products[0]
    assert p["package_kg"] == 2.0
    assert p["price_huf"] == 1200
    assert p["in_stock"] is True
    assert p["data_source"] == "reseller_fallback_kovaszshop"
    assert p["protein_percent_min"] == 13.0
    assert p["protein_percent_max"] == 14.0
    assert p["gluten_percent_min"] == 30.0
    assert p["gluten_percent_max"] == 33.0


def run_all():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} teszt lefutott, mind sikeres.")


if __name__ == "__main__":
    run_all()
