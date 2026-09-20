"""Kecskeméti Családellátó (csaladellato.hu) adapter.

A bolt platformja build közben nem volt egyértelműen azonosítható
(valószínűleg egyedi/kevésbé elterjedt rendszer), ezért ez az adapter
tudatosan defenzív, szöveg/regex-alapú kinyerést használ a törékeny
CSS-class-ok helyett. Megfigyelés: minden kiszerelés (1/2/5/10 kg)
KÜLÖN termékoldal saját URL-lel (nem egy legördülő menüs variáció),
pl.:
  .../termekek/kecskemeti-kerecsen-kenyer-liszt-bl-80-1kg
  .../termekek/kecskemeti-kerecsen-kenyer-liszt-bl-80-2kg

FONTOS: ezt a scriptet a fejlesztői sandboxból nem lehetett élesben
tesztelni (kimenő hálózat csak engedélyezett domainekre megy innen).
Az első GitHub Actions futtatást (workflow_dispatch) érdemes manuálisan
elindítani és a kimenetet átnézni/finomítani, mielőtt a napi
ütemezésre hagynánk - különösen a stock-detekciós szövegmintákat.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import common

MILL_ID = "csaladellato"
MILL_NAME = "Kecskeméti Családellátó"
BASE_URL = "https://www.csaladellato.hu"
CATEGORY_URL = f"{BASE_URL}/termekkategoriak/lisztek"

IN_STOCK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [r"raktáron", r"raktaron", r"készleten"]]
OUT_OF_STOCK_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [r"nincs raktáron", r"nincs készleten", r"elfogyott", r"nem elérhető"]
]


def _guess_flour_type(title: str) -> Optional[str]:
    t = title.lower()
    if "tönköly" in t or "tonkoly" in t:
        return "tönköly"
    if "rozs" in t:
        return "rozs"
    if "királybúza" in t or "kiralybuza" in t:
        return "királybúza"
    if "búza" in t or "buza" in t or "kerecsen" in t:
        return "búza"
    return None


def _guess_bl_code(title: str) -> Optional[str]:
    match = re.search(r"\b([A-Z]{2,4}-?\d{2,3})\b", title.upper())
    return match.group(1) if match else None


def discover_product_urls(session) -> List[str]:
    urls: set[str] = set()
    page_url = CATEGORY_URL
    seen_pages: set[str] = set()

    for _ in range(20):  # védőháló
        if page_url in seen_pages:
            break
        seen_pages.add(page_url)

        resp = session.get(page_url, timeout=common.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            break
        soup = BeautifulSoup(resp.text, "lxml")

        for a in soup.select('a[href*="/termekek/"]'):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin(BASE_URL, href)
            if re.match(r"^https://(www\.)?csaladellato\.hu/termekek/[a-z0-9-]+/?$", full):
                urls.add(full)

        # következő oldal keresése (rel=next, vagy "Következő" szövegű link)
        next_link = soup.select_one('a[rel="next"]')
        if not next_link:
            for a in soup.select("a"):
                if "következő" in a.get_text(strip=True).lower():
                    next_link = a
                    break

        if not next_link or not next_link.get("href"):
            break
        page_url = urljoin(BASE_URL, next_link["href"])

    return sorted(urls)


def parse_product_page(url: str, html_text: str) -> Optional[dict]:
    soup = BeautifulSoup(html_text, "lxml")

    title_el = soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else soup.title.get_text(strip=True) if soup.title else url

    package_kg = common.parse_package_kg(title)

    # ár: keressünk egy "... Ft" mintát a cím közelében / a fő tartalomban.
    # A teljes oldal szövegéből az ELSŐ Ft-mintát vesszük, mert a termékoldal
    # tetején jellemzően az aktuális ár szerepel, a lap alján lévő
    # "kapcsolódó termékek" árai csak ez után jönnek.
    main_el = soup.select_one("main") or soup.body or soup
    price_huf = common.parse_huf_price(main_el.get_text(" ", strip=True)[:1500])

    full_text = soup.get_text(" ", strip=True).lower()
    in_stock: Optional[bool] = None
    if any(p.search(full_text) for p in OUT_OF_STOCK_PATTERNS):
        in_stock = False
    elif any(p.search(full_text) for p in IN_STOCK_PATTERNS):
        in_stock = True

    # a regex-minták re.IGNORECASE-szel dolgoznak, a kisbetűs full_text is jó nekik
    technical_specs = common.extract_technical_specs(full_text)

    return common.make_product(
        mill_id=MILL_ID,
        mill_name=MILL_NAME,
        product_name=title,
        package_kg=package_kg,
        price_huf=price_huf,
        in_stock=in_stock,
        stock_note=None,
        source_url=url,
        flour_type=_guess_flour_type(title),
        bl_code=_guess_bl_code(title),
        whole_grain="teljes kiőrlésű" in title.lower() or "teljes kiorlesu" in title.lower(),
        additive_free="unknown",
        additive_free_source="mill_meta_default",
        organic_certified=False,
        technical_specs=technical_specs,
    )


def fetch_products() -> List[dict]:
    session = common.get_session()
    product_urls = discover_product_urls(session)

    products: List[dict] = []
    for url in product_urls:
        resp = session.get(url, timeout=common.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            continue
        product = parse_product_page(url, resp.text)
        if product:
            products.append(product)

    return products


if __name__ == "__main__":
    print(json.dumps(fetch_products(), ensure_ascii=False, indent=2))
