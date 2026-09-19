"""Biom Malom Bóly adapter.

Ez a legbizonytalanabb adapter. A malom saját oldala (biomliszt.hu)
build közben JS-renderltnek tűnt (a termékadat nem szerepelt a
kezdeti HTML-ben), ezért Playwright-tal (headless böngésző) próbáljuk
meg elsődlegesen - de mivel a fejlesztői sandboxból nem volt
elérhető a domain (kimenő hálózat csak engedélyezett listára megy
innen), ez a rész NEM lett élesben tesztelve, csak best-effort,
általános heurisztikákkal írva.

Ha a közvetlen scraping nem hoz eredményt, a kovaszshop.hu
viszonteladói oldalra esünk vissza - ez MÁSODLAGOS forrás, és minden
ebből származó terméknél data_source="reseller_fallback_kovaszshop"
jelölést kapunk, amit a frontendnek fel kell tüntetnie.

TEENDŐ ÉLES FUTTATÁS UTÁN: ha a try_direct() nem talál termékeket,
nézd meg a GitHub Actions log kimenetét (a Playwright oldal
screenshotját/HTML-jét érdemes menteni debug módban), és pontosítsd a
szelektorokat a valódi biomliszt.hu struktúra alapján.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from . import common

MILL_ID = "biom_malom"
MILL_NAME = "Biom Malom Bóly"
DIRECT_BASE_URL = "https://www.biomliszt.hu"
# Sorban kipróbált lehetséges shop-útvonalak, mert a build közben nem
# derült ki egyértelműen, melyik az élő webshop oldal.
DIRECT_CANDIDATE_PATHS = ["/", "/shop", "/webshop", "/termekek", "/bolt"]

FALLBACK_URLS = [
    "https://www.kovaszshop.hu/biom-koves-bio-malom-111",
    "https://www.kovaszshop.hu/alapanyagok/biom-koves-malom-182",
]

PRICE_PER_KG_RE = re.compile(r"(\d[\d\s]*)\s*Ft\s*/\s*kg", re.IGNORECASE)


def _guess_flour_type(title: str) -> Optional[str]:
    t = title.lower()
    if "tönköly" in t or "tonkoly" in t:
        return "tönköly"
    if "rozs" in t:
        return "rozs"
    if "búza" in t or "buza" in t:
        return "búza"
    return None


def try_direct() -> List[dict]:
    """Best-effort Playwright scraping a biomliszt.hu-ról.

    Óvatosan van írva: minden hibát elnyel és üres listát ad vissza,
    hogy az aggregátor biztonságosan tovább tudjon lépni a fallback-ra.
    Nem lett élesben tesztelve a build sandbox hálózati korlátai miatt.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    products: List[dict] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=common.USER_AGENT)

            for path in DIRECT_CANDIDATE_PATHS:
                url = DIRECT_BASE_URL + path
                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                except Exception:
                    continue

                # generikus heurisztika: keressünk "... Ft" mintát tartalmazó,
                # ismétlődő kártya-szerű elemeket
                cards = page.locator(
                    "css=[class*='product'], [class*='card'], li, article"
                )
                count = min(cards.count(), 200)
                for i in range(count):
                    try:
                        text = cards.nth(i).inner_text(timeout=1000)
                    except Exception:
                        continue
                    if "Ft" not in text or "liszt" not in text.lower():
                        continue
                    price_huf = common.parse_huf_price(text)
                    package_kg = common.parse_package_kg(text)
                    if price_huf is None:
                        continue
                    name_line = text.splitlines()[0].strip() if text.splitlines() else "Biom liszt"

                    products.append(
                        common.make_product(
                            mill_id=MILL_ID,
                            mill_name=MILL_NAME,
                            product_name=name_line,
                            package_kg=package_kg,
                            price_huf=price_huf,
                            in_stock=None,
                            stock_note="Automatikus felismerés, ellenőrizendő",
                            source_url=url,
                            flour_type=_guess_flour_type(name_line),
                            additive_free="likely_organic",
                            additive_free_source="mill_meta_default",
                            organic_certified=True,
                            organic_cert_body="Bio Garancia Magyarország, HU-ÖKO-02",
                            data_source="direct",
                        )
                    )

                if products:
                    break  # találtunk valamit ezen az útvonalon, nem kell tovább próbálkozni

            browser.close()
    except Exception:
        return []

    return products


def try_fallback_kovaszshop() -> List[dict]:
    session = common.get_session()
    products: List[dict] = []

    for url in FALLBACK_URLS:
        try:
            resp = session.get(url, timeout=common.REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception:
            continue

        soup = BeautifulSoup(resp.text, "lxml")

        # Shoprenter-alapú oldalak gyakran itemprop schema.org microdata-t
        # használnak SEO céljából - ezt próbáljuk elsőként.
        item_cards = soup.select('[itemtype*="Product"], [class*="product"]')
        for card in item_cards:
            name_el = card.select_one('[itemprop="name"]') or card.select_one("h2, h3, .name, .product-name")
            price_el = card.select_one('[itemprop="price"]') or card.select_one(".price")
            if not name_el or not price_el:
                continue

            name = name_el.get_text(strip=True)
            if "liszt" not in name.lower() and "biom" not in name.lower():
                continue

            price_text = price_el.get("content") or price_el.get_text(strip=True)
            price_huf = common.parse_huf_price(str(price_text))
            package_kg = common.parse_package_kg(name)

            card_text = card.get_text(" ", strip=True).lower()
            in_stock = None
            if "elfogyott" in card_text or "várólist" in card_text or "varolist" in card_text:
                in_stock = False
            elif "raktáron" in card_text or "raktaron" in card_text or "készleten" in card_text:
                in_stock = True

            products.append(
                common.make_product(
                    mill_id=MILL_ID,
                    mill_name=MILL_NAME,
                    product_name=name,
                    package_kg=package_kg,
                    price_huf=price_huf,
                    in_stock=in_stock,
                    stock_note="Viszonteladói (kovaszshop.hu) forrásból - a malom saját oldala nem volt közvetlenül scrape-elhető",
                    source_url=url,
                    flour_type=_guess_flour_type(name),
                    additive_free="likely_organic",
                    additive_free_source="mill_meta_default",
                    organic_certified=True,
                    organic_cert_body="Bio Garancia Magyarország, HU-ÖKO-02",
                    data_source="reseller_fallback_kovaszshop",
                )
            )

    return products


def fetch_products() -> List[dict]:
    direct = try_direct()
    if direct:
        return direct
    return try_fallback_kovaszshop()


if __name__ == "__main__":
    print(json.dumps(fetch_products(), ensure_ascii=False, indent=2))
