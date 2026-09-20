"""Csoroszlya Farm (csoroszlyafarm.hu) adapter.

A bolt Shopify-alapú, ezért a nyilvános, dokumentált /products.json
végpontot használjuk - ez a legmegbízhatóbb forrásunk, nem kell HTML-t
parse-olni. Ld.: minden Shopify shop kínálja ezt, view-only, hitelesítés
nélkül.
"""
from __future__ import annotations

import re
from typing import List

from . import common

_TAG_RE = re.compile(r"<[^>]+>")

MILL_ID = "csoroszlya_farm"
MILL_NAME = "Csoroszlya Farm"
BASE_URL = "https://csoroszlyafarm.hu"
COLLECTION_HANDLE = "liszt"
PRODUCTS_JSON_URL = f"{BASE_URL}/collections/{COLLECTION_HANDLE}/products.json"

# Shopify products.json lapoz, ha 250-nél több termék van egy kollekcióban -
# a liszt kollekcióban ez nem várható, de a biztonság kedvéért limitet adunk.
PAGE_LIMIT = 250


def _guess_flour_type(title: str) -> str | None:
    title_low = title.lower()
    if "tönköly" in title_low or "tonkoly" in title_low:
        return "tönköly"
    if "rozs" in title_low:
        return "rozs"
    if "alakor" in title_low:
        return "alakor"
    if "borsó" in title_low or "borso" in title_low:
        return "borsó"
    if "búza" in title_low or "buza" in title_low:
        return "búza"
    return None


def fetch_products() -> List[dict]:
    session = common.get_session()
    resp = session.get(
        PRODUCTS_JSON_URL,
        params={"limit": PAGE_LIMIT},
        timeout=common.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    products: List[dict] = []
    for shopify_product in payload.get("products", []):
        title = shopify_product.get("title", "")
        handle = shopify_product.get("handle", "")
        product_url = f"{BASE_URL}/products/{handle}"
        whole_grain = "teljes kiőrlésű" in title.lower() or "teljes kiorlesu" in title.lower()

        # a Shopify products.json "body_html" mezője (ha van) a termékleírás,
        # ott néha szerepel fehérje-/sikértartalom, W-érték - ugyanaz a ritkán
        # változó "metaadat" jelleg, mint az adalékmentesség
        body_html = shopify_product.get("body_html") or ""
        description_text = _TAG_RE.sub(" ", body_html)
        technical_specs = common.extract_technical_specs(description_text)

        for variant in shopify_product.get("variants", []):
            variant_title = variant.get("title", "")
            package_kg = common.parse_package_kg(variant_title) or common.parse_package_kg(title)
            price_huf = None
            if variant.get("price") is not None:
                # Shopify a "price" mezőt stringként adja, pl. "1400.00"
                try:
                    price_huf = round(float(variant["price"]))
                except (TypeError, ValueError):
                    price_huf = None

            in_stock = variant.get("available")

            products.append(
                common.make_product(
                    mill_id=MILL_ID,
                    mill_name=MILL_NAME,
                    product_name=f"{title} ({variant_title})" if variant_title and variant_title != "Default Title" else title,
                    package_kg=package_kg,
                    price_huf=price_huf,
                    in_stock=in_stock,
                    stock_note=None if in_stock else "Hamarosan elérhető / elfogyott",
                    source_url=product_url,
                    flour_type=_guess_flour_type(title),
                    whole_grain=whole_grain,
                    additive_free="likely_organic",
                    additive_free_source="mill_meta_default",
                    organic_certified=True,
                    organic_cert_body=None,
                    technical_specs=technical_specs,
                )
            )

    return products


if __name__ == "__main__":
    import json

    print(json.dumps(fetch_products(), ensure_ascii=False, indent=2))
