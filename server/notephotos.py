"""Photos for the perfume notes, from Wikimedia Commons, with free licences only.

For each note that has a page (pages.index), the main image of its English Wikipedia article (the plant or material,
see TITLES) is looked up. It is kept only when it is on Wikimedia Commons under a free licence (public domain, CC0,
CC BY or CC BY-SA); then a 400 px copy is stored under NOTE_DIR with its author, licence and file page, and the note
page shows that credit. Abstract and synthetic notes (amber, ambroxan, aldehydes…) and animal notes (musk, civet…) get
no photo: their article images would be misleading. Without a photo the page keeps its colour field.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

NOTE_DIR = os.environ.get("NOTE_IMG_DIR", os.path.join(os.path.dirname(os.environ.get("DB_PATH", "/data/prices.db")), "notes"))
USER_AGENT = "FragranceNotes/1.4 (https://fragrancenotes.app; support@fragrancenotes.app)"
IMG_MAX = 800_000
RECHECK = 7 * 86400   # a note without a free photo is tried again after a week (new uploads, the fallbacks)
FREE = re.compile(r"^(?:cc0|public domain|pd(?:\b|-)|cc by(?:-sa)?(?! ?-?n[cd]))", re.I)   # never NC or ND

# The Wikipedia article of the plant or material, when it isn't simply the note's own name.
TITLES = {
    "sage": "Salvia officinalis", "cedar": "Cedrus", "juniper": "Juniperus communis", "pink pepper": "Schinus molle",
    "violet leaf": "Viola odorata", "violet": "Viola odorata", "lavender": "Lavandula angustifolia",
    "chestnut": "Castanea sativa", "glazed chestnut": "Marron glacé", "iris": "Orris root", "oud": "Agarwood",
    "vetiver": "Chrysopogon zizanioides", "bergamot": "Bergamot orange", "mandarin": "Mandarin orange",
    "orange blossom": "Orange blossom", "tuberose": "Polianthes tuberosa", "rose": "Rose", "pepper": "Black pepper",
    "black pepper": "Black pepper", "tonka bean": "Tonka bean", "bourbon vanilla": "Vanilla", "guaiac wood": "Guaiacum",
    "amberwood": "Cedrus atlantica", "orange": "Orange (fruit)", "lemon": "Lemon", "apple": "Apple", "pear": "Pear",
    "cherry": "Cherry", "sour cherry": "Prunus cerasus", "blackcurrant": "Blackcurrant", "plum": "Plum",
    "tea": "Tea", "coffee": "Coffee bean", "cocoa": "Cocoa bean", "honey": "Honey", "leather": "Leather",
    "suede": "Suede", "tobacco": "Tobacco", "incense": "Frankincense", "frankincense": "Frankincense",
    "oakmoss": "Evernia prunastri", "moss": "Moss", "pine": "Pine", "fir": "Fir", "oak": "Oak", "birch": "Birch",
    "clary sage": "Salvia sclarea", "tarragon": "Tarragon", "bay leaf": "Bay leaf", "fig": "Common fig",
    "blood orange": "Blood orange", "bitter orange": "Bitter orange", "blood mandarin": "Mandarin orange",
    "lime": "Lime (fruit)", "red berries": "Redcurrant", "berries": "Berry", "water lily": "Nymphaeaceae", "lily": "Lilium",
    "lily of the valley": "Convallaria majalis", "olive tree": "Olive", "rosewood": "Dalbergia", "ebony": "Ebony",
    "mahogany": "Mahogany", "salt": "Sea salt", "maple syrup": "Maple syrup", "sugar": "Sugar", "milk": "Milk",
    "cream": "Cream", "rum": "Rum", "wine": "Wine", "hay": "Hay", "grass": "Poaceae", "praline": "Praline (nut confection)",
    "caviar": "Caviar", "monoi": "Monoi oil", "davana": "Artemisia pallens", "labdanum": "Labdanum",
    # Accords and families with a photo that fits without misleading (not amber: that would be fossil amber).
    "caramel": "Caramel", "smoke": "Smoke", "spicy": "Spice", "woody": "Wood", "aquatic": "Breaking wave", "marine": "Breaking wave",
    "ambergris": "Ambergris", "elemi": "Canarium luzonicum",
    "benzoin": "Benzoin resin", "heliotrope": "Heliotropium arborescens", "cypress": "Cupressus sempervirens",
    "wormwood": "Artemisia absinthium", "coriander": "Coriander", "apricot": "Prunus armeniaca",
}
# A Commons file chosen by hand, when the article's main image doesn't work as a small square (an old botanical
# drawing, a landscape). Changing an entry here replaces the stored photo on the next refresh.
FILES = {
    "lavender": "Lavandula angustifolia in Sedovo 1.jpg", "lavandin": "DSC05621 - Lavandin (38797971360).jpg",
    "violet leaf": "Viola odorata sl20.jpg", "suede": "Modern Suede Jacket.jpg",
    "vetiver": "Vetiveria zizanoides dsc07810.jpg",   # bundles of the roots; the old photo had a person in it
    "tonka bean": "Tonka Beans.jpg", "cedar": "Cedrus libani cone, Sète cf01.jpg", "chestnut": "Chestnuts roasted.jpg",
    "apple": "Apples in basket 2018 G1.jpg", "mint": "Mint leaves (Mentha spicata).jpg", "peppermint": "Peppermint Plant.jpg",
    "ginger": "Ginger Root.jpg", "pepper": "Black Pepper IMG 4866 - 02.jpg", "black pepper": "Black Pepper IMG 4866 - 02.jpg",
    "white pepper": "Pimienta blanca (Piper nigrum), 2020-06-12, DD 01-19 FS.jpg", "clove": "Clove close up.jpg",
    "caraway": "Kümmel 2012-07-08-9523.jpg", "fig": "Ficus carica whole fruits and fruit cut open.jpg",
    "jasmine sambac": "Jasminum sambac flower.jpg", "date": "Fruits of date tree.jpg",
    "coconut": "Raw and freshly cut coconut (27814).jpg", "neroli": "Orange Blossom.JPG",
    "mineral": "Beach rocks and pebbles.jpg",
}
# The article's main image is sometimes an old botanical drawing or engraving (Köhler's Medizinal-Pflanzen, 1887).
# As a small square that's a blur of lines: rather no photo (the note's colour) than that.
DRAWING = re.compile(r"k[öo]hler|medizinal|britannica|engraving|illustration|\bNGM\b|\b1[5-8]\d\d\b|\bL\.?,", re.I)
# No photo: abstract accords, synthetics, animal materials and descriptions.
SKIP = {"amber", "ambroxan", "amberever", "cinnamon liqueur", "iso e super", "hedione", "cashmeran", "aldehydes", "musk", "white musk",
        "civet", "castoreum", "ozonic", "solar notes", "resin", "toffee",
        "sweet", "oriental", "aromatic", "floral", "fruity", "powdery", "fresh", "citrus",
        "green", "gourmand", "chypre", "fougere", "musky", "cypriol"}


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS note_images (
        key TEXT PRIMARY KEY, file TEXT, title TEXT, artist TEXT, license TEXT, license_url TEXT, page TEXT,
        checked INTEGER NOT NULL)""")


