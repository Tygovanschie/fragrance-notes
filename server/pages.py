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
import accords
import maintenance
import regions
import notephotos
import votes

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
LANGS = ("en", "nl", "de", "fr", "es", "it", "pt", "pl")   # English without a prefix, the others under /<code>


def _n(one, many):
    return lambda n: (one if n == 1 else many).format(n=n)


T = {
    "en": {
        "langName": "English", "getExt": "Get the extension", "back": "← All perfumes",
        "notePhotos": "Note photos: Wikimedia Commons",
        "accordsH": "Main accords", "accordsSub": "Worked out from the notes and fragrance families the shops give, not voted.",
        "theDb": "All perfumes", "allNotes": "All notes", "privacy": "Privacy", "source": "Source",
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
        "notes": "Notes", "notesSub": "The notes at least two different shops agree on.", "singleH": "Also named by one shop ({n})", "singleSub": "Not confirmed yet. Shops sometimes use their own, different note list, so these can differ from the official one.",
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
        "dbH1": "Find your next perfume",
        "dbLead": "Notes, accords, prices and what people who wear them think. From the shops that sell them and from the brands themselves.",
        "searchPh": "Search a perfume, brand or note", "search": "Search",
        "statPerfumes": "perfumes", "statBrands": "brands", "statConfirmed": "with confirmed notes", "statShops": "shops with prices",
        "counted": "Counted {day}. It grows with every shop page people visit.",
        "howH": "How a note gets confirmed",
        "howIntro": "Nothing here is copied from other sites. It's only what perfume shops show on their own product pages, collected by people who turned sharing on.",
        "step1T": "You visit a perfume page", "step1D": "On any of 300+ supported shops, as you normally would. Sharing is off until you turn on “Help other perfume lovers”.",
        "step2T": "The shop's facts are shared", "step2D": "The notes, family, sizes, barcode and price that the shop itself shows. Never who you are or what you buy.",
        "step3T": "Shops agree, it's confirmed", "step3D": 'Once two different shops list the same note, it gets <span class="chip">confirmed</span> and shows up in the extension and on this site.',
        "withConfirmed": "All perfumes", "pageRule": "A perfume gets its own page once at least {n} of its notes are confirmed.",
        "nextT": "Yours could be next", "nextD": "Visit a perfume at two shops with sharing on.",
        "brandsH": "Brands", "notesH": "Most confirmed notes",
        "openH": "Open data",
        "openD1": 'The database is published under the <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Use it in your own app, research or site, as long as you name the source and share improvements under the same licence.',
        "openD2": 'It also includes perfume data from <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>.',
        "apiSearch": "Search", "apiOne": "One perfume", "apiStats": "Totals", "growBtn": "Help it grow: get the extension",
        "dsName": "Fragrance Notes open perfume database",
        "dbTitle": "Perfumes: notes, accords and prices | Fragrance Notes",
        "dbDesc": "Find perfumes by name, brand or note: notes, accords, prices across shops and what people who wear them think.",
        "noMatch": "No perfume page matches that yet.",
        "moreMatch": _n("{n} more perfume in the database matches, but doesn't have enough confirmed notes for a page yet.",
                        "{n} more perfumes in the database match, but don't have enough confirmed notes for a page yet."),
        "nfH": "Not here (yet)",
        "voteH": "What do people think?", "yourVoteH": "Your vote",
        "voteIntro": "Own it or have you worn it? Share how it performs for you. No account needed.",
        "owns": "I own this perfume or have worn it", "send": "Send my vote",
        "voteNote": 'One vote per browser; vote again to change it. We keep a random code in a cookie and nothing about you (<a href="https://fragrancenotes.app/privacy">privacy</a>).',
        "q": {"rating": "Overall", "longevity": "How long does it last?", "sillage": "Sillage: how far can others smell it?",
              "value": "Value for money", "gender": "Who is it for?"},
        "r": {"longevity": "Longevity", "sillage": "Sillage", "value": "Value for money", "gender": "Gender"},
        "star": _n("{n} star", "{n} stars"),
        "voteMsg": {"thanks": "Thanks! Your vote is in. The results on this page update within about 10 minutes.",
                    "own": "Tick “I own this perfume or have worn it” to vote.", "empty": "Choose at least one answer.",
                    "busy": "Too many votes at once. Please try again later."},
        "votesSoFar": _n("{n} person voted so far. Results appear from 3 votes.", "{n} people voted so far. Results appear from 3 votes."),
        "votesNone": "No votes yet. Be the first.", "votedBy": _n("from {n} vote", "from {n} votes"),
        "voteSaved": "Your vote is saved.", "voteChange": "These are your answers. Change any of them and update your vote.",
        "update": "Update my vote", "rateTitle": "Rate {full} | Fragrance Notes",
        "rateLead": "Not enough shops confirm the notes of this perfume yet for a full page, but you can already rate it.",
        "nfD": "This perfume or note has no page yet. A perfume gets one once at least {n} of its notes are confirmed by two different shops.",
    },
    "nl": {
        "langName": "Nederlands", "getExt": "Installeer de extensie", "back": "← Alle parfums",
        "notePhotos": "Foto’s van noten: Wikimedia Commons",
        "accordsH": "Hoofdaccoorden", "accordsSub": "Afgeleid uit de geurnoten en geurfamilies die de winkels noemen, niet gestemd.",
        "theDb": "Alle parfums", "allNotes": "Alle geurnoten", "privacy": "Privacy", "source": "Broncode",
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
        "notes": "Geurnoten", "notesSub": "De geurnoten waar minstens twee verschillende winkels het over eens zijn.", "singleH": "Ook genoemd door één winkel ({n})", "singleSub": "Nog niet bevestigd. Winkels gebruiken soms hun eigen, afwijkende notenlijst, dus deze kunnen verschillen van de officiële.",
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
        "dbH1": "Vind je volgende parfum",
        "dbLead": "Geurnoten, accoorden, prijzen en wat dragers ervan vinden. Van de winkels die ze verkopen en van de merken zelf.",
        "searchPh": "Zoek een parfum, merk of geurnoot", "search": "Zoeken",
        "statPerfumes": "parfums", "statBrands": "merken", "statConfirmed": "met bevestigde noten", "statShops": "winkels met prijzen",
        "counted": "Geteld op {day}. Hij groeit met elke winkelpagina die mensen bezoeken.",
        "howH": "Hoe een geurnoot bevestigd wordt",
        "howIntro": "Niets hier is gekopieerd van andere sites. Het is alleen wat parfumwinkels op hun eigen productpagina's laten zien, verzameld door mensen die delen aan hebben gezet.",
        "step1T": "Je bezoekt een parfumpagina", "step1D": "Bij een van de 300+ ondersteunde winkels, zoals je normaal doet. Delen staat uit tot je “Help andere parfumliefhebbers” aanzet.",
        "step2T": "De gegevens van de winkel worden gedeeld", "step2D": "De geurnoten, familie, inhoud, barcode en prijs die de winkel zelf laat zien. Nooit wie je bent of wat je koopt.",
        "step3T": "Winkels zijn het eens: bevestigd", "step3D": 'Zodra twee verschillende winkels dezelfde noot noemen, wordt hij <span class="chip">bevestigd</span> en verschijnt hij in de extensie en op deze site.',
        "withConfirmed": "Alle parfums", "pageRule": "Een parfum krijgt een eigen pagina zodra minstens {n} van zijn noten bevestigd zijn.",
        "nextT": "Jouw parfum kan de volgende zijn", "nextD": "Bekijk een parfum bij twee winkels met delen aan.",
        "brandsH": "Merken", "notesH": "Meest bevestigde noten",
        "openH": "Open data",
        "openD1": 'De database valt onder de <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Gebruik hem in je eigen app, onderzoek of site, zolang je de bron noemt en verbeteringen onder dezelfde licentie deelt.',
        "openD2": 'Hij bevat ook parfumgegevens van <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>.',
        "apiSearch": "Zoeken", "apiOne": "Eén parfum", "apiStats": "Totalen", "growBtn": "Help hem groeien: installeer de extensie",
        "dsName": "Open parfumdatabase van Fragrance Notes",
        "dbTitle": "Parfums: geurnoten, accoorden en prijzen | Fragrance Notes",
        "dbDesc": "Zoek parfums op naam, merk of geurnoot: geurnoten, accoorden, prijzen bij verschillende winkels en wat dragers ervan vinden.",
        "noMatch": "Nog geen parfumpagina die daarop past.",
        "moreMatch": _n("Er past nog {n} parfum in de database, maar die heeft te weinig bevestigde noten voor een pagina.",
                        "Er passen nog {n} parfums in de database, maar die hebben te weinig bevestigde noten voor een pagina."),
        "nfH": "(Nog) niet hier",
        "voteH": "Wat vinden mensen ervan?", "yourVoteH": "Jouw stem",
        "voteIntro": "Heb je hem, of heb je hem gedragen? Deel hoe hij bij jou presteert. Geen account nodig.",
        "owns": "Ik heb dit parfum of heb het gedragen", "send": "Stem versturen",
        "voteNote": 'Eén stem per browser; stem opnieuw om hem te wijzigen. We bewaren een willekeurige code in een cookie en verder niets over jou (<a href="https://fragrancenotes.app/privacy">privacy</a>).',
        "r": {"longevity": "Hoe lang hij blijft", "sillage": "Sillage", "value": "Prijs-kwaliteit", "gender": "Voor wie"},
        "q": {"rating": "Totaal", "longevity": "Hoe lang blijft hij?", "sillage": "Sillage: hoe ver ruiken anderen hem?",
              "value": "Prijs-kwaliteit", "gender": "Voor wie?"},
        "star": _n("{n} ster", "{n} sterren"),
        "voteMsg": {"thanks": "Bedankt! Je stem is binnen. De uitslag op deze pagina wordt binnen zo'n 10 minuten bijgewerkt.",
                    "own": "Vink “Ik heb dit parfum of heb het gedragen” aan om te stemmen.", "empty": "Kies minstens één antwoord.",
                    "busy": "Te veel stemmen tegelijk. Probeer het later nog eens."},
        "votesSoFar": _n("{n} persoon heeft gestemd. De uitslag verschijnt vanaf 3 stemmen.", "{n} mensen hebben gestemd. De uitslag verschijnt vanaf 3 stemmen."),
        "votesNone": "Nog geen stemmen. Wees de eerste.", "votedBy": _n("uit {n} stem", "uit {n} stemmen"),
        "voteSaved": "Je stem is opgeslagen.", "voteChange": "Dit zijn je antwoorden. Pas er een aan en werk je stem bij.",
        "update": "Stem bijwerken", "rateTitle": "{full} beoordelen | Fragrance Notes",
        "rateLead": "Nog niet genoeg winkels bevestigen de geurnoten van dit parfum voor een volledige pagina, maar je kunt het al wel beoordelen.",
        "nfD": "Dit parfum of deze noot heeft nog geen pagina. Een parfum krijgt er een zodra minstens {n} van zijn noten door twee verschillende winkels bevestigd zijn.",
    },
}

