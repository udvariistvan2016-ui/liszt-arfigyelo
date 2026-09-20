"""Garat Malom (garatmalom.hu) adapter.

A bolt WordPress + WooCommerce alapú. Ahol lehet, a WooCommerce CORE
viselkedésére támaszkodunk, nem a téma egyedi CSS class-aira, mert az
stabilabb sok témán át:

- Variálható (méretes) termékeknél a WooCommerce a <form
  class="variations_form" ...> elem "data-product_variations"
  attribútumába teszi az összes variáció JSON-jét (ár, készlet,
  attribútumok). Ez a WooCommerce alapfunkciója, nem témafüggő.
- Az adalékmentességi állítást ("Adalékanyag-mentes") egyszerű
  szövegkereséssel azonosítjuk a termékleírásban.

MEGJEGYZÉS: ezt a scriptet nem lehetett élesben tesztelni a fejlesztői
sandboxból (kimenő hálózat csak engedélyezett domainekre megy innen),
ezért az első GitHub Actions futtatást manuálisan (workflow_dispatch)
érdemes elindítani és a kimenetet átnézni, mielőtt a napi ütemezésre
hagynánk.
"""
from __future__ import annotations

import html
import json
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import common

MILL_ID = "garat_malom"
MILL_NAME = "Garat Malom"
BASE_URL = "https://garatmalom.hu"
SHOP_URL = f"{BASE_URL}/shop/"

ADDITIVE_FREE_PATTERNS = [
    re.compile(r"adal[eé]kanyag[- ]mentes", re.IGNORECASE),
    re.compile(r"adal[eé]kmentes", re.IGNORECASE),
]

_VARIATIONS_ATTR_RE = re.compile(
    r'data-product_variations="([^"]+)"', re.IGNORECASE
)


def _guess_flour_type(title: str) -> Optional[str]:
    t = title.lower()
    if "kamut" in t:
        return "kamut"
    if "tönköly" in t or "tonkoly" in t:
        return "tönköly"
    if "rozs" in t:
        return "rozs"
    if "királybúza" in t or "kiralybuza" in t:
        return "királybúza"
    if "búza" in t or "buza" in t:
        return "búza"
    return None


def _guess_bl_code(title: str) -> Optional[str]:
    match = re.search(r"\b([A-Z]{2,4}-?\d{2,3})\b", title.upper())
    return match.group(1) if match else None


def discover_product_urls(session) -> List[str]:
    """Végigmegy a shop kategória oldalain, összegyűjti a termék-URL-eket."""
    urls: set[str] = set()
    page = 1
    while True:
        page_url = SHOP_URL if page == 1 else f"{SHOP_URL}page/{page}/"
        resp = session.get(page_url, timeout=common.REQUEST_TIMEOUT)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        found_this_page = set()
        for a in soup.select('a[href*="/shop/"]'):
            href = a.get("href", "")
            if not href:
                continue
            full = urljoin(BASE_URL, href)
            # csak konkrét termékoldalak, ne a shop gyökér vagy kategória/lapozó linkek
            if re.match(r"^https://garatmalom\.hu/shop/[a-z0-9-]+/?$", full) and full.rstrip("/") != SHOP_URL.rstrip("/"):
                found_this_page.add(full)

        if not found_this_page or found_this_page.issubset(urls):
            # nincs új termék ezen az oldalon -> vége a lapozásnak
            urls.update(found_this_page)
            break

        urls.update(found_this_page)
        page += 1
        if page > 20:  # védőháló végtelen ciklus ellen
            break

    return sorted(urls)


def _extract_variations(html_text: str) -> Optional[list[dict]]:
    match = _VARIATIONS_ATTR_RE.search(html_text)
    if not match:
        return None
    raw = html.unescape(match.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _extract_simple_price(soup: BeautifulSoup) -> Optional[int]:
    price_el = soup.select_one(".price .woocommerce-Price-amount, .summary .price, .price")
    if price_el:
        return common.parse_huf_price(price_el.get_text(" ", strip=True))
    # utolsó esély: keressünk bármilyen "... Ft" mintát az oldal elején
    text = soup.get_text(" ", strip=True)
    return common.parse_huf_price(text)


def parse_product_page(url: str, html_text: str) -> List[dict]:
    soup = BeautifulSoup(html_text, "lxml")

    title_el = soup.select_one("h1.product_title, h1.entry-title, h1")
    title = title_el.get_text(strip=True) if title_el else url.rstrip("/").rsplit("/", 1)[-1]

    full_text = soup.get_text(" ", strip=True)
    additive_free = "unknown"
    additive_free_source = "default"
    if any(p.search(full_text) for p in ADDITIVE_FREE_PATTERNS):
        additive_free = "yes"
        additive_free_source = "scraped_page_text"

    technical_specs = common.extract_technical_specs(full_text)

    flour_type = _guess_flour_type(title)
    bl_code = _guess_bl_code(title)
    whole_grain = "teljes kiőrlésű" in title.lower() or "teljes kiorlesu" in title.lower() or (bl_code or "").endswith(("200", "112"))

    variations = _extract_variations(html_text)
    products: List[dict] = []

    if variations:
        for var in variations:
            attrs = var.get("attributes", {})
            size_label = next(iter(attrs.values()), "") if attrs else ""
            package_kg = common.parse_package_kg(str(size_label)) or common.parse_package_kg(title)
            price_huf = None
            display_price = var.get("display_price")
            if display_price is not None:
                try:
                    price_huf = round(float(display_price))
                except (TypeError, ValueError):
                    price_huf = None
            in_stock = var.get("is_in_stock")

            products.append(
                common.make_product(
                    mill_id=MILL_ID,
                    mill_name=MILL_NAME,
                    product_name=f"{title} ({size_label})" if size_label else title,
                    package_kg=package_kg,
                    price_huf=price_huf,
                    in_stock=in_stock,
                    stock_note=None,
                    source_url=url,
                    flour_type=flour_type,
                    bl_code=bl_code,
                    whole_grain=whole_grain,
                    additive_free=additive_free,
                    additive_free_source=additive_free_source,
                    organic_certified=False,
                    technical_specs=technical_specs,
                )
            )
    else:
        # nem variálható (egyetlen kiszerelésű) termék
        package_kg = common.parse_package_kg(title)
        price_huf = _extract_simple_price(soup)
        in_stock_el = soup.select_one(".stock")
        in_stock = None
        if in_stock_el:
            in_stock = "outofstock" not in " ".join(in_stock_el.get("class", [])).lower() and "elfogyott" not in in_stock_el.get_text(strip=True).lower()

        products.append(
            common.make_product(
                mill_id=MILL_ID,
                mill_name=MILL_NAME,
                product_name=title,
                package_kg=package_kg,
                price_huf=price_huf,
                in_stock=in_stock,
                stock_note=None,
                source_url=url,
                flour_type=flour_type,
                bl_code=bl_code,
                whole_grain=whole_grain,
                additive_free=additive_free,
                additive_free_source=additive_free_source,
                organic_certified=False,
                technical_specs=technical_specs,
            )
        )

    return products


def fetch_products() -> List[dict]:
    session = common.get_session()
    product_urls = discover_product_urls(session)

    all_products: List[dict] = []
    for url in product_urls:
        resp = session.get(url, timeout=common.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            continue
        all_products.extend(parse_product_page(url, resp.text))

    return all_products


if __name__ == "__main__":
    print(json.dumps(fetch_products(), ensure_ascii=False, indent=2))
