"""Public web pages for the open perfume database, in English and Dutch (/nl/…):
/database, /database/search, /perfume/<id>-<slug>, /note/<slug>, /notes, /brand/<slug>.

Only perfumes that are worth a page get one: at least PAGE_MIN_CONFIRMED notes confirmed by two or more
shops (catalog.CONFIRM_SHOPS). Everything else answers 404, so search engines never see near-empty pages.
A note gets a page once it is confirmed in at least one published perfume and has an English name; a brand
once it has a published perfume.

What a page shows comes only from our own data: the catalog (shop facts + Open Beauty Facts), the
anonymous price reports (app.stats and the daily lows), reviewed note descriptions (note_texts.json, written
by the local model from a cited source and checked by hand, see llm_review.py) and bottle photos from Open
Beauty Facts (CC BY-SA, cached under IMG_DIR, see refresh_images). Nothing from Fragrantica, which is only
linked to.

All values are escaped with html.escape. Links are root-relative, so the pages work on any host that
forwards these paths to the API; <link rel="canonical"> and the hreflang links use PAGES_BASE. The pages run
no scripts (the JSON-LD block is data).
"""
import hashlib
import html
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date

import catalog
import obf

PAGE_MIN_CONFIRMED = int(os.environ.get("PAGE_MIN_CONFIRMED", "3"))
BASE = os.environ.get("PAGES_BASE", "https://fragrancenotes.app").rstrip("/")
SITE = "https://fragrancenotes.app/"
STORE = "https://chromewebstore.google.com/detail/fragrance-notes/hhhiolpcmkdkegcmjmpglcnfolohldgc"
IMG_DIR = os.environ.get("IMG_DIR", os.path.join(os.path.dirname(os.environ.get("DB_PATH", "/data/prices.db")), "img"))
IMG_MAX = 600_000          # bytes; Open Beauty Facts' 400 px photos are 20-60 KB
IMG_RECHECK = 30 * 86400   # look again for a photo after 30 days
TEXTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "note_texts.json")

CONC = {"edt": "Eau de Toilette", "edp": "Eau de Parfum", "edc": "Eau de Cologne", "parfum": "Parfum",
        "extrait": "Extrait de Parfum"}
CURRENCY = {"EUR": "€", "GBP": "£", "USD": "$", "CHF": "CHF ", "PLN": "zł ", "SEK": "kr ", "DKK": "kr "}
TIER_KEYS = ("top", "heart", "base")
LANGS = ("en", "nl")


def _n(one, many):
    return lambda n: (one if n == 1 else many).format(n=n)