def slug(key):
    return "-".join(key.split())


def _get(url, opener, limit=400_000):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=20) as r:
        return r.read(limit)


def plain_text(s, n=120):
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    return re.sub(r"\s+", " ", s).strip()[:n]


# Files in an article that are no photo of the thing itself: maps, diagrams, molecules, logos, herbarium sheets.
NOT_PHOTO = re.compile(r"\b(?:map|range|distribution|locator|structure|formula|molecule|skeletal|ball.and.stick|diagram|"
                       r"chart|graph|logo|icon|symbol|flag|coat of arms|stamp|herbarium|specimen|label|seal|"
                       r"cross.section|microscop|sem image|chromosome|plate|tafel|drawing|sketch|painting|poster|"
                       r"satellite|goes-?\d+|nasa|modis|\d+\.\d+[NSEW])\b", re.I)   # also satellite views ("Sea")
MAX_CANDIDATES = 6   # files tried per note and run, after the main image


def article_images(title, opener=urllib.request.urlopen):
    """(main image, [other images in the article]) of an English Wikipedia article, as file names."""
    q = urllib.parse.urlencode({"action": "query", "prop": "pageimages|images", "piprop": "name", "imlimit": 50,
                                "redirects": 1, "format": "json", "titles": title})
    pages = json.loads(_get(f"https://en.wikipedia.org/w/api.php?{q}", opener))["query"].get("pages", {})
    main = next((pg.get("pageimage") for pg in pages.values() if pg.get("pageimage")), None)
    others = [i["title"].split(":", 1)[1] for pg in pages.values() for i in pg.get("images", [])]
    return main, others


def usable(name):
    """A file name that can be a photo of the note: a JPG, no drawing, map, diagram or the like."""
    n = name.replace("_", " ")
    return bool(re.search(r"\.jpe?g$", n, re.I)) and not DRAWING.search(n) and not NOT_PHOTO.search(n)


def lookup(key, opener=urllib.request.urlopen):
    """(image bytes, info dict) for a note, or None when there's no free photo. The article's main image first; when
    that one isn't free or isn't a photo, the other photos in the article, in order."""
    if key in FILES:
        return commons_file(FILES[key], opener)
    title = TITLES.get(key, key[:1].upper() + key[1:])
    main, others = article_images(title, opener)
    plain_main = (main or "").replace("_", " ")
    names = ([main] if main and not DRAWING.search(plain_main) and not NOT_PHOTO.search(plain_main) else []) + \
            [n for n in others if n != main and usable(n)][:MAX_CANDIDATES]
    for name in names:
        found = commons_file(name, opener)
        if found:
            return found
    return None


