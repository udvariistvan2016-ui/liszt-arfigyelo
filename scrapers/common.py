"""Közös segédfüggvények a malom-adapterekhez.

Ez a modul semmilyen malomhoz nem kötött logikát nem tartalmaz - csak
általános eszközöket: HTTP session udvarias User-Agenttel, ár-parsingot,
egységesített termék-rekord felépítést.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

import requests

USER_AGENT = (
    "LisztArfigyeloBot/1.0 (+https://github.com/; nem hivatalos, "
    "tajekoztato jellegu ar-osszehasonlito eszkoz, kis gyakorisagu, "
    "udvarias lekerdezes; kapcsolat: udvari.istvan2016@gmail.com)"
)

REQUEST_TIMEOUT = 20


def get_session() -> requests.Session:
    """Egységes, udvarias HTTP session minden adapterhez."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.5",
        }
    )
    return session


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


_PRICE_RE = re.compile(r"[\d\s.]+(?=\s*(?:Ft|HUF|ft))", re.IGNORECASE)


def parse_huf_price(text: str) -> Optional[int]:
    """Kinyer egy forint-árat egy szöveges cellából, pl. '3 750 Ft' -> 3750."""
    if not text:
        return None
    match = _PRICE_RE.search(text.replace("\xa0", " "))
    if not match:
        # próbáljunk meg minden számjegyet kiszedni, ha nincs "Ft" jelölés
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None
    digits = re.sub(r"[^\d]", "", match.group(0))
    return int(digits) if digits else None


_KG_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.IGNORECASE)


def parse_package_kg(text: str) -> Optional[float]:
    """Kinyer egy kiszerelést kilogrammban, pl. '2kg' vagy '2 kg' -> 2.0."""
    if not text:
        return None
    match = _KG_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def make_product(
    *,
    mill_id: str,
    mill_name: str,
    product_name: str,
    package_kg: Optional[float],
    price_huf: Optional[int],
    in_stock: Optional[bool],
    stock_note: Optional[str] = None,
    source_url: str,
    flour_type: Optional[str] = None,
    bl_code: Optional[str] = None,
    whole_grain: Optional[bool] = None,
    additive_free: str = "unknown",
    additive_free_source: str = "default",
    organic_certified: Optional[bool] = None,
    organic_cert_body: Optional[str] = None,
    data_source: str = "direct",
) -> dict:
    """Egységesített termék-rekord, amit minden adapter ugyanígy ad vissza."""
    price_per_kg = None
    if price_huf is not None and package_kg:
        price_per_kg = round(price_huf / package_kg)

    product_id = slugify(f"{mill_id}-{product_name}-{package_kg}kg")

    return {
        "id": product_id,
        "mill_id": mill_id,
        "mill": mill_name,
        "product_name": product_name.strip(),
        "flour_type": flour_type,
        "bl_code": bl_code,
        "whole_grain": whole_grain,
        "package_kg": package_kg,
        "price_huf": price_huf,
        "price_per_kg_huf": price_per_kg,
        "in_stock": in_stock,
        "stock_note": stock_note,
        "additive_free": additive_free,
        "additive_free_source": additive_free_source,
        "organic_certified": organic_certified,
        "organic_cert_body": organic_cert_body,
        "source_url": source_url,
        # "direct": a malom saját oldaláról; "reseller_fallback_<nev>": viszonteladói
        # forrásból, mert a malom saját oldala nem volt scrape-elhető - ezt a
        # frontendnek jól láthatóan jeleznie kell.
        "data_source": data_source,
        "last_checked": now_iso(),
    }