T = {
    "en": {
        "langName": "English", "getExt": "Get the extension", "back": "← Back to the database",
        "theDb": "The database", "allNotes": "All notes", "privacy": "Privacy", "source": "Source",
        "footData": 'From the open Fragrance Notes perfume database: what perfume shops show on their own pages, shared '
                    'anonymously by users, and <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>. Available under the '
                    '<a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Photos from Open Beauty Facts (CC BY-SA).',
        "footNot": "Not affiliated with the brands or shops named. Prices change; check the shop.",
        "months": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
        "gender": {"m": "For men", "f": "For women", "u": "Unisex"},
        "tiers": (("top", "Top", "first minutes"), ("heart", "Heart", "first hours"), ("base", "Base", "the dry-down")),
        "shops": _n("{n} shop", "{n} shops"), "sources": _n("{n} source", "{n} sources"),
        "perfumes": _n("{n} perfume", "{n} perfumes"), "perfume": "perfume",
        "by": "{name} by {brand}", "bottleOf": "Bottle of {name} by {brand}", "photo": "Photo",
        "trustShops": _n("<b>{n} source</b> describes it", "<b>{n} sources</b> describe it"),
        "trustNotes": _n("<b>{n} note</b> confirmed", "<b>{n} notes</b> confirmed"), "lastSeen": "Last seen",
        "notes": "Notes", "notesSub": "As the shops describe it. A note gets a ✓ once two different shops list it.",
        "legendOk": "Confirmed by 2 or more shops", "legendOne": "Named by one shop so far",
        "prices": "Prices", "pricesSub": "Lowest price per size in the last {days} days at {shops}, shared anonymously by Fragrance Notes users.",
        "size": "Size", "lowest": "Lowest", "at": "At", "perMl": "Per ml", "range": "Range", "oneShop": "1 shop",
        "atEachShop": "{size} at each shop", "chartTitle": "Lowest price for {size}, day by day",
        "chartLabel": "from {low} to {high}",
        "family": "Fragrance family", "sizes": "Sizes", "describedBy": "Described by", "barcodes": "Barcodes (EAN)",
        "more": "More about it", "moreFrag": "Accords, reviews and votes on {link}", "details": "Details",
        "helpT": "See this on every shop page",
        "helpD": "The free Fragrance Notes extension shows the notes, accords and prices right on the product page. Turn on “Help other perfume lovers” and the shops you visit help confirm these notes.",
        "getFN": "Get Fragrance Notes",
        "perfumeDesc": "Notes of {full} ({conc}), confirmed by several shops: {notes}.",
        "perfumeTitle": "{full} – notes and prices | Fragrance Notes",
        "smellsLike": "What it smells like", "comesFrom": "Where it comes from",
        "aiNote": "Written by our own AI model from the source text, checked by hand before it went online.",
        "sourceWord": "Source", "confirmedBy": "confirmed by {n} shops", "perfumeNote": "Perfume note",
        "alsoWrite": "Shops also write", "perfumesWith": "Perfumes with {note}", "whereSits": "Where it sits",
        "pairedWith": "Often paired with", "noteDesc": "Perfumes with a confirmed {note} note in the open Fragrance Notes database.",
        "noteTitle": "{name} – what it smells like, perfumes with this note | Fragrance Notes",
        "notesLead": "Every note that is confirmed in at least one perfume, with the number of perfumes.",
        "notesTitle": "All perfume notes | Fragrance Notes", "nothingYet": "Nothing here yet.",
        "brandKind": "Perfume house", "brandLead": "{n} by {brand} with notes confirmed by several shops.",
        "brandMore": "{n} more perfumes by {brand} are in the database, but don't have enough confirmed notes for a page yet.",
        "brandTitle": "{brand} perfumes – notes and prices | Fragrance Notes",
        "from": "{size} from",
        "dbH1": "An open perfume database, built while you shop",
        "dbLead": "Every perfume shop describes its perfumes a little differently. When people who use Fragrance Notes visit a shop page, it can share what that shop says. Where shops agree, a note gets confirmed. Everything is free to use.",
        "searchPh": "Search a perfume, brand or note", "search": "Search",
        "statPerfumes": "perfumes", "statBrands": "brands", "statConfirmed": "with confirmed notes", "statShops": "shops with prices",
        "counted": "Counted {day}. It grows with every shop page people visit.",
        "howH": "How a note gets confirmed",
        "howIntro": "Nothing here is copied from other sites. It's only what perfume shops show on their own product pages, collected by people who turned sharing on.",
        "step1T": "You visit a perfume page", "step1D": "On any of 300+ supported shops, as you normally would. Sharing is off until you turn on “Help other perfume lovers”.",
        "step2T": "The shop's facts are shared", "step2D": "The notes, family, sizes, barcode and price that the shop itself shows. Never who you are or what you buy.",
        "step3T": "Shops agree, it's confirmed", "step3D": 'Once two different shops list the same note, it gets <span class="chip">confirmed</span> and shows up in the extension and on this site.',
        "withConfirmed": "Perfumes with confirmed notes", "pageRule": "A perfume gets its own page once at least {n} of its notes are confirmed.",
        "nextT": "Yours could be next", "nextD": "Visit a perfume at two shops with sharing on.",
        "brandsH": "Brands", "notesH": "Most confirmed notes",
        "openH": "Open data",
        "openD1": 'The database is published under the <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Use it in your own app, research or site, as long as you name the source and share improvements under the same licence.',
        "openD2": 'It also includes perfume data from <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>.',
        "apiSearch": "Search", "apiOne": "One perfume", "apiStats": "Totals", "growBtn": "Help it grow: get the extension",
        "dsName": "Fragrance Notes open perfume database",
        "dbTitle": "The open perfume database | Fragrance Notes",
        "dbDesc": "An open perfume database built by shoppers: notes confirmed by several shops, sizes, barcodes and anonymous prices. Free under the Open Database License.",
        "noMatch": "No perfume page matches that yet.",
        "moreMatch": _n("{n} more perfume in the database matches, but doesn't have enough confirmed notes for a page yet.",
                        "{n} more perfumes in the database match, but don't have enough confirmed notes for a page yet."),
        "nfH": "Not here (yet)",
        "nfD": "This perfume or note has no page yet. A perfume gets one once at least {n} of its notes are confirmed by two different shops.",
    },
    "nl": {
        "langName": "Nederlands", "getExt": "Installeer de extensie", "back": "← Terug naar de database",
        "theDb": "De database", "allNotes": "Alle geurnoten", "privacy": "Privacy", "source": "Broncode",
        "footData": 'Uit de open parfumdatabase van Fragrance Notes: wat parfumwinkels op hun eigen pagina\'s laten zien, anoniem '
                    'gedeeld door gebruikers, en <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>. Beschikbaar onder de '
                    '<a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Foto\'s van Open Beauty Facts (CC BY-SA).',
        "footNot": "Niet verbonden aan de genoemde merken of winkels. Prijzen veranderen; kijk altijd even bij de winkel.",
        "months": "jan feb mrt apr mei jun jul aug sep okt nov dec".split(),
        "gender": {"m": "Voor mannen", "f": "Voor vrouwen", "u": "Unisex"},
        "tiers": (("top", "Top", "eerste minuten"), ("heart", "Hart", "eerste uren"), ("base", "Basis", "wat blijft hangen")),
        "shops": _n("{n} winkel", "{n} winkels"), "sources": _n("{n} bron", "{n} bronnen"),
        "perfumes": _n("{n} parfum", "{n} parfums"), "perfume": "parfum",
        "by": "{name} van {brand}", "bottleOf": "Fles {name} van {brand}", "photo": "Foto",
        "trustShops": _n("<b>{n} bron</b> beschrijft het", "<b>{n} bronnen</b> beschrijven het"),
        "trustNotes": _n("<b>{n} noot</b> bevestigd", "<b>{n} noten</b> bevestigd"), "lastSeen": "Laatst gezien",
        "notes": "Geurnoten", "notesSub": "Zoals de winkels het beschrijven. Een noot krijgt een ✓ zodra twee verschillende winkels hem noemen.",
        "legendOk": "Bevestigd door 2 of meer winkels", "legendOne": "Tot nu toe door één winkel genoemd",
        "prices": "Prijzen", "pricesSub": "Laagste prijs per inhoud in de afgelopen {days} dagen bij {shops}, anoniem gedeeld door gebruikers van Fragrance Notes.",
        "size": "Inhoud", "lowest": "Laagste", "at": "Bij", "perMl": "Per ml", "range": "Van – tot", "oneShop": "1 winkel",
        "atEachShop": "{size} per winkel", "chartTitle": "Laagste prijs voor {size}, per dag",
        "chartLabel": "van {low} tot {high}",
        "family": "Geurfamilie", "sizes": "Inhoud", "describedBy": "Beschreven door", "barcodes": "Barcodes (EAN)",
        "more": "Meer erover", "moreFrag": "Accoorden, reviews en stemmen op {link}", "details": "Details",
        "helpT": "Zie dit op elke winkelpagina",
        "helpD": "De gratis extensie Fragrance Notes toont de geurnoten, accoorden en prijzen direct op de productpagina. Zet “Help andere parfumliefhebbers” aan en de winkels die je bezoekt helpen deze noten bevestigen.",
        "getFN": "Installeer Fragrance Notes",
        "perfumeDesc": "Geurnoten van {full} ({conc}), bevestigd door meerdere winkels: {notes}.",
        "perfumeTitle": "{full} – geurnoten en prijzen | Fragrance Notes",
        "smellsLike": "Hoe het ruikt", "comesFrom": "Waar het vandaan komt",
        "aiNote": "Geschreven door ons eigen AI-model op basis van de brontekst, met de hand gecontroleerd voordat het online ging.",
        "sourceWord": "Bron", "confirmedBy": "bevestigd door {n} winkels", "perfumeNote": "Geurnoot",
        "alsoWrite": "Winkels schrijven ook", "perfumesWith": "Parfums met {note}", "whereSits": "Waar hij zit",
        "pairedWith": "Vaak samen met", "noteDesc": "Parfums met een bevestigde noot {note} in de open parfumdatabase van Fragrance Notes.",
        "noteTitle": "{name} – hoe het ruikt, parfums met deze geurnoot | Fragrance Notes",
        "notesLead": "Elke geurnoot die in minstens één parfum bevestigd is, met het aantal parfums.",
        "notesTitle": "Alle geurnoten | Fragrance Notes", "nothingYet": "Nog niets te zien.",
        "brandKind": "Parfumhuis", "brandLead": "{n} van {brand} met geurnoten die door meerdere winkels bevestigd zijn.",
        "brandMore": "Er staan nog {n} parfums van {brand} in de database, maar die hebben nog te weinig bevestigde noten voor een eigen pagina.",
        "brandTitle": "Parfums van {brand} – geurnoten en prijzen | Fragrance Notes",
        "from": "{size} vanaf",
        "dbH1": "Een open parfumdatabase, gebouwd terwijl je shopt",
        "dbLead": "Elke parfumwinkel beschrijft zijn parfums net iets anders. Als mensen met Fragrance Notes een winkelpagina bezoeken, kan de extensie delen wat die winkel zegt. Waar winkels het eens zijn, wordt een geurnoot bevestigd. Alles is vrij te gebruiken.",
        "searchPh": "Zoek een parfum, merk of geurnoot", "search": "Zoeken",
        "statPerfumes": "parfums", "statBrands": "merken", "statConfirmed": "met bevestigde noten", "statShops": "winkels met prijzen",
        "counted": "Geteld op {day}. Hij groeit met elke winkelpagina die mensen bezoeken.",
        "howH": "Hoe een geurnoot bevestigd wordt",
        "howIntro": "Niets hier is gekopieerd van andere sites. Het is alleen wat parfumwinkels op hun eigen productpagina's laten zien, verzameld door mensen die delen aan hebben gezet.",
        "step1T": "Je bezoekt een parfumpagina", "step1D": "Bij een van de 300+ ondersteunde winkels, zoals je normaal doet. Delen staat uit tot je “Help andere parfumliefhebbers” aanzet.",
        "step2T": "De gegevens van de winkel worden gedeeld", "step2D": "De geurnoten, familie, inhoud, barcode en prijs die de winkel zelf laat zien. Nooit wie je bent of wat je koopt.",
        "step3T": "Winkels zijn het eens: bevestigd", "step3D": 'Zodra twee verschillende winkels dezelfde noot noemen, wordt hij <span class="chip">bevestigd</span> en verschijnt hij in de extensie en op deze site.',
        "withConfirmed": "Parfums met bevestigde noten", "pageRule": "Een parfum krijgt een eigen pagina zodra minstens {n} van zijn noten bevestigd zijn.",
        "nextT": "Jouw parfum kan de volgende zijn", "nextD": "Bekijk een parfum bij twee winkels met delen aan.",
        "brandsH": "Merken", "notesH": "Meest bevestigde noten",
        "openH": "Open data",
        "openD1": 'De database valt onder de <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Gebruik hem in je eigen app, onderzoek of site, zolang je de bron noemt en verbeteringen onder dezelfde licentie deelt.',
        "openD2": 'Hij bevat ook parfumgegevens van <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>.',
        "apiSearch": "Zoeken", "apiOne": "Eén parfum", "apiStats": "Totalen", "growBtn": "Help hem groeien: installeer de extensie",
        "dsName": "Open parfumdatabase van Fragrance Notes",
        "dbTitle": "De open parfumdatabase | Fragrance Notes",
        "dbDesc": "Een open parfumdatabase, gebouwd door shoppers: geurnoten bevestigd door meerdere winkels, inhoud, barcodes en anonieme prijzen. Gratis onder de Open Database License.",
        "noMatch": "Nog geen parfumpagina die daarop past.",
        "moreMatch": _n("Er past nog {n} parfum in de database, maar die heeft te weinig bevestigde noten voor een pagina.",
                        "Er passen nog {n} parfums in de database, maar die hebben te weinig bevestigde noten voor een pagina."),
        "nfH": "(Nog) niet hier",
        "nfD": "Dit parfum of deze noot heeft nog geen pagina. Een parfum krijgt er een zodra minstens {n} van zijn noten door twee verschillende winkels bevestigd zijn.",
    },
}