def commons_info(names, opener=urllib.request.urlopen):
    """{file name: {license, artist, license_url, page, thumb}} for Commons files that have a free licence (for the
    perfume photo review list, see llm_review.job_photos). Up to 20 names per call."""
    q = urllib.parse.urlencode({"action": "query", "titles": "|".join("File:" + n for n in names[:20]), "prop": "imageinfo",
                                "iiprop": "url|extmetadata", "iiurlwidth": 400, "format": "json"})
    pages = json.loads(_get(f"https://commons.wikimedia.org/w/api.php?{q}", opener, 2_000_000))["query"].get("pages", {})
    out = {}
    for pg in pages.values():
        info = (pg.get("imageinfo") or [None])[0]
        if not info:
            continue
        meta = info.get("extmetadata") or {}
        lic = plain_text((meta.get("LicenseShortName") or {}).get("value"), 40)
        if FREE.match(lic) and info.get("thumburl"):
            out[pg["title"].removeprefix("File:")] = {
                "license": lic, "artist": plain_text((meta.get("Artist") or {}).get("value")) or "unknown",
                "license_url": (meta.get("LicenseUrl") or {}).get("value", ""), "page": info.get("descriptionurl", ""),
                "thumb": info["thumburl"]}
    return out


def commons_file(name, opener=urllib.request.urlopen):
    """(400 px image bytes, info) of one Commons file when it has a free licence, else None."""
    name = name.removeprefix("File:")
    q = urllib.parse.urlencode({"action": "query", "titles": "File:" + name, "prop": "imageinfo",
                                "iiprop": "url|extmetadata|mime", "iiurlwidth": 400, "format": "json"})
    pages = json.loads(_get(f"https://commons.wikimedia.org/w/api.php?{q}", opener))["query"].get("pages", {})
    info = next((pg.get("imageinfo", [None])[0] for pg in pages.values() if pg.get("imageinfo")), None)
    if not info:   # not on Commons: a local (often non-free) Wikipedia file
        return None
    meta = info.get("extmetadata") or {}
    lic = plain_text((meta.get("LicenseShortName") or {}).get("value"), 40)
    if not FREE.match(lic) or not info.get("thumburl"):   # the 400 px thumbnail is a JPG or PNG, whatever the original
        return None
    data = _get(info["thumburl"], opener, IMG_MAX + 1)
    if len(data) > IMG_MAX or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        return None
    return data, {"title": name, "artist": plain_text((meta.get("Artist") or {}).get("value")) or "unknown",
                  "license": lic, "license_url": (meta.get("LicenseUrl") or {}).get("value", ""),
                  "page": info.get("descriptionurl", "")}


def refresh(con, keys, opener=urllib.request.urlopen, now=None, limit=20):
    """Look up photos for these note keys (at most `limit` per run; each again only after RECHECK). Returns the
    number of new photos."""
    init(con)
    now = int(now or time.time())
    os.makedirs(NOTE_DIR, exist_ok=True)
    got = 0
    for key in sorted(keys):
        if limit <= 0:
            break
        if key in SKIP:
            continue
        r = con.execute("SELECT file, checked, title FROM note_images WHERE key=?", (key,)).fetchone()
        chosen = FILES.get(key)
        stale = bool(chosen and r and r[2] != chosen)   # a photo picked in FILES that isn't the stored one yet
        if r and not stale and (r[0] or now - r[1] < RECHECK):
            continue
        limit -= 1
        try:
            found = lookup(key, opener)
        except Exception as err:   # network trouble: try again next time
            print("note photo lookup failed:", key, type(err).__name__, flush=True)
            continue
        file, info = None, {}
        if not found and stale and r[0]:   # the chosen file isn't free or gone: keep the photo we have
            continue
        if found:
            data, info = found
            file = slug(key) + (".jpg" if data[:2] == b"\xff\xd8" else ".png")
            with open(os.path.join(NOTE_DIR, file), "wb") as f:
                f.write(data)
            got += 1
        con.execute("INSERT OR REPLACE INTO note_images (key, file, title, artist, license, license_url, page, checked) "
                    "VALUES (?,?,?,?,?,?,?,?)", (key, file, info.get("title"), info.get("artist"), info.get("license"),
                                                  info.get("license_url"), info.get("page"), now))
    con.commit()
    return got


def get(con, key):
    """{file, url, artist, license, license_url, page} of a note's stored photo, or None. The url carries the time the
    photo was stored, so a replaced photo (FILES) gets a new address and browsers don't keep showing the old one."""
    try:
        r = con.execute("SELECT file, artist, license, license_url, page, checked FROM note_images "
                        "WHERE key=? AND file IS NOT NULL", (key,)).fetchone()
    except Exception:
        return None
    if not r or not os.path.exists(os.path.join(NOTE_DIR, r[0])):
        return None
    d = dict(zip(("file", "artist", "license", "license_url", "page"), r[:5]))
    d["url"] = f"/photo/n/{r[0]}?v={int(r[5]):x}"
    return d


def image_file(name):
    """(bytes, content type) for GET /photo/n/<file>, or None."""
    if not re.fullmatch(r"[a-z0-9-]{1,60}\.(jpg|png)", name):
        return None
    path = os.path.join(NOTE_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read(), "image/jpeg" if name.endswith(".jpg") else "image/png"
