# Liszt árfigyelő

Nem hivatalos, tájékoztató jellegű eszköz, amely kedvenc kézműves/bio malmok liszt-kínálatát,
árait, ár/kg-ját, készletadatait és szállítási feltételeit gyűjti össze és hasonlítja össze egy
helyen. Naponta automatikusan frissül (GitHub Actions), az eredmény egy egyfájlos statikus
weboldal (`index.html`), amit GitHub Pages szolgál ki.

**Induló malmok:** Kecskeméti Családellátó, Garat Malom, Csoroszlya Farm, Biom Malom Bóly.

## Hogyan működik

```
scrapers/aggregate.py  --  naponta lefut (GitHub Actions), meghívja mind a 4 adaptert
  ├─ scrapers/csaladellato.py
  ├─ scrapers/csoroszlya_farm.py     (Shopify /products.json - a legmegbízhatóbb forrás)
  ├─ scrapers/garat_malom.py         (WooCommerce, a variáció-JSON-t olvassa ki)
  └─ scrapers/biom_malom.py          (Playwright a saját oldalra, kovaszshop.hu fallback)
        ↓
data/mill_meta.json   --  kézzel karbantartott: szállítási feltételek, adalékmentesség/bio
                           alapértelmezés malmonként - ITT javítható, kód nélkül
        ↓
data/current.json     --  a legutóbbi futás eredménye (ezt tölti be a frontend)
data/history.jsonl    --  append-only napló, MINDEN futás egy sor, lejárat nélkül
                           (hosszútávú ár-trendekhez)
        ↓
index.html             --  egyfájlos frontend, ezt látja a látogató GitHub Pages-en
```

## Első futtatás (fontos!)

A scraper scriptek build közben nem lettek élesben tesztelve a valódi malom-oldalak ellen
(a fejlesztői környezetből ez technikailag nem volt elérhető). A parsing-logikát szintetikus
mintaadaton teszteltük (`tests/test_parsing.py`), de az élő oldalak apró eltérései miatt
valószínű, hogy az első futás után finomítani kell egy-két szelektort - főleg a Kecskeméti
Családellátó és a Biom Malom Bóly adapterénél (ld. lent, "Ismert korlátok").

Ezért:

1. Push után menj a repó **Actions** fülére, válaszd a **"Liszt adatok frissítése"** workflow-t,
   és indítsd el kézzel (**Run workflow** gomb - ez a `workflow_dispatch` trigger).
2. Nézd át a futás logját: melyik malomnál hány terméket talált, van-e hiba.
3. Ha egy malomnál 0 terméket talál vagy hibát dob, nézd meg a `data/current.json`
   `errors` mezőjét, és igazítsd a megfelelő `scrapers/<malom>.py` fájlt a látott
   HTML-struktúra alapján.
4. Ha minden rendben, a napi ütemezett futás (`cron`, 05:00 UTC) onnantól magától megy.

## GitHub Pages beállítása

Repó **Settings → Pages → Source: Deploy from a branch → Branch: main / (root)**.
Nincs build lépés, az `index.html` közvetlenül a repó gyökeréből szolgál ki.

## Adalékmentesség és bio jelzés

Ez a mező NEM naponta újra-scrapelt adat (kivéve a Garat Malomnál, ahol a terméklap
kifejezetten kimondja - onnan a scraper automatikusan kinyeri). A többi malomnál a
`data/mill_meta.json`-ban tárolt, kézzel kutatott alapértelmezés érvényesül
(`additive_free_default`). Ha erről pontosabb infót szerzel (pl. a malom válaszol egy
megkeresésre), csak ezt a fájlt kell szerkeszteni - kód-módosítás nélkül, a következő
futás már az új értéket mutatja.

Lehetséges értékek: `yes` (kimondott nyilatkozat), `likely_organic` (bio tanúsítvány, de
nincs kimondott állítás), `no`, `unknown`.

## Új malom hozzáadása

1. `data/mill_meta.json`-ba vegyél fel egy új bejegyzést (szállítás, adalékmentesség,
   bio-státusz).