# The Dutch name of a note: the first spelling of its line in catalog.NOTE_WORDS (written Dutch first).
NOTE_NL = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].split("|")[0].strip()
           for line in catalog.NOTE_WORDS.strip().splitlines() if ":" in line}


def load_texts(path=TEXTS_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}


TEXTS = load_texts()
e = html.escape


# ---------- small helpers ----------

def P(lang, path):
    """The path in a language: English without a prefix, Dutch under /nl."""
    return path if lang == "en" else f"/{lang}{path}"


def slug(s):
    return "-".join(catalog.plain(s).split())[:80] or "perfume"


def perfume_path(p):
    return f"/perfume/{p['id']}-{slug(p['brand'] + ' ' + p['name'])}"


def note_path(key):
    return "/note/" + "-".join(key.split())


def nice(key):
    return key[:1].upper() + key[1:]


def note_name(key, lang="en"):
    return nice(NOTE_NL.get(key, key) if lang == "nl" else key)


def day(s, lang="en"):
    try:
        d = date.fromisoformat(s)
        return f"{d.day} {T[lang]['months'][d.month - 1]} {d.year}"
    except (TypeError, ValueError):
        return ""


def money(v, cur, lang="en", decimals=2):
    sym = CURRENCY.get(cur, (cur or "") + " ")
    s = f"{v:,.{decimals}f}"
    if lang == "nl":   # 1.234,56
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{sym}{s}"


def num(n, lang="en"):
    s = f"{n:,}"
    return s.replace(",", ".") if lang == "nl" else s


def ml(v):
    return f"{v:g} ml"


# ---------- the published set, cached until the catalog changes ----------

_cache = {"stamp": None, "index": None}


def index(con):
    """Published perfumes and the note index, rebuilt only when the catalog changes (hourly at most)."""
    con.row_factory = sqlite3.Row
    stamp = tuple(con.execute("SELECT MAX(updated), COUNT(*) FROM catalog").fetchone())
    if _cache["stamp"] == stamp:
        return _cache["index"]
    perfumes = []
    for r in con.execute("SELECT * FROM catalog WHERE confirmed >= ? ORDER BY confirmed DESC, shops DESC, name",
                         (PAGE_MIN_CONFIRMED,)):
        p = catalog.row_out(r, full=True)
        perfumes.append(p)
    notes = defaultdict(lambda: {"perfumes": [], "tiers": Counter(), "names": Counter(), "pairs": Counter()})
    for p in perfumes:
        en = {n["en"] for t in p["notes"].values() for n in t if n.get("en") and n["confirmed"]}
        for tier in TIER_KEYS:
            for n in p["notes"][tier]:
                k = n.get("en")
                if not k:
                    continue
                x = notes[k]
                x["tiers"][tier] += 1
                x["names"][n["name"]] += n["shops"]
                if n["confirmed"]:
                    x["perfumes"].append((p, n["shops"]))
                    x["pairs"].update(en - {k})
    notes = {k: v for k, v in notes.items() if v["perfumes"]}
    brands = {}
    for p in perfumes:
        b = brands.setdefault(slug(p["brand"]), {"name": p["brand"], "perfumes": []})
        b["perfumes"].append(p)
    idx = {"perfumes": perfumes, "byId": {p["id"]: p for p in perfumes}, "notes": notes, "brands": brands}
    _cache.update(stamp=stamp, index=idx)
    return idx


# ---------- photos from Open Beauty Facts ----------

def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS page_images (
        gtin TEXT PRIMARY KEY, file TEXT, product TEXT, checked INTEGER NOT NULL)""")


def obf_image_url(gtin, opener=urllib.request.urlopen):
    """The front photo URL Open Beauty Facts has for this barcode, or None."""
    url = (f"https://world.openbeautyfacts.org/api/v2/product/{gtin}.json"
           "?fields=code,image_front_url,product_type")
    req = urllib.request.Request(url, headers={"User-Agent": obf.USER_AGENT})
    try:
        with opener(req, timeout=20) as r:
            d = json.loads(r.read(200_000))
    except urllib.error.HTTPError as err:
        if err.code == 404:   # how Open Beauty Facts says "not found" (or "not a beauty product"): no photo
            return None
        raise
    u = (d.get("product") or {}).get("image_front_url") if d.get("status") == 1 else None
    return u if u and u.startswith("https://images.openbeautyfacts.org/") else None


def fetch_image(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": obf.USER_AGENT})
    with opener(req, timeout=20) as r:
        data = r.read(IMG_MAX + 1)
    if len(data) > IMG_MAX or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        return None
    return data


def refresh_images(con, opener=urllib.request.urlopen, now=None, limit=40):
    """Look up a bottle photo for each published perfume that has none yet (one barcode at a time, at most
    `limit` lookups per run, each barcode again only after IMG_RECHECK). Returns the number of new photos."""
    init(con)
    now = int(now or time.time())
    os.makedirs(IMG_DIR, exist_ok=True)
    done = 0
    for p in index(con)["perfumes"]:
        if limit <= 0:
            break
        if photo(con, p):
            continue
        for g in p.get("gtins", []):
            r = con.execute("SELECT checked FROM page_images WHERE gtin=?", (g,)).fetchone()
            if r and now - r[0] < IMG_RECHECK:
                continue
            limit -= 1
            file = None
            try:
                url = obf_image_url(g, opener)
                data = fetch_image(url, opener) if url else None
                if data:
                    file = f"{g}.jpg" if data[:2] == b"\xff\xd8" else f"{g}.png"
                    with open(os.path.join(IMG_DIR, file), "wb") as f:
                        f.write(data)
                    done += 1
            except Exception as err:   # network trouble: try this barcode again next time
                print("photo lookup failed:", g, type(err).__name__, flush=True)
                continue
            con.execute("INSERT OR REPLACE INTO page_images (gtin, file, product, checked) VALUES (?,?,?,?)",
                        (g, file, g if file else None, now))
            if file or limit <= 0:
                break
    con.commit()
    return done


def photo(con, p):
    """(file, barcode) of the perfume's cached photo, or None."""
    gt = p.get("gtins") or []
    if not gt:
        return None
    try:
        r = con.execute(f"SELECT file, gtin FROM page_images WHERE file IS NOT NULL AND gtin IN ({','.join('?' * len(gt))})"
                        " ORDER BY gtin LIMIT 1", gt).fetchone()
    except sqlite3.OperationalError:   # table not made yet
        return None
    return (r[0], r[1]) if r and os.path.exists(os.path.join(IMG_DIR, r[0])) else None