# German, French, Spanish, Italian, Portuguese and Polish (pages_i18n.py); missing texts fall back to English.
from pages_i18n import EXTRA, SCALES as SCALE_TEXT  # noqa: E402
for _l, _d in EXTRA.items():
    T[_l] = {**T["en"], **_d}
# The answers of the voting questions, for every language (one list in pages_i18n.SCALES).
for _l, _s in SCALE_TEXT.items():
    T[_l]["scale"] = _s
T["en"]["r"] = {"longevity": "Longevity", "sillage": "Sillage", "value": "Value for Money", "gender": "Gender"}
T["nl"]["r"] = {**T["nl"]["r"], "longevity": "Houdbaarheid"}

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
_auto = {"mtime": None, "texts": {}}


# The credit under a note description the nightly job put online by itself (maintenance.py): checked against its
# source by the computer, not by a person.
AI_AUTO = {"en": "Written by our own AI model from the source text and checked against it automatically.",
           "nl": "Geschreven door ons eigen AI-model op basis van de brontekst en daar automatisch mee vergeleken.",
           "de": "Von unserem eigenen KI-Modell aus dem Quelltext geschrieben und automatisch damit abgeglichen.",
           "fr": "Écrit par notre propre modèle d’IA à partir du texte source et vérifié automatiquement par rapport à celui-ci.",
           "es": "Escrito por nuestro propio modelo de IA a partir del texto fuente y comprobado automáticamente con él.",
           "it": "Scritto dal nostro modello di IA a partire dal testo della fonte e confrontato automaticamente con esso.",
           "pt": "Escrito pelo nosso próprio modelo de IA a partir do texto da fonte e verificado automaticamente com ele.",
           "pl": "Napisane przez nasz własny model AI na podstawie tekstu źródłowego i automatycznie z nim porównane."}


def auto_texts():
    """Note descriptions the nightly job wrote (maintenance.py, data/auto.db), read again when the file changes."""
    try:
        m = os.path.getmtime(maintenance.AUTO_DB)
    except OSError:
        return {}
    if _auto["mtime"] != m:
        _auto.update(mtime=m, texts=maintenance.texts())
    return _auto["texts"]


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
    if lang != "en":   # 1.234,56
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{sym}{s}"