2. Írj egy új `scrapers/<uj_malom>.py`-t a meglévők mintájára (`fetch_products()`
   függvény, ami `common.make_product(...)` rekordok listáját adja vissza).
3. Regisztráld a `scrapers/aggregate.py` `ADAPTERS` szótárában.
4. Ha van rá minta, írj hozzá tesztet a `tests/test_parsing.py`-ba szintetikus HTML/JSON-nal.

## Ismert korlátok / build közbeni megjegyzések

- **Kecskeméti Családellátó**: a webshop platformja nem volt egyértelműen azonosítható
  build közben, ezért az adapter szöveg/regex-alapú, defenzív kinyerést használ CSS
  class-ok helyett. Működnie kell, de érdemes az első futás után ellenőrizni, különösen
  a készlet-detekciót (`IN_STOCK_PATTERNS` / `OUT_OF_STOCK_PATTERNS` a
  `scrapers/csaladellato.py`-ban).
- **Biom Malom Bóly**: a saját oldal (biomliszt.hu) JS-renderltnek tűnt, a termékadat nem
  szerepelt a kezdeti HTML-ben. A Playwright-alapú közvetlen scraper (`try_direct()`)
  best-effort, általános heurisztikákkal írt kód, ami build közben nem volt tesztelhető
  élesben. Ha nem hoz eredményt, a kód automatikusan a kovaszshop.hu viszonteladói oldalra
  esik vissza (`data_source: "reseller_fallback_kovaszshop"` jelöléssel, amit a frontend
  is jelez). Érdemes az első pár futás után megnézni, sikerül-e a közvetlen scraping, és
  ha nem, a `DIRECT_CANDIDATE_PATHS` listát / a kártya-detekciós heurisztikát pontosítani
  a biomliszt.hu tényleges struktúrája alapján.
- **Garat Malom** és **Csoroszlya Farm**: ezek a legmegbízhatóbb adapterek - a Csoroszlya
  Farm a dokumentált, stabil Shopify `/products.json` végpontot használja, a Garat Malom
  pedig a WooCommerce alapfunkcióját (a `data-product_variations` attribútumot), ami nem
  témafüggő.
- A szállítási díj-adatok (`data/mill_meta.json` `shipping` mezői) 2026-09-19-i
  kutatáson alapulnak, egy részük (`confidence: "medium_needs_reverify"`) érdemes
  időnként újra-ellenőrizni a malmok oldalán, mert ezek nem automatikusan frissülnek.

## Etikai/technikai megjegyzések a scraping-hez

- Minden kérés egyedi, azonosító User-Agentet küld (`scrapers/common.py`), ami jelzi,
  hogy nem hivatalos, tájékoztató célú, alacsony gyakoriságú (napi 1x) lekérdezésről van
  szó, elérhetőséggel.
- A futás naponta egyszer megy, nem valós idejű, nem terheli a malmok szervereit.
- Ha egy malom kéri, hogy ne scrapeljük az oldalát, vedd ki az adaptert a
  `scrapers/aggregate.py` `ADAPTERS` szótárából.

## Helyi fejlesztés / tesztelés

```bash
pip install -r requirements.txt
playwright install chromium   # csak a Biom Malom adapterhez kell

# gyors, hálózat nélküli smoke tesztek a parsing-logikára:
python3 tests/test_parsing.py

# teljes adatgyűjtés futtatása helyben (éles hálózati hívásokkal):
python3 -m scrapers.aggregate

# frontend megtekintése helyben:
python3 -m http.server 8000
# majd nyisd meg: http://localhost:8000/index.html
```

## Tervezett funkciók

- Kosár-szintű teljes költség kalkulátor (recepthez szükséges liszt mennyiség alapján)
- Kedvenc termékek / figyelőlista, értesítés készletre kerüléskor vagy áresésnél
- Minimum rendelési mennyiség jelzése
- További malmok (bővíthető, ld. fent)

---

Készítette: Udvari István · Adatelemző