def image_file(name):
    """(bytes, content type) of a cached photo, for GET /photo/<file>, or None."""
    if not re.fullmatch(r"\d{8,14}\.(jpg|png)", name):
        return None
    path = os.path.join(IMG_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read(), "image/jpeg" if name.endswith(".jpg") else "image/png"


# ---------- page frame ----------

CSS = """
:root{--ink:#2b1426;--ink-soft:#5e4a59;--plum:#7e2f63;--plum-deep:#4a1a3b;--mauve:#c58bb0;--paper:#f4eef3;--white:#fff;
--line:#e3d6e0;--ok:#2f7a4f;--ok-bg:#e6f2ea;--display:"Bricolage Grotesque",system-ui,sans-serif;--text:"Figtree",system-ui,sans-serif}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:400 1.0625rem/1.6 var(--text)}
a{color:var(--plum);text-underline-offset:3px}a:hover{color:var(--plum-deep)}
:focus-visible{outline:3px solid var(--plum);outline-offset:3px;border-radius:4px}
.wrap{width:min(1120px,100% - 32px);margin-inline:auto}
.top{padding:22px 0}.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px}
.brand{display:flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;font:700 1.125rem/1 var(--display)}
.brand img{width:30px;height:30px}
.btn{display:inline-flex;align-items:center;gap:10px;padding:13px 22px;border-radius:999px;background:var(--plum);color:var(--white);font:600 1rem/1 var(--text);text-decoration:none;border:0;cursor:pointer}
.btn:hover{background:var(--plum-deep);color:var(--white)}.btn.small{padding:10px 18px;font-size:.9375rem}
.back{display:inline-flex;gap:6px;margin:8px 0 18px;font:600 .9375rem/1 var(--text);text-decoration:none}.back:hover{text-decoration:underline}
h1{margin:0 0 18px;font:800 clamp(2.3rem,5.6vw,4rem)/1 var(--display);letter-spacing:-.035em}
h2{margin:0 0 6px;font:750 1.6rem/1.1 var(--display);letter-spacing:-.02em}
.sub{margin:0 0 22px;color:var(--ink-soft);font-size:.9375rem}.muted{color:var(--ink-soft);font-size:.875rem}
.card{background:var(--white);border:1px solid var(--line);border-radius:22px;padding:30px}.card+.card{margin-top:28px}
.grid{display:grid;grid-template-columns:1.25fr .75fr;gap:28px;align-items:start;padding-bottom:72px}
.head{padding:0 0 36px;display:grid;grid-template-columns:220px 1fr;gap:36px;align-items:center}.head.nophoto{grid-template-columns:1fr}
.house,.kind{font:600 1.0625rem/1 var(--display);color:var(--plum);margin:0 0 10px}
.photo{margin:0}.photo img{width:100%;aspect-ratio:1;object-fit:contain;background:var(--white);border:1px solid var(--line);border-radius:22px;padding:14px;display:block}
.photo figcaption{margin-top:8px;font-size:.75rem;color:var(--ink-soft)}.photo figcaption a{color:var(--ink-soft)}
.tags{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 22px;padding:0;list-style:none}
.tags li{padding:6px 12px;border-radius:999px;background:var(--white);border:1px solid var(--line);font-size:.9375rem}
.trust{display:flex;flex-wrap:wrap;gap:6px 22px;color:var(--ink-soft);font-size:.9375rem;margin:0}.trust b{color:var(--ink);font-weight:600}
.tier{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:18px 0;border-top:1px solid var(--line)}.tier:last-of-type{border-bottom:1px solid var(--line)}
.tier h3{margin:4px 0 0;font:700 1rem/1.2 var(--display)}.tier h3 small{display:block;font:400 .8125rem/1.3 var(--text);color:var(--ink-soft);margin-top:3px}
.notes{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.note{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;border-radius:999px;font:500 .9688rem/1.2 var(--text);text-decoration:none}
a.note:hover{box-shadow:0 0 0 2px var(--plum)}
.note.ok{background:var(--ok-bg);color:#173f28}.note.ok::before{content:"\\2713";font-weight:700;color:var(--ok)}
.note.one{background:var(--paper);color:var(--ink-soft);border:1px dashed var(--mauve)}.note small{font-size:.75rem;opacity:.75}
.legend{display:flex;flex-wrap:wrap;gap:8px 20px;margin:18px 0 0;font-size:.875rem;color:var(--ink-soft)}
.legend span{display:inline-flex;align-items:center;gap:7px}.legend i{width:14px;height:14px;border-radius:50%;display:inline-block}
.k-ok{background:var(--ok-bg);box-shadow:inset 0 0 0 1.5px var(--ok)}.k-one{background:var(--paper);border:1px dashed var(--mauve)}
table{width:100%;border-collapse:collapse;font-size:.9688rem}
th{text-align:left;font:600 .8125rem/1.2 var(--text);color:var(--ink-soft);text-transform:uppercase;letter-spacing:.06em;padding:0 8px 10px 0}
td{padding:12px 8px 12px 0;border-top:1px solid var(--line);vertical-align:baseline}.num{text-align:right;font-variant-numeric:tabular-nums}
td .low{font:700 1.0625rem/1 var(--display)}
.bars{margin:26px 0 0;display:grid;gap:10px}.bars h3{margin:0 0 4px;font:700 1rem/1.2 var(--display)}
.bar{display:grid;grid-template-columns:104px 1fr 72px;gap:10px;align-items:center;font-size:.9063rem}
.bar span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track{height:12px;background:var(--paper);border-radius:6px;overflow:hidden}.fill{display:block;height:100%;background:var(--mauve);border-radius:6px}
.bar.best .fill{background:var(--plum)}.bar .eur{text-align:right;font-variant-numeric:tabular-nums}.bar.best .eur{font-weight:700}
dl.facts{margin:0}dl.facts div{padding:12px 0;border-top:1px solid var(--line)}dl.facts div:first-child{border-top:0;padding-top:0}
dl.facts dt{font:600 .8125rem/1.2 var(--text);color:var(--ink-soft);text-transform:uppercase;letter-spacing:.06em}dl.facts dd{margin:5px 0 0}
.codes{font:500 .875rem/1.7 ui-monospace,Consolas,monospace}
.help{background:var(--plum);color:var(--white);border:0}.help h2{color:var(--white);font-size:1.35rem}
.help p{color:#f3dcea;margin:0 0 18px;font-size:.9688rem}.help .btn{background:var(--white);color:var(--plum-deep)}
.hero{padding:36px 0 56px}.hero h1{font-size:clamp(2.5rem,5.6vw,4.4rem);line-height:.98;max-width:14ch}
.lead{margin:0 0 28px;font-size:1.1875rem;color:var(--ink-soft);max-width:36em}
.search{display:flex;gap:10px;max-width:560px}
.search input{flex:1;min-width:0;padding:14px 20px;border-radius:999px;border:1.5px solid var(--mauve);background:var(--white);font:400 1rem/1 var(--text);color:var(--ink)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);background:var(--white);border:1px solid var(--line);border-radius:22px;overflow:hidden}
.stats div{padding:26px 26px 24px;border-left:1px solid var(--line)}.stats div:first-child{border-left:0}
.stats b{display:block;font:800 clamp(2rem,4vw,2.8rem)/1 var(--display);letter-spacing:-.03em}
.stats span{display:block;margin-top:8px;color:var(--ink-soft);font-size:.9375rem;line-height:1.35}.stats .hl b{color:var(--ok)}
.asof{margin:12px 0 0;color:var(--ink-soft);font-size:.875rem}
section.part{padding:80px 0 0}section.part h2{font-size:clamp(1.8rem,3.4vw,2.5rem);margin-bottom:14px}
.intro{margin:0 0 32px;color:var(--ink-soft);max-width:38em}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:0;padding:0;list-style:none;counter-reset:s}
.steps li{background:var(--white);border:1px solid var(--line);border-radius:22px;padding:26px;counter-increment:s}
.steps li::before{content:counter(s);display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:var(--paper);color:var(--plum);font:800 1.125rem/1 var(--display);margin-bottom:16px}
.steps h3{margin:0 0 6px;font:700 1.1875rem/1.25 var(--display)}.steps p{margin:0;color:var(--ink-soft);font-size:.9688rem}
.chip{display:inline-flex;gap:6px;padding:3px 10px;border-radius:999px;background:var(--ok-bg);color:#173f28;font-weight:500;font-size:.875rem}
.chip::before{content:"\\2713";color:var(--ok);font-weight:700}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}
.pcard{display:block;background:var(--white);border:1px solid var(--line);border-radius:22px;padding:24px;color:var(--ink);text-decoration:none}
.pcard:hover{color:var(--ink);box-shadow:0 18px 40px -22px rgba(74,26,59,.45)}
.pcard .img{width:84px;height:84px;object-fit:contain;background:var(--paper);border-radius:14px;padding:6px;float:right;margin:0 0 8px 12px}
.pcard .h{font:600 .9375rem/1 var(--display);color:var(--plum);margin:0 0 8px}.pcard .n{font:750 1.375rem/1.15 var(--display);margin:0 0 4px}
.pcard .c{color:var(--ink-soft);font-size:.9375rem;margin:0 0 16px}
.pcard ul{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px;padding:0;list-style:none}
.pcard li{padding:4px 10px;border-radius:999px;background:var(--ok-bg);color:#173f28;font-size:.8438rem}
.pcard .p{display:flex;justify-content:space-between;border-top:1px solid var(--line);padding-top:12px;font-size:.9375rem;color:var(--ink-soft);clear:both}
.pcard .p b{color:var(--ink)}
.soon{border-style:dashed;background:transparent;display:grid;place-content:center;text-align:center;color:var(--ink-soft);min-height:220px}
.soon b{display:block;font:700 1.125rem/1.3 var(--display);color:var(--ink);margin-bottom:6px}
.open{margin:80px 0 0;background:var(--plum);color:var(--white);border-radius:28px;padding:52px;display:grid;grid-template-columns:1fr 1fr;gap:44px}
.open h2{color:var(--white);font-size:clamp(1.8rem,3.4vw,2.5rem)}.open p,.open ul{margin:0 0 16px;color:#f3dcea}.open a{color:var(--white)}
.open code{font:500 .875rem/1.5 ui-monospace,Consolas,monospace;background:rgba(255,255,255,.12);padding:2px 7px;border-radius:6px;color:var(--white);word-break:break-all}
.open .btn{background:var(--white);color:var(--plum-deep)}
.swatch{height:150px;border-radius:22px}
.where{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.where div{border-radius:14px;padding:12px 14px;background:var(--paper);color:var(--ink-soft);font-size:.9375rem}
.where div.on{background:var(--plum);color:var(--white)}.where b{display:block;font:700 1rem/1.2 var(--display)}
.plist{margin:0;padding:0;list-style:none}.plist li{border-top:1px solid var(--line)}.plist li:first-child{border-top:0}
.plist a{display:grid;grid-template-columns:56px 1fr;gap:14px;align-items:center;padding:14px 0;color:var(--ink);text-decoration:none}
.plist a:hover b{text-decoration:underline}.plist img,.plist i{width:56px;height:56px;object-fit:contain;background:var(--paper);border-radius:12px;padding:4px;display:block}
.plist small{display:block;color:var(--ink-soft);font-size:.875rem}
.pairs{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.pairs a{display:inline-block;padding:7px 13px;border-radius:999px;background:var(--paper);color:var(--ink);text-decoration:none;font-size:.9375rem}
.pairs a:hover{box-shadow:0 0 0 2px var(--plum)}
.src{font-size:.875rem;color:var(--ink-soft);border-top:1px solid var(--line);padding-top:14px;margin-top:18px}
.results{margin:0;padding:0;list-style:none}.results li{border-top:1px solid var(--line);padding:14px 0}
footer{padding:36px 0 56px;color:var(--ink-soft);font-size:.875rem;border-top:1px solid var(--line);margin-top:40px}footer p{margin:0 0 8px;max-width:75ch}
@media (max-width:900px){.grid,.open,.steps{grid-template-columns:1fr}.head{grid-template-columns:120px 1fr;gap:18px;align-items:start}
.card{padding:22px 18px;border-radius:18px}.tier{grid-template-columns:1fr;gap:10px}.bar{grid-template-columns:88px 1fr 64px}
.hide-sm{display:none}.stats{grid-template-columns:1fr 1fr}.stats div:nth-child(3){border-left:0}.stats div:nth-child(n+3){border-top:1px solid var(--line)}
.stats div{padding:20px 18px}.open{padding:34px 22px;gap:24px}section.part{padding-top:60px}.search{flex-direction:column}.swatch{height:90px}}
.top nav{display:flex;align-items:center;gap:14px}.lang{font:600 .9375rem/1 var(--text);text-decoration:none;color:var(--ink-soft)}
.lang:hover{color:var(--plum)}
.chart{margin:26px 0 0}.chart h3{margin:0 0 8px;font:700 1rem/1.2 var(--display)}.chart svg{width:100%;height:auto;display:block}
.chart .axis{display:flex;justify-content:space-between;font-size:.8125rem;color:var(--ink-soft);margin-top:4px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.chips a{display:inline-block;padding:8px 14px;border-radius:999px;background:var(--white);border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:.9688rem}
.chips a:hover{box-shadow:0 0 0 2px var(--plum)}.chips small{color:var(--ink-soft);margin-left:4px}
.letter{font:750 1.25rem/1 var(--display);margin:26px 0 10px;color:var(--plum)}
"""


def ld_json(obj):
    """JSON for a <script type="application/ld+json"> block: <, > and & as \\u escapes, so no value can end
    the block or start markup in it."""
    s = json.dumps(obj, ensure_ascii=False)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def frame(lang, title, desc, path, body, noindex=False, image=None, jsonld=None):
    """A whole page. `path` is the page's path without the language prefix (the same in every language)."""
    t = T[lang]
    alt = "".join(f'<link rel="alternate" hreflang="{l}" href="{e(BASE + P(l, path))}">' for l in LANGS)
    head = ('<meta name="robots" content="noindex">' if noindex else
            f'<link rel="canonical" href="{e(BASE + P(lang, path))}">{alt}<link rel="alternate" hreflang="x-default" href="{e(BASE + path)}">')
    ld = f'<script type="application/ld+json">{ld_json(jsonld)}</script>' if jsonld else ""
    other = "nl" if lang == "en" else "en"
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
{head}
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(image or SITE + 'img/og.png')}">
<meta property="og:type" content="website">
<meta property="og:url" content="{e(BASE + P(lang, path))}">
<meta name="twitter:card" content="{'summary' if image else 'summary_large_image'}">
<link rel="icon" href="{SITE}img/icon.png">
<link rel="preconnect" href="https://fonts.bunny.net">
<link rel="stylesheet" href="https://fonts.bunny.net/css?family=bricolage-grotesque:600,700,750,800|figtree:400,500,600&display=swap">
<link rel="stylesheet" href="/assets/pages.css?v={CSS_VERSION}">
{ld}
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{SITE}"><img src="{SITE}img/icon.png" alt="">Fragrance Notes</a>
<nav><a class="lang" href="{e(P(other, path))}" hreflang="{other}" lang="{other}">{T[other]["langName"]}</a>
<a class="btn small" href="{STORE}">{t["getExt"]}</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
<p>{t["footData"]}</p>
<p>{t["footNot"]}</p>
<p><a href="{P(lang, '/database')}">{t["theDb"]}</a> · <a href="{P(lang, '/notes')}">{t["allNotes"]}</a> · <a href="{SITE}privacy.html">{t["privacy"]}</a> · <a href="https://github.com/Tygovanschie/fragrance-notes">{t["source"]}</a></p>
</div></footer>
</body>
</html>"""


CSS_VERSION = hashlib.sha1(CSS.encode()).hexdigest()[:8]


def back(lang):
    return f'<a class="back" href="{P(lang, "/database")}">{T[lang]["back"]}</a>'


def img_tag(con, p, cls="", size=400):
    ph = photo(con, p)
    if not ph:
        return ""
    return f'<img{f" class={chr(34)}{cls}{chr(34)}" if cls else ""} src="/photo/{e(ph[0])}" alt="" width="{size}" height="{size}" loading="lazy">'


def best_prices(stats):
    """[(ml, lowest, shop, high, n_shops, lows)] from app.stats output."""
    out = []
    for s in (stats or {}).get("sizes", []):
        lows = s.get("lows") or {}
        if not lows:
            continue
        shop, low = min(lows.items(), key=lambda kv: kv[1])
        out.append((s["ml"], low, shop, max(lows.values()), len(lows), lows))
    return out


def chart(points, cur, lang):
    """An inline SVG line of the lowest price per day (no script); None with fewer than two days."""
    if len(points) < 2:
        return None
    w, h, pad = 600, 140, 8
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    span = (hi - lo) or 1
    xs = [pad + i * (w - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    ys = [pad + (h - 2 * pad) * (1 - (v - lo) / span) for _, v in points]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{h} {line} {xs[-1]:.1f},{h}"
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#7e2f63"/>' for x, y in zip(xs, ys)) if len(points) <= 31 else ""
    label = T[lang]["chartLabel"].format(low=money(lo, cur, lang), high=money(hi, cur, lang))
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{e(label)}" preserveAspectRatio="none">'
            f'<polygon points="{area}" fill="#c58bb0" fill-opacity=".18"/>'
            f'<polyline points="{line}" fill="none" stroke="#7e2f63" stroke-width="2.5" stroke-linejoin="round"/>{dots}</svg>'
            f'<div class="axis"><span>{e(day(points[0][0], lang))}</span><span>{e(label)}</span><span>{e(day(points[-1][0], lang))}</span></div>')


# ---------- /perfume/<id>-<slug> ----------

def conc_name(p):
    return CONC.get(p.get("conc") or "", "")


def perfume_page(con, pid, prices=None, lang="en"):
    """(path, html) for a published perfume, path without language prefix; None if it has no page."""
    t = T[lang]
    idx = index(con)
    p = idx["byId"].get(pid)
    if not p:
        return None
    path = perfume_path(p)
    linkable = idx["notes"]
    conf = sum(n["confirmed"] for tr in p["notes"].values() for n in tr)
    tags = [conc_name(p), t["gender"].get(p.get("gender") or "", "")]
    sizes = p.get("sizes") or []
    if sizes:
        tags.append(ml(sizes[0]) if len(sizes) == 1 else f"{sizes[0]:g} – {sizes[-1]:g} ml")
    ph = photo(con, p)
    photo_html = (f'<figure class="photo"><img src="/photo/{e(ph[0])}" alt="{e(t["bottleOf"].format(name=p["name"], brand=p["brand"]))}" width="400" height="400">'
                  f'<figcaption>{t["photo"]}: <a href="https://world.openbeautyfacts.org/product/{e(ph[1])}">Open Beauty Facts</a>, CC BY-SA</figcaption></figure>') if ph else ""
    full = t["by"].format(name=p["name"], brand=p["brand"])

    tiers = []
    for tier, label, hint in t["tiers"]:
        chips = []
        for n in p["notes"][tier]:
            name = note_name(n["en"], lang) if n.get("en") else n["name"]
            cls = "note ok" if n["confirmed"] else "note one"
            extra = "" if n["confirmed"] else f' <small>{t["shops"](n["shops"])}</small>'
            if n.get("en") in linkable:
                chips.append(f'<li><a class="{cls}" href="{P(lang, note_path(n["en"]))}">{e(name)}{extra}</a></li>')
            else:
                chips.append(f'<li><span class="{cls}">{e(name)}{extra}</span></li>')
        if chips:
            tiers.append(f'<div class="tier"><h3>{label}<small>{hint}</small></h3><ul class="notes">{"".join(chips)}</ul></div>')

    price_html, offers = "", None
    st = prices(p["fragrantica"][0]) if prices and p.get("fragrantica") else None
    rows = best_prices(st)
    if rows:
        cur = st.get("currency")
        trs = "".join(
            f'<tr><td>{ml(m)}</td><td class="num"><span class="low">{e(money(low, cur, lang))}</span></td><td>{e(shop)}</td>'
            f'<td class="num hide-sm">{e(money(low / m, cur, lang))}</td>'
            f'<td class="num hide-sm muted">{t["oneShop"] if n == 1 else e(money(low, cur, lang, 0) + " – " + money(high, cur, lang, 0))}</td></tr>'
            for m, low, shop, high, n, _ in rows)
        m, _, _, _, _, lows = max(rows, key=lambda r: (r[4], r[0] == 100, r[0]))
        top = max(lows.values())
        bars = "".join(
            f'<div class="bar{" best" if i == 0 else ""}"><span>{e(s)}</span><span class="track"><span class="fill" style="width:{v / top * 100:.0f}%"></span></span>'
            f'<span class="eur">{e(money(v, cur, lang))}</span></div>'
            for i, (s, v) in enumerate(sorted(lows.items(), key=lambda kv: kv[1]))) if len(lows) > 1 else ""
        hist = chart([(d, v) for d, v in (st.get("history") or {}).get(m, [])], cur, lang)
        shops_n = len({s for r in rows for s in r[5]})
        price_html = f"""<section class="card" aria-labelledby="price-h"><h2 id="price-h">{t["prices"]}</h2>
