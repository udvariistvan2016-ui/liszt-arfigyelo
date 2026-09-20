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


_PROTEIN_FELETTI_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*%\s*feletti\s*fehérjetartalom", re.IGNORECASE
)

# Egy százalékos érték (vagy tartomány), pl. "14%" vagy "12-14%" - csak a
# TARTOMÁNY VÉGÉN van "%" jel (ahogy a valós oldalakon látott mintákban is:
# "12-14%", nem "12%-14%").
_PCT_RANGE = r"(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|és)\s*(\d+(?:[.,]\d+)?))?\s*%"

# A százalék-tartomány a kulcsszó UTÁN jöhet ("Fehérjetartalom: 12-14%")
# vagy ELŐTTE ("12-14% fehérjetartalom") - a valós oldalakon mindkét
# szórend előfordulhat, ezért mindkettőt megpróbáljuk.
_PROTEIN_BEFORE_RE = re.compile(_PCT_RANGE + r"\s*fehérje", re.IGNORECASE)
_PROTEIN_AFTER_RE = re.compile(
    r"fehérje\w*\s*(?:tartalom)?\s*[:\-]?\s*" + _PCT_RANGE, re.IGNORECASE
)
_PROTEIN_GRAM_RE = re.compile(r"fehérje\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*g\b", re.IGNORECASE)

_GLUTEN_BEFORE_RE = re.compile(_PCT_RANGE + r"\s*sikér", re.IGNORECASE)
_GLUTEN_AFTER_RE = re.compile(
    r"sikér\w*\s*(?:tartalom)?\s*[:\-]?\s*" + _PCT_RANGE, re.IGNORECASE
)

_W_VALUE_RE = re.compile(
    r"W[\s\-]?érték\D{0,12}(\d{2,3})(?:\s*(?:-|–)\s*(\d{2,3}))?", re.IGNORECASE
)


def _to_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    return float(text.replace(",", "."))


def extract_technical_specs(text: str) -> dict:
    """Kinyeri a fehérjetartalmat, sikértartalmat és W-értéket egy termékleírás
    szövegéből, ha ott szerepel (ez NEM minden malomnál elérhető - ahol nincs
    találat, a mezők None-ok maradnak).

    Ritkán változó, "metaadat" jellegű infó, akárcsak az adalékmentesség -
    ezért egyszerű, megengedő regex-mintákkal dolgozunk, nem szigorú
    táblázat-parsing-gal. Támogatott minták, a valós oldalakon megfigyeltek
    alapján:
      - "14% feletti fehérjetartalom!"          -> protein_percent_min=14, max=None
      - "Fehérjetartalom: 12-14%"                -> protein_percent_min=12, max=14
      - "Fehérje: 9,8 g" (100 g-ra vetítve)       -> protein_percent_min=max=9.8
      - "32-38% sikértartalom!"                   -> gluten_percent_min=32, max=38
      - "W-érték 350-370" / "W érték(350-370)"    -> w_value_min=350, max=370
    """
    result = {
        "protein_percent_min": None,
        "protein_percent_max": None,
        "gluten_percent_min": None,
        "gluten_percent_max": None,
        "w_value_min": None,
        "w_value_max": None,
    }
    if not text:
        return result

    m = _PROTEIN_FELETTI_RE.search(text)
    if m:
        result["protein_percent_min"] = _to_float(m.group(1))
    else:
        m = _PROTEIN_BEFORE_RE.search(text) or _PROTEIN_AFTER_RE.search(text)
        if m:
            result["protein_percent_min"] = _to_float(m.group(1))
            result["protein_percent_max"] = _to_float(m.group(2)) or result["protein_percent_min"]
        else:
            m = _PROTEIN_GRAM_RE.search(text)
            if m:
                val = _to_float(m.group(1))
                result["protein_percent_min"] = val
                result["protein_percent_max"] = val

    m = _GLUTEN_BEFORE_RE.search(text) or _GLUTEN_AFTER_RE.search(text)
    if m:
        result["gluten_percent_min"] = _to_float(m.group(1))
        result["gluten_percent_max"] = _to_float(m.group(2)) or result["gluten_percent_min"]

    m = _W_VALUE_RE.search(text)
    if m:
        result["w_value_min"] = _to_float(m.group(1))
        result["w_value_max"] = _to_float(m.group(2)) or result["w_value_min"]

    return result


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
    technical_specs: Optional[dict] = None,
) -> dict:
    """Egységesített termék-rekord, amit minden adapter ugyanígy ad vissza."""
    price_per_kg = None
    if price_huf is not None and package_kg:
        price_per_kg = round(price_huf / package_kg)

    product_id = slugify(f"{mill_id}-{product_name}-{package_kg}kg")

    specs = technical_specs or {}
    default_specs = {
        "protein_percent_min": None,
        "protein_percent_max": None,
        "gluten_percent_min": None,
        "gluten_percent_max": None,
        "w_value_min": None,
        "w_value_max": None,
    }
    default_specs.update({k: v for k, v in specs.items() if v is not None})

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
        "protein_percent_min": default_specs["protein_percent_min"],
        "protein_percent_max": default_specs["protein_percent_max"],
        "gluten_percent_min": default_specs["gluten_percent_min"],
        "gluten_percent_max": default_specs["gluten_percent_max"],
        "w_value_min": default_specs["w_value_min"],
        "w_value_max": default_specs["w_value_max"],
        "source_url": source_url,
        # "direct": a malom saját oldaláról; "reseller_fallback_<nev>": viszonteladói
        # forrásból, mert a malom saját oldala nem volt scrape-elhető - ezt a
        # frontendnek jól láthatóan jeleznie kell.
        "data_source": data_source,
        "last_checked": now_iso(),
    }
