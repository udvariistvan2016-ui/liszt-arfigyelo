"""Fő belépési pont: lefuttatja mind a négy malom-adaptert, összefésüli a
mill_meta.json statikus adataival, majd frissíti a data/current.json-t és
appendeli a data/history.jsonl-t.

Ezt hívja a GitHub Actions workflow (.github/workflows/update-data.yml)
naponta egyszer, de kézzel is futtatható:

    python -m scrapers.aggregate

Egy malom hibája nem dönti be a teljes futást - ha egy adapter kivételt
dob, a hiba bekerül az "errors" mezőbe, a többi malom adata viszont
rendben frissül.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from . import biom_malom, csaladellato, csoroszlya_farm, garat_malom, common

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MILL_META_PATH = DATA_DIR / "mill_meta.json"
CURRENT_PATH = DATA_DIR / "current.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"

ADAPTERS = {
    "csaladellato": csaladellato,
    "csoroszlya_farm": csoroszlya_farm,
    "garat_malom": garat_malom,
    "biom_malom": biom_malom,
}


def load_mill_meta() -> dict:
    with open(MILL_META_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def enrich_with_mill_meta(products: list[dict], mill_meta: dict) -> None:
    """Helyben módosítja a termékeket: ahol a mező még csak alapértelmezés
    (mill_meta_default), ráírja a mill_meta.json aktuális értékét - így a
    mill_meta.json az egyetlen hely, amit szerkeszteni kell, ha változik
    egy malom adalékmentességi/bio státusza, kód-módosítás nélkül."""
    for product in products:
        meta = mill_meta.get(product["mill_id"])
        if not meta:
            continue
        if product.get("additive_free_source") == "mill_meta_default":
            product["additive_free"] = meta.get("additive_free_default", "unknown")
        if product.get("organic_certified") is None:
            product["organic_certified"] = meta.get("organic_certified")
        if not product.get("organic_cert_body"):
            product["organic_cert_body"] = meta.get("organic_cert_body")


def run() -> dict:
    mill_meta = load_mill_meta()

    all_products: list[dict] = []
    errors: dict[str, str] = {}

    for mill_id, adapter in ADAPTERS.items():
        try:
            products = adapter.fetch_products()
            if not products:
                errors[mill_id] = "Az adapter nem talált egy terméket sem (üres eredmény)."
            enrich_with_mill_meta(products, mill_meta)
            all_products.extend(products)
        except Exception as exc:  # noqa: BLE001 - szándékosan széles, hogy egy malom hibája ne dőjtse be a többit
            errors[mill_id] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)

    generated_at = common.now_iso()

    current = {
        "generated_at": generated_at,
        "mills": mill_meta,
        "products": all_products,
        "errors": errors,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CURRENT_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # history: append-only, lejárat nélkül - minden futás egy sor
    history_entry = {"generated_at": generated_at, "products": all_products}
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(history_entry, ensure_ascii=False) + "\n")

    return current


if __name__ == "__main__":
    result = run()
    print(f"Kész. {len(result['products'])} termék, {len(result['errors'])} hiba.")
    for mill_id, err in result["errors"].items():
        print(f"  - {mill_id}: {err}", file=sys.stderr)