<p class="sub">{t["pricesSub"].format(days=st.get("days", 30), shops=t["shops"](shops_n))}</p>
<table><thead><tr><th>{t["size"]}</th><th class="num">{t["lowest"]}</th><th>{t["at"]}</th><th class="num hide-sm">{t["perMl"]}</th><th class="num hide-sm">{t["range"]}</th></tr></thead>
<tbody>{trs}</tbody></table>
{f'<div class="bars"><h3>{t["atEachShop"].format(size=ml(m))}</h3>{bars}</div>' if bars else ""}
{f'<div class="chart"><h3>{t["chartTitle"].format(size=ml(m))}</h3>{hist}</div>' if hist else ""}</section>"""
        offers = {"@type": "AggregateOffer", "priceCurrency": cur, "lowPrice": f"{min(r[1] for r in rows):.2f}",
                  "highPrice": f"{max(r[3] for r in rows):.2f}", "offerCount": shops_n}

    fams = [note_name(f["key"], lang) if f["key"] in catalog.NOTE_EN else f["name"] for f in p.get("families", [])
            if f["confirmed"] or f["key"] in catalog.NOTE_EN]
    srcs = ["Open Beauty Facts" if s == obf.SOURCE else s for s in p.get("shopList", [])]
    facts = []
    if fams:
        facts.append((t["family"], e(" · ".join(fams))))
    if sizes:
        facts.append((t["sizes"], e(", ".join(f"{s:g}" for s in sizes) + " ml")))
    facts.append((t["describedBy"], e(", ".join(srcs))))
    if p.get("gtins"):
        facts.append((t["barcodes"], f'<span class="codes">{"<br>".join(e(g) for g in p["gtins"][:8])}</span>'))
    q = urllib.parse.quote(f"{p['brand']} {p['name']}")
    facts.append((t["more"], t["moreFrag"].format(link=f'<a href="https://www.fragrantica.com/search/?query={q}" rel="nofollow">Fragrantica ↗</a>')))
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    body = f"""{back(lang)}
<section class="head{'' if ph else ' nophoto'}">{photo_html}<div>
<p class="house"><a href="{P(lang, brand_path(p['brand']))}" style="color:inherit;text-decoration:none">{e(p["brand"])}</a></p>
<h1>{e(p["name"])}</h1>
<ul class="tags">{"".join(f"<li>{e(x)}</li>" for x in tags if x)}</ul>
<p class="trust"><span>{t["trustShops"](p["shops"])}</span><span>{t["trustNotes"](conf)}</span><span>{t["lastSeen"]} <b>{e(day(p.get("lastSeen"), lang))}</b></span></p>
</div></section>
<div class="grid"><div>
<section class="card" aria-labelledby="notes-h"><h2 id="notes-h">{t["notes"]}</h2>
<p class="sub">{t["notesSub"]}</p>
{"".join(tiers)}
<div class="legend"><span><i class="k-ok"></i>{t["legendOk"]}</span><span><i class="k-one"></i>{t["legendOne"]}</span></div>
</section>
{price_html}
</div><aside>
<section class="card" aria-label="{t["details"]}"><dl class="facts">{facts_html}</dl></section>
<section class="card help"><h2>{t["helpT"]}</h2>
<p>{t["helpD"]}</p>
<a class="btn" href="{STORE}">{t["getFN"]}</a></section>
</aside></div>"""
    confirmed_names = [note_name(n["en"], lang) if n.get("en") else n["name"] for tr in p["notes"].values() for n in tr if n["confirmed"]]
    desc = t["perfumeDesc"].format(full=full, conc=conc_name(p) or t["perfume"], notes=", ".join(confirmed_names[:6]))
    image = BASE + f"/photo/{ph[0]}" if ph else None
    ld = {"@context": "https://schema.org", "@type": "Product", "name": p["name"], "category": "Perfume",
          "brand": {"@type": "Brand", "name": p["brand"]}, "url": BASE + P(lang, path), "description": desc}
    if image:
        ld["image"] = image
    if p.get("gtins"):
        ld["gtin13"] = p["gtins"][0]
    if offers:
        ld["offers"] = offers
    return path, frame(lang, t["perfumeTitle"].format(full=full), desc, path, body, image=image, jsonld=ld)


# ---------- /note/<slug> and /notes ----------

def swatch(key):
    """A soft colour field per note (no photo): three warm circles on a gradient, from a hash of the name."""
    h = hashlib.sha1(key.encode()).digest()
    hue = h[0] * 360 // 256
    c = lambda i, s, l: f"hsl({(hue + h[i] % 40 - 20) % 360} {s}% {l}%)"
    return (f"background:radial-gradient(circle at 25% 35%,{c(1, 45, 78)} 0 18%,transparent 19%),"
            f"radial-gradient(circle at 62% 60%,{c(2, 40, 55)} 0 22%,transparent 23%),"
            f"radial-gradient(circle at 85% 25%,{c(3, 45, 35)} 0 12%,transparent 13%),"
            f"linear-gradient(120deg,{c(4, 50, 90)},{c(5, 35, 62)} 60%,{c(6, 40, 40)})")


def note_page(con, slug_, lang="en"):
    t = T[lang]
    key = " ".join(slug_.split("-"))
    idx = index(con)
    x = idx["notes"].get(key)
    if not x:
        return None
    path = note_path(key)
    name = note_name(key, lang)
    aka = [n for n, _ in x["names"].most_common() if catalog.plain(n) not in (key, catalog.plain(name))][:6]
    text = TEXTS.get(key)
    about = ""
    if text:
        smell = text.get(f"smell_{lang}") or text["smell"]
        origin = text.get(f"origin_{lang}") or text["origin"]
        english = lang != "en" and not text.get(f"smell_{lang}")
        src = text.get("source", "")
        about = f"""<section class="card"{' lang="en"' if english else ""}><h2>{t["smellsLike"]}</h2><p>{e(smell)}</p>