def num(n, lang="en"):
    s = f"{n:,}"
    return s.replace(",", ".") if lang != "en" else s


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
    # Where a photo comes from (one of OPEN_FACTS, or "commons") and, for Commons, its credit (JSON).
    for col in ("source TEXT", "credit TEXT"):
        try:
            con.execute(f"ALTER TABLE page_images ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass   # already there


# The Open Facts projects share barcodes and all publish their photos under CC BY-SA. A perfume's barcode is
# sometimes only in Open Products Facts or Open Food Facts ("product found with a different product type").
OPEN_FACTS = [("openbeautyfacts.org", "Open Beauty Facts"), ("openproductsfacts.org", "Open Products Facts"),
              ("openfoodfacts.org", "Open Food Facts")]
PHOTOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfume_photos.json")


def open_facts_image(gtin, opener=urllib.request.urlopen):
    """(photo URL, site) of the front photo any Open Facts project has for this barcode (any language), or None."""
    for site, _ in OPEN_FACTS:
        url = f"https://world.{site}/api/v2/product/{gtin}.json?fields=code,image_front_url,selected_images"
        req = urllib.request.Request(url, headers={"User-Agent": obf.USER_AGENT})
        try:
            with opener(req, timeout=20) as r:
                d = json.loads(r.read(400_000))
        except urllib.error.HTTPError as err:
            if err.code == 404:   # not in this project (or another product type): try the next one
                continue
            raise
        prod = d.get("product") or {} if d.get("status") == 1 else {}
        front = (prod.get("selected_images") or {}).get("front", {}).get("display", {})
        for u in [prod.get("image_front_url")] + list(front.values()):
            if u and re.match(r"https://images\.open(beauty|products|food)facts\.org/", u):
                return u, site
    return None


def fetch_image(url, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": obf.USER_AGENT})
    with opener(req, timeout=20) as r:
        data = r.read(IMG_MAX + 1)
    if len(data) > IMG_MAX or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        return None
    return data


def approved_photos(path=PHOTOS_FILE):
    """{perfume id: Commons file name} checked by hand (from the review list of llm_review.job_photos)."""
    try:
        with open(path, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_") and re.fullmatch(r"[0-9a-f]{12}", k)}
    except FileNotFoundError:
        return {}


def _save(con, key, data, product, source, credit, now):
    file = f"{key}.jpg" if data[:2] == b"\xff\xd8" else f"{key}.png"
    with open(os.path.join(IMG_DIR, file), "wb") as f:
        f.write(data)
    con.execute("INSERT OR REPLACE INTO page_images (gtin, file, product, checked, source, credit) VALUES (?,?,?,?,?,?)",
                (key, file, product, now, source, json.dumps(credit) if credit else None))


def refresh_images(con, opener=urllib.request.urlopen, now=None, limit=40, approved=None):
    """A bottle photo for each published perfume that has none yet: first from the Open Facts projects (every
    barcode, front photo in any language; each barcode again only after IMG_RECHECK), else the Commons photo
    approved for it in perfume_photos.json. At most `limit` lookups per run. Returns the number of new photos."""
    init(con)
    now = int(now or time.time())
    os.makedirs(IMG_DIR, exist_ok=True)
    approved = approved_photos() if approved is None else approved
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
            try:
                found = open_facts_image(g, opener)
                data = fetch_image(found[0], opener) if found else None
            except Exception as err:   # network trouble: try this barcode again next time
                print("photo lookup failed:", g, type(err).__name__, flush=True)
                continue
            if data:
                _save(con, g, data, g, found[1], None, now)
                done += 1
                break
            con.execute("INSERT OR REPLACE INTO page_images (gtin, file, product, checked) VALUES (?,?,?,?)",
                        (g, None, None, now))
            if limit <= 0:
                break
        name = approved.get(p["id"])
        if name and not photo(con, p) and limit > 0:
            limit -= 1
            try:
                found = notephotos.commons_file(name, opener)
            except Exception as err:
                print("commons photo failed:", p["id"], type(err).__name__, flush=True)
                found = None
            if found:
                data, info = found
                _save(con, "c-" + p["id"], data, info["page"], "commons",
                      {"artist": info["artist"], "license": info["license"], "license_url": info["license_url"]}, now)
                done += 1
    con.commit()
    return done


def photo(con, p):
    """(file, product, source, credit) of the perfume's stored photo, or None. product is the barcode (Open Facts)
    or the Commons file page; credit is a dict for Commons photos."""
    keys = list(p.get("gtins") or []) + ["c-" + p["id"]]
    try:
        rows = con.execute(f"SELECT file, product, source, credit, gtin FROM page_images WHERE file IS NOT NULL "
                           f"AND gtin IN ({','.join('?' * len(keys))})", keys).fetchall()
    except sqlite3.OperationalError:   # table not made yet
        return None
    rows = sorted(rows, key=lambda r: (r[4].startswith("c-"), r[4]))   # an Open Facts photo before a Commons one
    for file, product, source, credit, _ in rows:
        if os.path.exists(os.path.join(IMG_DIR, file)):
            return file, product, source or "openbeautyfacts.org", json.loads(credit) if credit else None
    return None


def photo_credit(ph, t):
    """The caption under a bottle photo, linking to where it comes from."""
    file, product, source, credit = ph
    if source == "commons" and credit:
        lic = (f'<a href="{e(credit["license_url"])}" rel="nofollow">{e(credit["license"])}</a>'
               if str(credit.get("license_url", "")).startswith("https://") else e(credit["license"]))
        return f'{t["photo"]}: {e(credit["artist"])}, {lic}, <a href="{e(product)}" rel="nofollow">Wikimedia Commons</a>'
    name = dict(OPEN_FACTS).get(source, "Open Beauty Facts")
    return f'{t["photo"]}: <a href="https://world.{e(source)}/product/{e(product)}">{name}</a>, CC BY-SA'


def image_file(name):
    """(bytes, content type) of a cached photo, for GET /photo/<file>, or None."""
    if not re.fullmatch(r"(\d{8,14}|c-[0-9a-f]{12})\.(jpg|png)", name):   # barcode (Open Facts) or c-<id> (Commons)
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
.btn.quiet{background:transparent;color:var(--plum);box-shadow:inset 0 0 0 1.5px var(--mauve)}.btn.quiet:hover{background:var(--white);color:var(--plum-deep)}
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
.tier{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:18px 0;border-top:1px solid var(--line)}.tier:last-of-type{border-bottom:1px solid var(--line)}.tier:last-of-type:has(+ details.single){border-bottom:0}
.tier h3{margin:4px 0 0;font:700 1rem/1.2 var(--display)}.tier h3 small{display:block;font:400 .8125rem/1.3 var(--text);color:var(--ink-soft);margin-top:3px}
.notes{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.note{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;border-radius:999px;font:500 .9688rem/1.2 var(--text);text-decoration:none}
a.note:hover{box-shadow:0 0 0 2px var(--plum)}
.note.ok{background:var(--white);color:var(--ink);border:1px solid var(--line)}a.note.ok:hover{border-color:var(--mauve);box-shadow:none}
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
.stats span{display:block;margin-top:8px;color:var(--ink-soft);font-size:.9375rem;line-height:1.35}.stats .hl b{color:var(--plum)}
.asof{margin:12px 0 0;color:var(--ink-soft);font-size:.875rem}
section.part{padding:80px 0 0}section.part h2{font-size:clamp(1.8rem,3.4vw,2.5rem);margin-bottom:14px}
.intro{margin:0 0 32px;color:var(--ink-soft);max-width:38em}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:0;padding:0;list-style:none;counter-reset:s}
.steps li{background:var(--white);border:1px solid var(--line);border-radius:22px;padding:26px;counter-increment:s}
.steps li::before{content:counter(s);display:grid;place-items:center;width:38px;height:38px;border-radius:50%;background:var(--paper);color:var(--plum);font:800 1.125rem/1 var(--display);margin-bottom:16px}
.steps h3{margin:0 0 6px;font:700 1.1875rem/1.25 var(--display)}.steps p{margin:0;color:var(--ink-soft);font-size:.9688rem}
.chip{display:inline-flex;gap:6px;padding:3px 10px;border-radius:999px;background:var(--paper);color:var(--ink);font-weight:500;font-size:.875rem}
.chip::before{content:"\\2713";color:var(--ok);font-weight:700}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}
.pcard{display:flex;flex-direction:column;background:var(--white);border:1px solid var(--line);border-radius:22px;padding:22px;color:var(--ink);text-decoration:none}
.pcard:hover{color:var(--ink);box-shadow:0 18px 40px -22px rgba(74,26,59,.45)}
.ptop{display:grid;grid-template-columns:minmax(0,1fr) 84px;gap:14px;height:100px;margin-bottom:12px}.pt{min-width:0}
.pimg{width:84px;height:84px;border-radius:14px;background:var(--paper);overflow:hidden}
.pimg img{width:100%;height:100%;object-fit:contain;padding:6px;display:block}
.pimg .ph{display:grid;place-items:center;width:100%;height:100%;font:800 2.1rem/1 var(--display);color:#fff;text-shadow:0 1px 10px rgba(43,20,38,.35)}
.pcard .h{font:600 .9375rem/1 var(--display);color:var(--plum);margin:0 0 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pcard .n{font:750 1.25rem/1.15 var(--display);margin:0 0 4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pcard .c{color:var(--ink-soft);font-size:.875rem;line-height:1.4;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pcard ul{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px;padding:0;list-style:none}
.pcard li{padding:4px 10px;border-radius:999px;background:var(--white);border:1px solid var(--line);color:var(--ink);font-size:.8438rem}
.pcard .p{display:flex;justify-content:space-between;border-top:1px solid var(--line);padding-top:12px;font-size:.9375rem;color:var(--ink-soft);margin-top:auto}
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
.langsel{position:relative}.langsel summary{list-style:none;display:inline-flex;align-items:center;gap:7px;cursor:pointer;padding:9px 14px;border-radius:999px;border:1.5px solid var(--line);background:var(--white);font:600 .9375rem/1 var(--text);color:var(--ink)}
.langsel summary::-webkit-details-marker{display:none}.langsel summary::after{content:"";width:7px;height:7px;border:solid var(--ink-soft);border-width:0 2px 2px 0;transform:rotate(45deg) translate(-2px,-2px);margin-left:2px}
.langsel[open] summary{border-color:var(--mauve)}
.langsel ul{position:absolute;right:0;top:calc(100% + 6px);z-index:10;margin:0;padding:6px;list-style:none;background:var(--white);border:1px solid var(--line);border-radius:16px;box-shadow:0 18px 40px -18px rgba(74,26,59,.45);min-width:170px}
.langsel li a{display:block;padding:9px 12px;border-radius:10px;color:var(--ink);text-decoration:none;font-size:.9688rem}
.langsel li a:hover{background:var(--paper)}.langsel li a[aria-current]{font-weight:700;color:var(--plum)}
@media (max-width:560px){.top .btn.small{display:none}}
.lang:hover{color:var(--plum)}
.chart{margin:26px 0 0}.chart h3{margin:0 0 8px;font:700 1rem/1.2 var(--display)}.chart svg{width:100%;height:auto;display:block}
.chart .axis{display:flex;justify-content:space-between;font-size:.8125rem;color:var(--ink-soft);margin-top:4px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.chips a{display:inline-block;padding:8px 14px;border-radius:999px;background:var(--white);border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:.9688rem}
.chips a:hover{box-shadow:0 0 0 2px var(--plum)}.chips small{color:var(--ink-soft);margin-left:4px}
.letter{font:750 1.25rem/1 var(--display);margin:26px 0 10px;color:var(--plum)}
.sr{position:absolute;opacity:0;width:1px;height:1px;margin:0;pointer-events:none}.sr-t{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.score{display:flex;align-items:baseline;gap:10px;margin:4px 0 6px}.score .big{font:800 2.4rem/1 var(--display)}.score .st{color:var(--plum);font-size:1.3rem;letter-spacing:2px}
form.vote{margin-top:22px;padding-top:18px;border-top:1px solid var(--line)}form.vote h3{margin:0 0 2px;font:700 1.05rem/1.2 var(--display)}form.vote .sub{margin:0 0 12px;font-size:.875rem}
form.vote fieldset{border:0;padding:0;margin:12px 0 0;min-width:0}form.vote legend{font:600 .875rem/1.3 var(--text);margin-bottom:6px;padding:0}.qgrid{display:grid;grid-template-columns:1fr 1fr;gap:0 24px}
.own{display:flex;gap:10px;align-items:center;padding:9px 12px;background:var(--paper);border-radius:12px;font-weight:600;font-size:.9375rem;cursor:pointer}
.own input{width:20px;height:20px;accent-color:var(--plum)}
.stars .opts{display:inline-flex;flex-direction:row-reverse;gap:2px}
.stars label{cursor:pointer;font-size:1.6rem;line-height:1;color:var(--line);padding:0 2px}.stars label::before{content:"\\2605"}
.stars label:hover,.stars label:hover~label,.stars input:checked~label{color:var(--plum)}
.scale .opts{display:flex;flex-wrap:wrap;gap:6px}
.scale label{padding:5px 11px;border-radius:999px;border:1.5px solid var(--line);background:var(--white);cursor:pointer;font-size:.8438rem}
.scale label:hover{border-color:var(--mauve)}.scale input:checked+label{background:var(--plum);border-color:var(--plum);color:var(--white)}
form.vote input:focus-visible+label{outline:3px solid var(--plum);outline-offset:2px}
form.vote .btn{margin-top:16px;padding:11px 20px;font-size:.9375rem}form.vote .muted{margin-top:10px;font-size:.8125rem}form.vote .vmsg{margin:4px 0 12px;padding:9px 14px;font-size:.9375rem}
.vmsg{padding:12px 16px;border-radius:14px;background:#fdf0e6;color:#6b3a12;margin:0 0 14px}.vmsg.ok{background:var(--ok-bg);color:#173f28}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:14px 10px;margin:0;padding:0;list-style:none}
.tile{display:flex;flex-direction:column;align-items:center;gap:7px;text-align:center;font:500 .875rem/1.25 var(--text);color:var(--ink);text-decoration:none}
.nimg{width:72px;height:72px;border-radius:18px;overflow:hidden;display:grid;place-items:center;background:var(--c,var(--paper));color:var(--f,var(--ink-soft));font:700 1.625rem/1 var(--display);box-shadow:0 0 0 1px var(--line)}
.nimg img{width:100%;height:100%;object-fit:cover;display:block}a.tile:hover .nimg{box-shadow:0 0 0 2px var(--mauve)}a.tile:hover{color:var(--plum)}
.credit{margin:10px 0 0;font-size:.8125rem}
.notephoto{margin:0}.notephoto img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:22px;display:block;background:var(--paper)}
.notephoto figcaption{margin-top:6px;font-size:.75rem;color:var(--ink-soft)}.notephoto figcaption a{color:var(--ink-soft)}
details.single{border-top:1px solid var(--line);padding-top:14px}details.single summary{cursor:pointer;font-weight:600;font-size:.9375rem;color:var(--ink-soft)}
details.single summary:hover{color:var(--plum)}details.single p{margin:8px 0 6px}details.single ul{margin:0;padding:0;list-style:none;columns:2;column-gap:24px}
details.single li{font-size:.9063rem;padding:3px 0;break-inside:avoid}details.single li .muted{display:inline-block;min-width:3.6em}
@media (max-width:560px){details.single ul{columns:1}}
.astrip{display:flex;gap:3px;height:44px;border-radius:12px;overflow:hidden;margin-top:6px}.astrip i{flex:var(--w) 1 0;min-width:8px;background:var(--c)}
.achips{display:flex;flex-wrap:wrap;gap:8px 18px;margin:14px 0 0;padding:0;list-style:none}
.achips li{display:inline-flex;align-items:center;gap:7px;font:500 .9375rem/1.2 var(--text);color:var(--ink)}
.achips li i{width:12px;height:12px;border-radius:50%;flex:none;background:var(--c);box-shadow:inset 0 0 0 1px rgba(0,0,0,.12)}
.achips small{color:var(--ink-soft);font-size:.8125rem;font-variant-numeric:tabular-nums}
@media (prefers-reduced-motion:no-preference){.astrip i{animation:grow .9s cubic-bezier(.2,.7,.2,1) both;animation-delay:calc(var(--i) * 70ms + 150ms);transform-origin:left}@keyframes grow{from{transform:scaleX(0)}}}
.vgrid{display:grid;grid-template-columns:1fr 1fr;gap:18px 28px;margin:14px 0 4px}.vgrid h3{margin:0 0 6px;font:700 .9375rem/1.2 var(--display)}
.vbar{display:grid;grid-template-columns:8.5em minmax(48px,1fr) 1.6em;gap:10px;align-items:center;font-size:.8125rem;line-height:1.5;color:var(--ink-soft)}
.vbar .l{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.vbar .track{height:8px}.vbar .n{text-align:right;font-variant-numeric:tabular-nums}
.vbar.best{color:var(--ink)}.vbar.best .fill{background:var(--plum)}.vbar.best .n{font-weight:700}
.score{margin:2px 0 4px}.score .big{font-size:2rem}
@media (max-width:560px){.vgrid,.qgrid{grid-template-columns:1fr}.astrip{height:32px;border-radius:10px}}
.sizes{margin-top:24px}.szpick{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}
.szpick label{padding:8px 14px;border-radius:999px;border:1.5px solid var(--line);background:var(--white);font:600 .875rem/1 var(--text);color:var(--ink-soft);cursor:pointer}
.szpick label:hover{border-color:var(--mauve);color:var(--ink)}.szp{display:none}.sizes .bars{margin-top:18px}
.dbhero{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:40px;align-items:end;padding:28px 0 4px}
.dbhero h1{font-size:clamp(2.2rem,4.4vw,3.6rem);max-width:none;margin:0}.dbhero .lead{font-size:1.0625rem;margin:0 0 6px}
section.part.first{padding-top:44px}.parthead{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.parthead h2{margin:0}.parthead h2 small{font:600 1rem/1 var(--text);color:var(--ink-soft);margin-left:6px;vertical-align:middle}
section.part.first .parthead{margin-bottom:22px}.showsel ul,.regsel ul{min-width:150px}#prices .parthead{margin-bottom:6px}#prices .parthead h2{margin:0}
.pager{display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:6px;margin:30px 0 0}
.pager a,.pager span{min-width:40px;height:40px;padding:0 12px;display:inline-grid;place-items:center;border-radius:999px;font:600 .9375rem/1 var(--text);text-decoration:none}
.pager a{background:var(--white);border:1.5px solid var(--line);color:var(--ink)}.pager a:hover{border-color:var(--mauve);color:var(--plum)}
.pager .cur{background:var(--plum);color:var(--white)}.pager .gap{color:var(--ink-soft);min-width:20px;padding:0}.pager .step{padding:0 16px}
.top .wrap{gap:18px}.hsearch{flex:1;max-width:440px;display:flex;align-items:center;background:var(--white);border:1.5px solid var(--line);border-radius:999px;padding:3px 3px 3px 16px}
.hsearch:focus-within{border-color:var(--mauve)}.hsearch input{flex:1;min-width:0;border:0;background:none;font:400 .9688rem/1.2 var(--text);color:var(--ink);padding:8px 0;outline:none}
.hsearch button{border:0;background:var(--plum);color:var(--white);width:38px;height:38px;border-radius:50%;display:grid;place-items:center;cursor:pointer}.hsearch button:hover{background:var(--plum-deep)}
@media (max-width:760px){.top .wrap{flex-wrap:wrap}.hsearch{order:3;flex-basis:100%;max-width:none}}
.listsearch{display:flex;align-items:center;max-width:560px;margin:0 0 24px;background:var(--white);border:1.5px solid var(--line);border-radius:999px;padding:4px 4px 4px 18px}
.listsearch:focus-within{border-color:var(--mauve)}.listsearch input{flex:1;min-width:0;border:0;background:none;font:400 1rem/1.2 var(--text);color:var(--ink);padding:9px 0;outline:none}
.listsearch button{border:0;background:var(--plum);color:var(--white);width:40px;height:40px;border-radius:50%;display:grid;place-items:center;cursor:pointer}.listsearch button:hover{background:var(--plum-deep)}
.nomatch{margin:8px 0 0;color:var(--ink-soft)}.listsearch input::-webkit-search-cancel-button,.hsearch input::-webkit-search-cancel-button{-webkit-appearance:none;appearance:none}
.pcard{transition:opacity .22s ease,transform .22s ease}.pcard.out{opacity:0;transform:scale(.96)}
.pcard.in{animation:cardin .28s ease both}@keyframes cardin{from{opacity:0;transform:translateY(6px)}}
.langsel summary{height:40px;padding:0 14px}.top .btn.small{height:40px;padding:0 18px}
.how h2{font-size:clamp(1.3rem,2.4vw,1.6rem)}.how .intro{font-size:.9375rem;margin-bottom:18px}.how .steps{gap:14px}
.how .steps li{padding:18px;border-radius:18px}.how .steps li::before{width:28px;height:28px;font-size:.9375rem;margin-bottom:10px}
.how .steps h3{font-size:1rem}.how .steps p{font-size:.875rem}
.astrip.mini{height:12px;border-radius:6px;gap:2px;margin:0 0 14px}.astrip.mini.none{background:var(--paper)}
.official{margin:-12px 0 18px;font-size:.875rem;font-weight:600;color:var(--plum)}.astrip.big{height:150px;border-radius:22px;gap:4px;margin:0}
@media (max-width:900px){.dbhero{grid-template-columns:1fr;gap:12px}.astrip.big{height:90px}}
"""
# The size picker of the price card (no script): the n-th radio shows the n-th panel and marks the n-th button.
MAX_SIZES = 8
CSS += "".join(
    f".sizes input:nth-of-type({n}):checked~.szp:nth-of-type({n}){{display:block}}"
    f".sizes input:nth-of-type({n}):checked~.szpick label:nth-of-type({n}){{background:var(--plum);border-color:var(--plum);color:#fff}}"
    f".sizes input:nth-of-type({n}):focus-visible~.szpick label:nth-of-type({n}){{outline:2px solid var(--mauve);outline-offset:2px}}\n"
    for n in range(1, MAX_SIZES + 1))


def ld_json(obj):
    """JSON for a <script type="application/ld+json"> block: <, > and & as \\u escapes, so no value can end
    the block or start markup in it."""
    s = json.dumps(obj, ensure_ascii=False)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def search_form(lang, cls, action, value="", hidden=""):
    """The round search field with its magnifier button: in the header ("hsearch"), and under "All perfumes"
    ("listsearch", filtered live as you type by /assets/live.js)."""
    t = T[lang]
    return (f'<form class="{cls}" role="search" action="{action}">{hidden}<input type="search" name="q" value="{e(value)}" '
            f'placeholder="{t["searchPh"]}" aria-label="{t["searchPh"]}" maxlength="100" autocomplete="off">'
            f'<button type="submit" aria-label="{t["search"]}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/>'
            f'<path d="m20 20-3.5-3.5"/></svg></button></form>')


def frame(lang, title, desc, path, body, noindex=False, image=None, jsonld=None, foot="", search=True, script=False):
    """A whole page. `path` is the page's path without the language prefix (the same in every language)."""
    t = T[lang]
    alt = "".join(f'<link rel="alternate" hreflang="{l}" href="{e(BASE + P(l, path))}">' for l in LANGS)
    head = ('<meta name="robots" content="noindex">' if noindex else
            f'<link rel="canonical" href="{e(BASE + P(lang, path))}">{alt}<link rel="alternate" hreflang="x-default" href="{e(BASE + path)}">')
    ld = f'<script type="application/ld+json">{ld_json(jsonld)}</script>' if jsonld else ""
    # Language menu: a <details> list (no script), every language's version of this same page.
    langs = "".join(f'<li><a href="{e(P(l, path))}" hreflang="{l}" lang="{l}"{" aria-current=" + chr(34) + "true" + chr(34) if l == lang else ""}>'
                    f'{T[l]["langName"]}</a></li>' for l in LANGS)
    menu = (f'<details class="langsel"><summary aria-label="Language">'
            f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">'
            f'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>'
            f'{t["langName"]}</summary><ul>{langs}</ul></details>')
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
{ld}{f'<script src="/assets/live.js?v={JS_VERSION}" defer></script>' if script else ""}
</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{SITE}"><img src="{SITE}img/icon.png" alt="">Fragrance Notes</a>
{search_form(lang, "hsearch", P(lang, "/database/search")) if search else ""}
<nav>{menu}
<a class="btn small" href="{STORE}">{t["getExt"]}</a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
<p>{t["footData"]}</p>
<p>{t["footNot"]}</p>
{foot}
<p><a href="{P(lang, '/database')}">{t["theDb"]}</a> · <a href="{P(lang, '/notes')}">{t["allNotes"]}</a> · <a href="{SITE}privacy.html">{t["privacy"]}</a> · <a href="https://github.com/Tygovanschie/fragrance-notes">{t["source"]}</a></p>
</div></footer>
</body>
</html>"""


CSS_VERSION = hashlib.sha1(CSS.encode()).hexdigest()[:8]

# The only script on the site (CSP: script-src 'self'): live search in the perfume list. While you type it asks the
# server for the same page with ?q= and lets the cards that no longer match fade out; matching cards stay where they
# are. Without it the search form still works (Enter loads /database?q=).
LIVE_JS = r"""(() => {
  const form = document.querySelector('form.listsearch');
  const box = document.getElementById('results');
  if (!form || !box || !window.fetch || !window.DOMParser) return;
  const input = form.querySelector('input[name=q]');
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let timer = 0, ctl = null, last = input.value.trim();
  const key = a => a.getAttribute('href');
  async function run(force) {
    const q = input.value.trim();
    if (q === last && !force) return;
    last = q;
    const url = new URL(form.getAttribute('action'), location.href);
    for (const h of form.querySelectorAll('input[type=hidden]')) url.searchParams.set(h.name, h.value);
    if (q) url.searchParams.set('q', q);
    if (ctl) ctl.abort();
    ctl = new AbortController();
    let doc;
    try {
      const r = await fetch(url, { signal: ctl.signal, headers: { Accept: 'text/html' } });
      doc = new DOMParser().parseFromString(await r.text(), 'text/html');
    } catch (err) { return; }
    const next = doc.getElementById('results');
    if (!next || q !== input.value.trim()) return;
    const cards = box.querySelector('.cards'), nextCards = next.querySelector('.cards');
    const keep = new Set([...nextCards.children].map(key));
    const gone = [...cards.children].filter(a => !keep.has(key(a)));
    gone.forEach(a => a.classList.add('out'));
    if (gone.length && !still) await new Promise(r => setTimeout(r, 230));
    if (q !== input.value.trim()) return;
    const have = new Map([...cards.children].map(a => [key(a), a]));
    cards.replaceChildren(...[...nextCards.children].map(a => {
      const old = have.get(key(a));
      if (old) { old.classList.remove('out'); return old; }
      if (!still) a.classList.add('in');
      return a;
    }));
    [...box.children].filter(n => n !== cards).forEach(n => n.remove());
    [...next.children].filter(n => !n.classList.contains('cards')).forEach(n => box.append(n));
    history.replaceState(null, '', url.pathname + url.search);
  }
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 160); });
  form.addEventListener('submit', e => { e.preventDefault(); clearTimeout(timer); run(true); });
})();
"""
JS_VERSION = hashlib.sha1(LIVE_JS.encode()).hexdigest()[:8]


def back(lang):
    return f'<a class="back" href="{P(lang, "/database")}">{T[lang]["back"]}</a>'


def img_tag(con, p, cls="", size=400):
    ph = photo(con, p)
    if not ph:
        return ""
    return f'<img{f" class={chr(34)}{cls}{chr(34)}" if cls else ""} src="/photo/{e(ph[0])}" alt="" width="{size}" height="{size}" loading="lazy">'


# The country menu on the price card (regions.py): (summary word, eurozone, "no prices for X yet", "fallback to the
# eurozone" note).
REGION_T = {
    "en": ("Prices for", "Eurozone", "No prices for {where} yet. Prices are known for:", "No shop in {where} yet: prices from other eurozone shops."),
    "nl": ("Prijzen voor", "Eurozone", "Nog geen prijzen voor {where}. Wel bekend voor:", "Nog geen winkel in {where}: prijzen van andere winkels in de eurozone."),
    "de": ("Preise für", "Eurozone", "Noch keine Preise für {where}. Bekannt für:", "Noch kein Shop in {where}: Preise anderer Shops in der Eurozone."),
    "fr": ("Prix pour", "Zone euro", "Pas encore de prix pour {where}. Prix connus pour :", "Pas encore de boutique en {where} : prix d’autres boutiques de la zone euro."),
    "es": ("Precios para", "Eurozona", "Aún no hay precios para {where}. Hay precios para:", "Aún no hay tiendas en {where}: precios de otras tiendas de la eurozona."),
    "it": ("Prezzi per", "Eurozona", "Ancora nessun prezzo per {where}. Prezzi noti per:", "Ancora nessun negozio in {where}: prezzi di altri negozi dell’eurozona."),
    "pt": ("Preços para", "Zona euro", "Ainda não há preços para {where}. Há preços para:", "Ainda não há lojas em {where}: preços de outras lojas da zona euro."),
    "pl": ("Ceny dla", "Strefa euro", "Brak jeszcze cen dla {where}. Ceny są znane dla:", "Brak jeszcze sklepu w {where}: ceny z innych sklepów strefy euro."),
}


def region_name(code, lang):
    return f"{regions.flag(code)} {REGION_T[lang][1] if code == regions.ZONE else code}"


def region_menu(info, lang, path):
    """Links to the same page with the prices of another country (or the whole eurozone): no script needed."""
    avail = info.get("available") or {}
    if not avail:
        return ""
    opts = sorted(avail) + ([regions.ZONE] if sum(1 for c in avail.values() if c == "EUR") >= 2 else [])
    now = regions.ZONE if info.get("kind") == "zone" else (info["shown"][0] if len(info.get("shown") or []) == 1 else None)
    label = region_name(now, lang) if now else REGION_T[lang][0]
    return (f'<details class="langsel regsel"><summary aria-label="{REGION_T[lang][0]}">{label}</summary><ul>'
            + "".join(f'<li><a href="{P(lang, path)}?region={c}#prices"{" aria-current=" + chr(34) + "true" + chr(34) if c == now else ""}>'
                      f'{region_name(c, lang)}</a></li>' for c in opts) + "</ul></details>")


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


# ---------- votes (votes.py) ----------

def vote_results(s, t):
    """The result bars per question; only from votes.MIN_VOTERS voters."""
    if s["voters"] < votes.MIN_VOTERS:
        return f'<p class="sub">{t["votesSoFar"](s["voters"]) if s["voters"] else t["votesNone"]}</p>'
    out = []
    r = s["rating"]
    # One line with the stars and how many votes in total; then the four questions in a compact 2 x 2 grid, each
    # answer with its number of votes.
    if r["n"]:
        full = round(r["avg"])
        stars = "★" * full + "☆" * (5 - full)
        out.append(f'<p class="score"><span class="big">{r["avg"]:.1f}</span> <span class="st" aria-hidden="true">{stars}</span>'
                   f' <span class="muted">{t["votedBy"](s["voters"])}</span></p>')
    else:
        out.append(f'<p class="score"><span class="muted">{t["votedBy"](s["voters"])}</span></p>')
    blocks = []
    for f, labels in t["scale"].items():
        x = s[f]
        if not x["n"]:
            continue
        top = max(x["dist"]) or 1
        rows = "".join(
            f'<div class="vbar{" best" if c == top else ""}"><span class="l" title="{e(lab)}">{e(lab.split(" (")[0])}</span><span class="track"><span class="fill" style="width:{c / top * 100:.0f}%"></span></span>'
            f'<span class="n">{c}</span></div>' for lab, c in zip(labels, x["dist"]))
        blocks.append(f'<div><h3>{t["r"][f]}</h3>{rows}</div>')
    if blocks:
        out.append(f'<div class="vgrid">{"".join(blocks)}</div>')
    return "".join(out)


def vote_section(con, p, lang, state=None, voter=None):
    """Results plus the form. Someone who voted before (voter = hash of their cookie code) sees their answers
    filled in and a "saved" note; the page is then never cached (app.page_get)."""
    t = T[lang]
    s = votes.summary(con, p["id"])
    my = votes.mine(con, p["id"], voter) or {}
    msg = t["voteMsg"].get(state or "")
    note = f'<p class="vmsg{" ok" if state == "thanks" else ""}" role="status">{e(msg)}</p>' if msg and not (my and state == "thanks") else ""
    if my:
        note = f'<p class="vmsg ok" role="status">✓ {e(t["voteSaved"])}</p>' + note
    on = lambda f, i: " checked" if my.get(f) == i else ""
    stars = "".join(f'<input class="sr" type="radio" name="rating" id="r{i}" value="{i}"{on("rating", i)}><label for="r{i}" title="{e(t["star"](i))}">'
                    f'<span class="sr-t">{e(t["star"](i))}</span></label>' for i in range(5, 0, -1))
    scales = "".join(
        f'<fieldset class="scale"><legend>{t["r"][f]}</legend><div class="opts">'
        + "".join(f'<input class="sr" type="radio" name="{f}" id="{f}{i}" value="{i}"{on(f, i)}><label for="{f}{i}">{e(lab)}</label>'
                  for i, lab in enumerate(labels, 1))
        + "</div></fieldset>" for f, labels in t["scale"].items())
    form = f"""<form class="vote{' voted' if my else ''}" method="post" action="{P(lang, f'/perfume/{p["id"]}/vote')}">
<h3>{t["yourVoteH"]}</h3>{note}<p class="sub">{t["voteChange"] if my else t["voteIntro"]}</p>
<label class="own"><input type="checkbox" name="owns" value="1" required{" checked" if my else ""}> {t["owns"]}</label>
<fieldset class="stars"><legend>{t["q"]["rating"]}</legend><div class="opts">{stars}</div></fieldset>
<div class="qgrid">{scales}</div>
<button class="btn" type="submit">{t["update"] if my else t["send"]}</button>
<p class="muted">{t["voteNote"]}</p></form>"""
    return f'<section class="card" id="vote" aria-labelledby="vote-h"><h2 id="vote-h">{t["voteH"]}</h2>{vote_results(s, t)}{form}</section>', s


def vote_target(con, pid):
    """Where a vote on this perfume goes back to: its page, or its rating page when it has no page yet; None if
    it isn't in the catalog."""
    p = index(con)["byId"].get(pid)
    if p:
        return perfume_path(p)
    con.row_factory = sqlite3.Row
    return f"/perfume/{pid}/rate" if con.execute("SELECT 1 FROM catalog WHERE id=?", (pid,)).fetchone() else None


def rate_page(con, pid, lang="en", state=None, voter=None):
    """/perfume/<id>/rate: just the voting block, for any perfume in the catalog (the extension's "Own it? Rate
    it" button opens it). Perfumes with a full page redirect there; this page itself is not indexed."""
    t = T[lang]
    idx = index(con)
    if pid in idx["byId"]:
        return perfume_path(idx["byId"][pid]) + "#vote", None
    p = catalog.perfume(con, pid)
    if not p:
        return None
    vote_html, _ = vote_section(con, p, lang, state, voter)
    ph = photo(con, p)
    photo_html = (f'<figure class="photo"><img src="/photo/{e(ph[0])}" alt="" width="400" height="400">'
                  f'<figcaption>{photo_credit(ph, t)}</figcaption></figure>') if ph else ""
    tags = [conc_name(p), t["gender"].get(p.get("gender") or "", "")]
    body = f"""{back(lang)}
<section class="head{'' if ph else ' nophoto'}">{photo_html}<div>
<p class="house">{e(p["brand"])}</p><h1>{e(p["name"])}</h1>
<ul class="tags">{"".join(f"<li>{e(x)}</li>" for x in tags if x)}</ul>
<p class="trust">{t["rateLead"]}</p></div></section>
<div class="grid"><div>{vote_html}</div></div>"""
    return None, frame(lang, t["rateTitle"].format(full=t["by"].format(name=p["name"], brand=p["brand"])),
                       t["voteIntro"], f"/perfume/{pid}/rate", body, noindex=True)


# ---------- /perfume/<id>-<slug> ----------

def accord_strip(acc, cls=""):
    """The colour strip of [(accord, share)]: the site's (and the extension's) way of showing a scent."""
    return (f'<div class="astrip{" " + cls if cls else ""}" aria-hidden="true">'
            + "".join(f'<i style="--w:{v};--c:{accords.COLOURS[a][0]};--i:{i}"></i>' for i, (a, v) in enumerate(acc)) + "</div>")


def shares(acc):
    """[(accord, strength 0–100)] → [(accord, whole percent)] that add up to exactly 100 (largest remainder)."""
    total = sum(v for _, v in acc)
    if not total:
        return []
    raw = [(a, v * 100 / total) for a, v in acc]
    out = [[a, int(x)] for a, x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i][1] - int(raw[i][1]), reverse=True)[:100 - sum(v for _, v in out)]:
        out[i][1] += 1
    return [(a, v) for a, v in out]


def conc_name(p):
    return CONC.get(p.get("conc") or "", "")


def perfume_page(con, pid, prices=None, lang="en", vote=None, voter=None):
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
                  f'<figcaption>{photo_credit(ph, t)}</figcaption></figure>') if ph else ""
    full = t["by"].format(name=p["name"], brand=p["brand"])

    # The pyramid shows the confirmed notes only (2+ shops agree). Notes a single shop names often come from that
    # shop's own, different note list (Douglas: Iris and Amberwood on Stronger With You Intensely), so they go in a
    # closed list underneath, with the shop that named them.
    shown = []

    def thumb(n, name):   # the note's photo from Wikimedia Commons, else a square in its main accord's colour
        ph = notephotos.get(con, n.get("en") or "")
        if ph:
            shown.append(1)
            return (f'<span class="nimg"><img src="{e(ph["url"])}" alt="" width="72" height="72" '
                    f'loading="lazy"></span>')
        acc = accords.NOTES.get(n.get("en") or "")
        bg, fg = accords.COLOURS[max(acc, key=acc.get)] if acc else ("var(--paper)", "var(--ink-soft)")
        return f'<span class="nimg" style="--c:{bg};--f:{fg}" aria-hidden="true">{e(name[:1].upper())}</span>'

    tiers, single = [], []
    for tier, label, hint in t["tiers"]:
        chips = []
        for n in p["notes"][tier]:
            name = note_name(n["en"], lang) if n.get("en") else n["name"]
            if not n["confirmed"]:
                single.append((label, name, ", ".join(n.get("from") or [])))
                continue
            if n.get("en") in linkable:
                chips.append(f'<li><a class="tile" href="{P(lang, note_path(n["en"]))}">{thumb(n, name)}<span>{e(name)}</span></a></li>')
            else:
                chips.append(f'<li><span class="tile">{thumb(n, name)}<span>{e(name)}</span></span></li>')
        if chips:
            tiers.append(f'<div class="tier"><h3>{label}<small>{hint}</small></h3><ul class="tiles">{"".join(chips)}</ul></div>')
    single_html = (f'<details class="single"><summary>{t["singleH"].format(n=len(single))}</summary><p class="muted">{t["singleSub"]}</p><ul>'
                   + "".join(f'<li><span class="muted">{e(lab)}</span> {e(nm)}{f" <small>({e(src)})</small>" if src else ""}</li>'
                             for lab, nm, src in single) + "</ul></details>") if single else ""
    sites = sorted({n["official"] for tr in p["notes"].values() for n in tr if n.get("official")})
    official_html = (f'<p class="official">✓ {OFFICIAL[lang].format(site=e(", ".join(sites)))}</p>') if sites else ""

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
        # Per size: the price at each shop and the price history. Without a script (the pages have none), size
        # buttons are radio inputs and CSS shows the panel of the checked one (see .sizes in CSS). It starts on the
        # size most shops sell.
        rows = rows[:MAX_SIZES]
        start = max(range(len(rows)), key=lambda i: (rows[i][4], rows[i][0] == 100, rows[i][0]))
        panels = []
        for m, _, _, _, _, lows in rows:
            top = max(lows.values())
            bars = "".join(
                f'<div class="bar{" best" if i == 0 else ""}"><span>{e(s)}</span><span class="track"><span class="fill" style="width:{v / top * 100:.0f}%"></span></span>'
                f'<span class="eur">{e(money(v, cur, lang))}</span></div>'
                for i, (s, v) in enumerate(sorted(lows.items(), key=lambda kv: kv[1])))
            hist = chart([(d, v) for d, v in (st.get("history") or {}).get(m, [])], cur, lang)
            panels.append(f'<article class="szp"><div class="bars"><h3>{t["atEachShop"].format(size=ml(m))}</h3>{bars}</div>'
                          + (f'<div class="chart"><h3>{t["chartTitle"].format(size=ml(m))}</h3>{hist}</div>' if hist else "")
                          + "</article>")
        k = f"sz{p['id']}"
        inputs = "".join(f'<input class="sr" type="radio" name="{k}" id="{k}-{i}"{" checked" if i == start else ""}>' for i in range(len(rows)))
        picker = (f'<div class="szpick" role="group" aria-label="{t["size"]}">'
                  + "".join(f'<label for="{k}-{i}">{ml(r[0])}</label>' for i, r in enumerate(rows)) + "</div>") if len(rows) > 1 else ""
        shops_n = len({s for r in rows for s in r[5]})
        info = st.get("region") or {}
        zone_note = (f'<p class="muted">{REGION_T[lang][3].format(where=region_name(info["want"], lang))}</p>'
                     if info.get("kind") == "zone" and info.get("want") not in ("", regions.ZONE) else "")
        price_html = f"""<section class="card" id="prices" aria-labelledby="price-h"><div class="parthead"><h2 id="price-h">{t["prices"]}</h2>{region_menu(info, lang, perfume_path(p))}</div>
<p class="sub">{t["pricesSub"].format(days=st.get("days", 30), shops=t["shops"](shops_n))}</p>{zone_note}
<table><thead><tr><th>{t["size"]}</th><th class="num">{t["lowest"]}</th><th>{t["at"]}</th><th class="num hide-sm">{t["perMl"]}</th><th class="num hide-sm">{t["range"]}</th></tr></thead>
<tbody>{trs}</tbody></table>
<div class="sizes">{inputs}{picker}{"".join(panels)}</div></section>"""
        offers = {"@type": "AggregateOffer", "priceCurrency": cur, "lowPrice": f"{min(r[1] for r in rows):.2f}",
                  "highPrice": f"{max(r[3] for r in rows):.2f}", "offerCount": shops_n}
    elif st and (st.get("region") or {}).get("kind") == "none" and st["region"].get("available"):
        # Prices exist, but not for the visitor's country: say so and offer the others (never show them unasked).
        info = st["region"]
        price_html = (f'<section class="card" id="prices" aria-labelledby="price-h"><div class="parthead"><h2 id="price-h">{t["prices"]}</h2>'
                      f'{region_menu(info, lang, perfume_path(p))}</div><p class="sub">'
                      f'{REGION_T[lang][2].format(where=region_name(info["want"], lang))} '
                      f'{", ".join(region_name(c, lang) for c in sorted(info["available"]))}</p></section>')

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
    vote_html, vs = vote_section(con, p, lang, vote, voter)
    acc = shares(accords.main_accords(p))
    acc_html = (f'<section class="card" aria-labelledby="acc-h"><h2 id="acc-h">{t["accordsH"]}</h2><p class="sub">{t["accordsSub"]}</p>'
                + accord_strip(acc)
                + '<ul class="achips">' + "".join(f'<li><i style="--c:{accords.COLOURS[a][0]}"></i>{e(accords.name(a, lang))}<small>{v}%</small></li>' for a, v in acc) + "</ul>"
                + "</section>") if acc else ""

    body = f"""{back(lang)}
<section class="head{'' if ph else ' nophoto'}">{photo_html}<div>
<p class="house"><a href="{P(lang, brand_path(p['brand']))}" style="color:inherit;text-decoration:none">{e(p["brand"])}</a></p>
<h1>{e(p["name"])}</h1>
<ul class="tags">{"".join(f"<li>{e(x)}</li>" for x in tags if x)}</ul>
<p class="trust"><span>{t["trustShops"](p["shops"])}</span><span>{t["trustNotes"](conf)}</span><span>{t["lastSeen"]} <b>{e(day(p.get("lastSeen"), lang))}</b></span></p>
</div></section>
<div class="grid"><div>
{acc_html}
<section class="card" aria-labelledby="notes-h"><h2 id="notes-h">{t["notes"]}</h2>
<p class="sub">{t["notesSub"]}</p>{official_html}
{"".join(tiers)}
{single_html}
</section>
{vote_html}
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
    if vs["rating"]["n"] >= votes.GOOGLE_MIN:
        ld["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": vs["rating"]["avg"],
                                 "ratingCount": vs["rating"]["n"], "bestRating": 5, "worstRating": 1}
    if offers:
        ld["offers"] = offers
    foot = f'<p class="credit"><a href="{P(lang, "/notes")}">{t["notePhotos"]}</a></p>' if shown else ""
    return path, frame(lang, t["perfumeTitle"].format(full=full), desc, path, body, image=image, jsonld=ld, foot=foot)


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
    text = TEXTS.get(key) or auto_texts().get(key)   # reviewed by hand first, then the nightly job's
    about = ""
    if text:
        smell = text.get(f"smell_{lang}") or text["smell"]
        origin = text.get(f"origin_{lang}") or text["origin"]
        english = lang != "en" and not text.get(f"smell_{lang}")
        src = text.get("source", "")
        about = f"""<section class="card"{' lang="en"' if english else ""}><h2>{t["smellsLike"]}</h2><p>{e(smell)}</p>
<h2 style="margin-top:26px">{t["comesFrom"]}</h2><p>{e(origin)}</p>
<p class="src">{AI_AUTO[lang] if text.get("auto") else t["aiNote"]}
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
    # A free photo from Wikimedia Commons with its credit (notephotos.py), or else the note's colour field.
    ph = notephotos.get(con, key)
    if ph:
        lic = (f'<a href="{e(ph["license_url"])}" rel="nofollow">{e(ph["license"])}</a>' if ph["license_url"].startswith("https://")
               else e(ph["license"]))
        visual = (f'<figure class="notephoto"><img src="{e(ph["url"])}" alt="{e(name)}" width="400" height="300">'
                  f'<figcaption>{t["photo"]}: {e(ph["artist"])}, {lic}, '
                  f'<a href="{e(ph["page"])}" rel="nofollow">Wikimedia Commons</a></figcaption></figure>')
    elif accords.NOTES.get(key):   # no photo: the note's accords in the site's colour-strip style
        visual = accord_strip(shares(sorted(accords.NOTES[key].items(), key=lambda kv: -kv[1])), "big")
    else:
        visual = f'<div class="swatch" style="{swatch(key)}" aria-hidden="true"></div>'
    body = f"""{back(lang)}
<section class="head" style="grid-template-columns:1fr 340px;align-items:end"><div>
<p class="kind"><a href="{P(lang, '/notes')}" style="color:inherit;text-decoration:none">{t["perfumeNote"]}</a></p><h1>{e(name)}</h1>
{f'<p class="muted" style="font-size:1rem">{t["alsoWrite"]}: {", ".join(f"<b>{e(a)}</b>" for a in aka)}</p>' if aka else ""}
</div>{visual}</section>
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
    bits = [conc_name(p), (t["gender"].get(p.get("gender") or "", "") or "").lower()]   # the sources count is on the page itself
    acc = shares(accords.main_accords(p))
    # Every card has the same shape: a text block of fixed height with a square on the right (the bottle photo, or
    # without one a field in the perfume's own accord colours with its initial), so the accord strips line up.
    ph = img_tag(con, p, "", 84)
    if not ph:
        cols = [accords.COLOURS[a][0] for a, _ in acc[:3]] or ["#c58bb0", "#7e2f63"]
        cols = cols * 2 if len(cols) == 1 else cols
        ph = (f'<span class="ph" style="background:linear-gradient(140deg,{",".join(cols)})" aria-hidden="true">'
              f'{e(p["name"][:1].upper())}</span>')
    return (f'<a class="pcard" href="{P(lang, perfume_path(p))}"><div class="ptop"><div class="pt">'
            f'<p class="h">{e(p["brand"])}</p><p class="n">{e(p["name"])}</p><p class="c">{e(" · ".join(b for b in bits if b))}</p>'
            f'</div><div class="pimg">{ph}</div></div>'
            f'{accord_strip(acc, "mini") if acc else "<div class=" + chr(34) + "astrip mini none" + chr(34) + "></div>"}'
            f'<ul>{"".join(f"<li>{e(c)}</li>" for c in conf[:8])}</ul>{tail}</a>')


# Notes confirmed by the brand's own website (catalog.OFFICIAL_SITES): they don't need a second shop.
OFFICIAL = {"en": "Confirmed by the brand's own website: {site}", "nl": "Bevestigd door de eigen website van het merk: {site}",
            "de": "Bestätigt von der eigenen Website der Marke: {site}", "fr": "Confirmé par le site officiel de la marque : {site}",
            "es": "Confirmado por la web oficial de la marca: {site}", "it": "Confermato dal sito ufficiale del marchio: {site}",
            "pt": "Confirmado pelo site oficial da marca: {site}", "pl": "Potwierdzone przez oficjalną stronę marki: {site}"}


# Cards per page: multiples of 12, so the grid's 1, 2, 3 or 4 columns always end in a full row.
SHOW_STEPS = (24, 48, 96)
SHOW = {"en": "Show {n}", "nl": "Toon {n}", "de": "{n} anzeigen", "fr": "Afficher {n}", "es": "Mostrar {n}",
        "it": "Mostra {n}", "pt": "Mostrar {n}", "pl": "Pokaż {n}"}
PAGER = {"en": ("Previous", "Next", "Pages"), "nl": ("Vorige", "Volgende", "Pagina's"), "de": ("Zurück", "Weiter", "Seiten"),
         "fr": ("Précédent", "Suivant", "Pages"), "es": ("Anterior", "Siguiente", "Páginas"),
         "it": ("Precedente", "Successiva", "Pagine"), "pt": ("Anterior", "Seguinte", "Páginas"),
         "pl": ("Poprzednia", "Następna", "Strony")}


def db_link(lang, show, page, q=""):
    """/database with only the settings that differ from the defaults (and the search words, if any)."""
    parts = [f"q={urllib.parse.quote_plus(q)}" if q else "", f"show={show}" if show != SHOW_STEPS[0] else "",
             f"page={page}" if page > 1 else ""]
    qs = "&amp;".join(x for x in parts if x)
    return P(lang, "/database") + (f"?{qs}" if qs else "") + "#perfumes"


def matches(p, words, lang):
    """True when every search word starts a word of the perfume's brand, name or one of its notes (in English or
    the page's language): "tom", "vanil", "stronger with" all find what you'd expect."""
    notes = " ".join(f'{n.get("en") or ""} {note_name(n["en"], lang) if n.get("en") else n["name"]}'
                     for tier in p["notes"].values() for n in tier if n["confirmed"])
    hay = " " + catalog.plain(f'{p["brand"]} {p["name"]} {notes}')
    return all(f" {w}" in hay for w in words)


def pager(lang, show, page, pages, q=""):
    """Page numbers under the cards: previous, 1 … around the current page … last, next (links, no script)."""
    if pages <= 1:
        return ""
    prev_t, next_t, label = PAGER[lang]
    nums = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    out, last = [], 0
    for n in nums:
        if n - last > 1:
            out.append('<span class="gap">…</span>')
        out.append(f'<span class="cur" aria-current="page">{n}</span>' if n == page else f'<a href="{db_link(lang, show, n, q)}">{n}</a>')
        last = n
    prev = f'<a class="step" href="{db_link(lang, show, page - 1, q)}" rel="prev">← {prev_t}</a>' if page > 1 else ""
    nxt = f'<a class="step" href="{db_link(lang, show, page + 1, q)}" rel="next">{next_t} →</a>' if page < pages else ""
    return f'<nav class="pager" aria-label="{label}">{prev}{"".join(out)}{nxt}</nav>'


def database_page(con, prices=None, lang="en", show=24, page=1, q=""):
    t = T[lang]
    idx = index(con)
    s = catalog.stats(con)
    shops = con.execute("SELECT COUNT(DISTINCT shop) FROM reports").fetchone()[0] if _has(con, "reports") else 0
    show = show if show in SHOW_STEPS else SHOW_STEPS[0]
    q = " ".join(str(q or "").split())[:100]
    words = catalog.plain(q).split()
    found = [p for p in idx["perfumes"] if matches(p, words, lang)] if words else idx["perfumes"]
    pages = max(1, -(-len(found) // show))
    page = min(max(1, page), pages)
    cards = "".join(card(con, p, prices, lang) for p in found[(page - 1) * show:page * show])
    empty = f'<p class="nomatch">{t["noMatch"]}</p>' if not found else ""
    hidden = f'<input type="hidden" name="show" value="{show}">' if show != SHOW_STEPS[0] else ""
    listsearch = search_form(lang, "listsearch", P(lang, "/database"), q, hidden)
    # How many cards to show, as a menu of links (the pages have no script), like the language menu.
    showsel = (f'<details class="langsel showsel"><summary>{SHOW[lang].format(n=show)}</summary><ul>'
               + "".join(f'<li><a href="{db_link(lang, n, 1, q)}"'
                         f'{" aria-current=" + chr(34) + "true" + chr(34) if n == show else ""}>{SHOW[lang].format(n=n)}</a></li>'
                         for n in SHOW_STEPS) + "</ul></details>")
    brands = "".join(f'<li><a href="{P(lang, brand_path(b["name"]))}">{e(b["name"])}<small>{len(b["perfumes"])}</small></a></li>'
                     for b in sorted(idx["brands"].values(), key=lambda b: catalog.plain(b["name"])))
    notes = "".join(f'<li><a href="{P(lang, note_path(k))}">{e(note_name(k, lang))}<small>{len(v["perfumes"])}</small></a></li>'
                    for k, v in sorted(idx["notes"].items(), key=lambda kv: (-len(kv[1]["perfumes"]), kv[0]))[:16])
    body = f"""<section class="hero dbhero">
<h1>{t["dbH1"]}</h1>
<p class="lead">{t["dbLead"]}</p>
</section>
<section class="part first" id="perfumes"><div class="parthead"><h2>{t["withConfirmed"]}</h2>{showsel}</div>
{listsearch}
<div id="results"><div class="cards">{cards}</div>{empty}{pager(lang, show, page, pages, q)}</div>
</section>
<section class="part"><div class="stats">
<div><b>{num(s["perfumes"], lang)}</b><span>{t["statPerfumes"]}</span></div>
<div><b>{num(s["brands"], lang)}</b><span>{t["statBrands"]}</span></div>
<div class="hl"><b>{num(len(idx["perfumes"]), lang)}</b><span>{t["statConfirmed"]}</span></div>
<div><b>{num(shops, lang)}</b><span>{t["statShops"]}</span></div>
</div>
<p class="asof">{t["counted"].format(day=e(day(date.today().isoformat(), lang)))}</p></section>
<section class="part how"><h2>{t["howH"]}</h2>
<p class="intro">{t["howIntro"]}</p>
<ol class="steps">
<li><h3>{t["step1T"]}</h3><p>{t["step1D"]}</p></li>
<li><h3>{t["step2T"]}</h3><p>{t["step2D"]}</p></li>
<li><h3>{t["step3T"]}</h3><p>{t["step3D"]}</p></li>
</ol></section>
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
    # A search result (?q=) is the same page filtered: not a page of its own for search engines.
    return frame(lang, t["dbTitle"], t["dbDesc"], "/database", body, noindex=bool(q), jsonld=None if q else ld,
                 search=False, script=True)


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


def route(con, path, query, prices, voter=None):
    """(status, html or None, redirect target or None) for a page path, in either language."""
    lang = "en"
    m = re.match(r"/([a-z]{2})(?=/|$)", path)
    if m and m.group(1) in LANGS and m.group(1) != "en":
        lang, path = m.group(1), path[3:] or "/"
    state = (urllib.parse.parse_qs(query).get("vote") or [None])[0]
    m = re.fullmatch(r"/perfume/([0-9a-f]{12})/rate", path)
    if m:
        r = rate_page(con, m.group(1), lang, state, voter)
        if not r:
            return 404, not_found(lang), None
        return (301, None, P(lang, r[0])) if r[0] else (200, r[1], None)
    if path in ("/", ""):
        return 301, None, P(lang, "/database")
    if path in ("/database", "/database/"):
        qs = urllib.parse.parse_qs(query)

        def number(k, default):
            try:
                return int((qs.get(k) or [default])[0])
            except ValueError:
                return default
        return 200, database_page(con, prices, lang, number("show", SHOW_STEPS[0]), number("page", 1),
                                  (qs.get("q") or [""])[0]), None
    if path == "/database/search":
        q = (urllib.parse.parse_qs(query).get("q") or [""])[0]
        return 200, search_page(con, q, lang), None
    if path in ("/notes", "/notes/"):
        return 200, notes_page(con, lang), None
    m = re.fullmatch(r"/perfume/([0-9a-f]{12})(?:-[a-z0-9-]*)?", path)
    if m and (r := perfume_page(con, m.group(1), prices, lang, state, voter)):
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