<h2 style="margin-top:26px">{t["comesFrom"]}</h2><p>{e(origin)}</p>
<p class="src">{t["aiNote"]}
{f'{t["sourceWord"]}: <a href="{e(src)}" rel="nofollow">{e(text.get("sourceName", "source"))}</a> ({e(text.get("license", ""))}).' if src else ""}</p></section>"""
    items = []
    for p, shops in sorted(x["perfumes"], key=lambda q: (-q[1], q[0]["name"])):
        im = img_tag(con, p, size=56) or "<i></i>"
        items.append(f'<li><a href="{P(lang, perfume_path(p))}">{im}<span><b>{e(p["name"])}</b>'
                     f'<small>{e(p["brand"])} · {e(conc_name(p) or t["perfume"])} · {t["confirmedBy"].format(n=shops)}</small></span></a></li>')
    total = sum(x["tiers"].values()) or 1
    where = "".join(f'<div class="{"on" if x["tiers"][tr] * 2 >= total and x["tiers"][tr] else ""}"><b>{label}</b>'
                    f'{t["perfumes"](x["tiers"][tr])}</div>' for tr, label, _ in t["tiers"])
    pairs = [k for k, _ in x["pairs"].most_common(8) if k in idx["notes"]]
    pairs_html = (f'<section class="card"><h2>{t["pairedWith"]}</h2><ul class="pairs">'
                  f'{"".join(f"<li><a href={chr(34)}{P(lang, note_path(k))}{chr(34)}>{e(note_name(k, lang))}</a></li>" for k in pairs)}</ul></section>') if pairs else ""
    body = f"""{back(lang)}
<section class="head" style="grid-template-columns:1fr 340px;align-items:end"><div>
<p class="kind"><a href="{P(lang, '/notes')}" style="color:inherit;text-decoration:none">{t["perfumeNote"]}</a></p><h1>{e(name)}</h1>
{f'<p class="muted" style="font-size:1rem">{t["alsoWrite"]}: {", ".join(f"<b>{e(a)}</b>" for a in aka)}</p>' if aka else ""}
</div><div class="swatch" style="{swatch(key)}" aria-hidden="true"></div></section>
<div class="grid"><div>
{about}
<section class="card"><h2>{t["perfumesWith"].format(note=e(name.lower()))}</h2><ul class="plist">{"".join(items)}</ul></section>
</div><aside>
<section class="card"><h2>{t["whereSits"]}</h2><div class="where">{where}</div></section>
{pairs_html}
</aside></div>"""
    if text:
        desc = (text.get(f"smell_{lang}") or text["smell"])[:155]
    else:
        desc = t["noteDesc"].format(note=name.lower())
    return path, frame(lang, t["noteTitle"].format(name=name), desc, path, body)


def notes_page(con, lang="en"):
    t = T[lang]
    idx = index(con)
    keys = sorted(idx["notes"], key=lambda k: catalog.plain(note_name(k, lang)))
    groups = defaultdict(list)
    for k in keys:
        groups[catalog.plain(note_name(k, lang))[:1].upper() or "#"].append(k)
    blocks = "".join(
        f'<p class="letter">{e(letter)}</p><ul class="chips">'
        + "".join(f'<li><a href="{P(lang, note_path(k))}">{e(note_name(k, lang))}<small>{len(idx["notes"][k]["perfumes"])}</small></a></li>' for k in ks)
        + "</ul>" for letter, ks in groups.items())
    body = f"""{back(lang)}<h1>{t["allNotes"]}</h1><p class="lead">{t["notesLead"]}</p>
<section class="card">{blocks or f"<p>{t['nothingYet']}</p>"}</section>"""
    return frame(lang, t["notesTitle"], t["notesLead"], "/notes", body)


# ---------- /brand/<slug> ----------

def brand_path(brand):
    return "/brand/" + slug(brand)


def brand_page(con, slug_, lang="en"):
    t = T[lang]
    idx = index(con)
    b = idx["brands"].get(slug_)
    if not b:
        return None
    cards = "".join(card(con, p, None, lang) for p in b["perfumes"])
    con.row_factory = sqlite3.Row
    more = 0
    for r in con.execute("SELECT brand FROM catalog WHERE confirmed < ?", (PAGE_MIN_CONFIRMED,)):
        more += slug(r["brand"]) == slug_
    more_html = f'<p class="asof">{t["brandMore"].format(n=more, brand=e(b["name"]))}</p>' if more else ""
    body = f"""{back(lang)}<p class="kind">{t["brandKind"]}</p><h1>{e(b["name"])}</h1>
<p class="lead">{t["brandLead"].format(brand=e(b["name"]), n=t["perfumes"](len(b["perfumes"])))}</p>
<div class="cards">{cards}</div>{more_html}"""
    path = brand_path(b["name"])
    ld = {"@context": "https://schema.org", "@type": "Brand", "name": b["name"], "url": BASE + P(lang, path)}
    return path, frame(lang, t["brandTitle"].format(brand=b["name"]), t["brandLead"].format(brand=b["name"], n=t["perfumes"](len(b["perfumes"]))),
                       path, body, jsonld=ld)


# ---------- /database and /database/search ----------

def card(con, p, prices=None, lang="en"):
    t = T[lang]
    conf = [note_name(n["en"], lang) if n.get("en") else n["name"] for tr in p["notes"].values() for n in tr if n["confirmed"]]
    tail = ""
    st = prices(p["fragrantica"][0]) if prices and p.get("fragrantica") else None
    rows = best_prices(st)
    if rows:
        m, low, *_ = min(rows, key=lambda r: (abs(r[0] - 100), r[0]))
        tail = f'<p class="p"><span>{t["from"].format(size=ml(m))}</span><b>{e(money(low, st.get("currency"), lang))}</b></p>'
    bits = [conc_name(p), (t["gender"].get(p.get("gender") or "", "") or "").lower(), t["sources"](p["shops"])]
    return (f'<a class="pcard" href="{P(lang, perfume_path(p))}">{img_tag(con, p, "img", 84)}<p class="h">{e(p["brand"])}</p>'
            f'<p class="n">{e(p["name"])}</p><p class="c">{e(" · ".join(b for b in bits if b))}</p>'
            f'<ul>{"".join(f"<li>{e(c)}</li>" for c in conf[:8])}</ul>{tail}</a>')


def database_page(con, prices=None, lang="en"):
    t = T[lang]
    idx = index(con)
    s = catalog.stats(con)
    shops = con.execute("SELECT COUNT(DISTINCT shop) FROM reports").fetchone()[0] if _has(con, "reports") else 0
    cards = "".join(card(con, p, prices, lang) for p in idx["perfumes"][:24])
    brands = "".join(f'<li><a href="{P(lang, brand_path(b["name"]))}">{e(b["name"])}<small>{len(b["perfumes"])}</small></a></li>'
                     for b in sorted(idx["brands"].values(), key=lambda b: catalog.plain(b["name"])))
    notes = "".join(f'<li><a href="{P(lang, note_path(k))}">{e(note_name(k, lang))}<small>{len(v["perfumes"])}</small></a></li>'
                    for k, v in sorted(idx["notes"].items(), key=lambda kv: (-len(kv[1]["perfumes"]), kv[0]))[:16])
    body = f"""<section class="hero">
<h1>{t["dbH1"]}</h1>
<p class="lead">{t["dbLead"]}</p>
<form class="search" role="search" action="{P(lang, '/database/search')}"><input type="search" name="q" placeholder="{t["searchPh"]}" aria-label="{t["searchPh"]}" required maxlength="100"><button class="btn" type="submit">{t["search"]}</button></form>
</section>
<div class="stats">
<div><b>{num(s["perfumes"], lang)}</b><span>{t["statPerfumes"]}</span></div>
<div><b>{num(s["brands"], lang)}</b><span>{t["statBrands"]}</span></div>
<div class="hl"><b>{num(s["withConfirmedNotes"], lang)}</b><span>{t["statConfirmed"]}</span></div>
<div><b>{num(shops, lang)}</b><span>{t["statShops"]}</span></div>
</div>
<p class="asof">{t["counted"].format(day=e(day(date.today().isoformat(), lang)))}</p>
<section class="part"><h2>{t["howH"]}</h2>
<p class="intro">{t["howIntro"]}</p>
<ol class="steps">
<li><h3>{t["step1T"]}</h3><p>{t["step1D"]}</p></li>
<li><h3>{t["step2T"]}</h3><p>{t["step2D"]}</p></li>
<li><h3>{t["step3T"]}</h3><p>{t["step3D"]}</p></li>
</ol></section>
<section class="part"><h2>{t["withConfirmed"]}</h2>
<p class="intro">{t["pageRule"].format(n=PAGE_MIN_CONFIRMED)}</p>
<div class="cards">{cards}<div class="pcard soon"><div><b>{t["nextT"]}</b>{t["nextD"]}</div></div></div>
</section>
{f'<section class="part"><h2>{t["brandsH"]}</h2><ul class="chips">{brands}</ul></section>' if brands else ""}
{f'<section class="part"><h2>{t["notesH"]}</h2><ul class="chips">{notes}</ul><p class="asof"><a href="{P(lang, "/notes")}">{t["allNotes"]} →</a></p></section>' if notes else ""}
<section class="open"><div><h2>{t["openH"]}</h2>
<p>{t["openD1"]}</p>
<p>{t["openD2"]}</p></div>
<div><ul><li>{t["apiSearch"]}: <code>api.fragrancenotes.app/catalog/search?q=</code></li><li>{t["apiOne"]}: <code>api.fragrancenotes.app/catalog/perfume/{{id}}</code></li>
<li>{t["apiStats"]}: <code>api.fragrancenotes.app/catalog/stats</code></li></ul>
<a class="btn" href="{STORE}">{t["growBtn"]}</a></div></section>"""
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": t["dsName"], "description": t["dbLead"],
          "url": BASE + P(lang, "/database"), "license": "https://opendatacommons.org/licenses/odbl/1-0/",
          "creator": {"@type": "Organization", "name": "Fragrance Notes", "url": SITE},
          "isAccessibleForFree": True,
          "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                            "contentUrl": "https://api.fragrancenotes.app/catalog/stats"}]}
    return frame(lang, t["dbTitle"], t["dbDesc"], "/database", body, jsonld=ld)


def search_page(con, q, lang="en"):
    t = T[lang]
    q = (q or "")[:100]
    idx = index(con)
    words = catalog.plain(q).split()
    hits = [p for p in idx["perfumes"] if words and all(f" {w}" in " " + catalog.plain(p["brand"] + " " + p["name"]) for w in words)]
    notes = [k for k in idx["notes"] if words and all(w in k or w in catalog.plain(note_name(k, lang)) for w in words)]
    others = sum(1 for r in catalog.search(con, q) if r["id"] not in idx["byId"]) if words else 0
    lis = "".join(f'<li><a href="{P(lang, perfume_path(p))}"><b>{e(p["name"])}</b></a> <span class="muted">{e(p["brand"])} · {e(conc_name(p) or t["perfume"])}</span></li>' for p in hits)
    lis += "".join(f'<li><a href="{P(lang, note_path(k))}"><b>{e(note_name(k, lang))}</b></a> <span class="muted">{t["perfumeNote"].lower()}</span></li>' for k in notes)
    none = "" if lis else f"<p>{t['noMatch']}</p>"
    more = f'<p class="muted">{t["moreMatch"](others)}</p>' if others else ""
    body = f"""{back(lang)}<h1 style="font-size:clamp(2rem,4vw,3rem)">{t["search"]}</h1>
<form class="search" role="search" action="{P(lang, '/database/search')}" style="margin-bottom:28px"><input type="search" name="q" value="{e(q)}" aria-label="{t["searchPh"]}" required maxlength="100"><button class="btn" type="submit">{t["search"]}</button></form>
<section class="card"><ul class="results">{lis}</ul>{none}{more}</section>"""
    return frame(lang, f'{t["search"]}: {q} | Fragrance Notes', t["dbDesc"], "/database/search", body, noindex=True)


def not_found(lang="en"):
    t = T[lang]
    body = f"""{back(lang)}<h1>{t["nfH"]}</h1><p class="lead">{t["nfD"].format(n=PAGE_MIN_CONFIRMED)}</p>"""
    return frame(lang, "Not found | Fragrance Notes", t["nfH"], "/database", body, noindex=True)


def sitemap(con):
    idx = index(con)
    paths = (["/database", "/notes"] + [perfume_path(p) for p in idx["perfumes"]]
             + [note_path(k) for k in sorted(idx["notes"])] + [brand_path(b["name"]) for b in idx["brands"].values()])
    urls = "".join(
        f"<url><loc>{e(BASE + P(l, u))}</loc>"
        + "".join(f'<xhtml:link rel="alternate" hreflang="{a}" href="{e(BASE + P(a, u))}"/>' for a in LANGS)
        + "</url>\n" for u in paths for l in LANGS)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + urls + "</urlset>\n")


def route(con, path, query, prices):
    """(status, html or None, redirect target or None) for a page path, in either language."""
    lang = "en"
    if path == "/nl" or path.startswith("/nl/"):
        lang, path = "nl", path[3:] or "/"
    if path in ("/", ""):
        return 301, None, P(lang, "/database")
    if path in ("/database", "/database/"):
        return 200, database_page(con, prices, lang), None
    if path == "/database/search":
        q = (urllib.parse.parse_qs(query).get("q") or [""])[0]
        return 200, search_page(con, q, lang), None
    if path in ("/notes", "/notes/"):
        return 200, notes_page(con, lang), None
    m = re.fullmatch(r"/perfume/([0-9a-f]{12})(?:-[a-z0-9-]*)?", path)
    if m and (r := perfume_page(con, m.group(1), prices, lang)):
        return (301, None, P(lang, r[0])) if path != r[0] else (200, r[1], None)
    m = re.fullmatch(r"/note/([a-z0-9-]{1,60})", path)
    if m and (r := note_page(con, m.group(1), lang)):
        return 200, r[1], None
    m = re.fullmatch(r"/brand/([a-z0-9-]{1,80})", path)
    if m and (r := brand_page(con, m.group(1), lang)):
        return 200, r[1], None
    return 404, not_found(lang), None


def _has(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
