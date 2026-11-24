"""Import perfumes from Open Beauty Facts into the open perfume database.

Open Beauty Facts (openbeautyfacts.org) is a free, crowd-sourced database of cosmetics, published under
the Open Database License (ODbL). Its nightly export has, for many perfumes, the barcode, brand, product
name and bottle size. It has no notes, but it adds perfumes, barcodes and a second source to compare with.

Because we use it, the catalog that combines it is published under the ODbL too, and must credit it
(see ATTRIBUTION; catalog.py adds it to its answers).

The import streams the export line by line (it's large), keeps only perfumes, and replaces the table
`obf_products` in one go. app.obf_loop runs it once a week (OBF_EVERY).
"""
import gzip
import io
import json
import os
import re
import time
import urllib.request

URL = os.environ.get("OBF_URL", "https://static.openbeautyfacts.org/data/openbeautyfacts-products.jsonl.gz")
SOURCE = "openbeautyfacts.org"
ATTRIBUTION = ("Contains information from Open Beauty Facts (openbeautyfacts.org), "
               "made available under the Open Database License (ODbL).")
USER_AGENT = "FragranceNotes/1.3 (https://fragrancenotes.app; support@fragrancenotes.app)"

# Category tags that mark a perfume. The real export (checked 2026-11-24) has them in many languages and
# not always normalised ("nl:Herenparfum", "en:Women's perfumes", "en:Eau de parfum", "de:eau-de-parfum"),
# so tags are normalised first (see tag_key) and any language prefix is accepted. Only whole tags match,
# so "de:toilettenpapier" or "fr:shampooings-aux-extraits-naturels" never do.
PERFUME_TAG = re.compile(r"^[a-z]{2}:(?:perfumes?|parfums?|fragrances?|colognes?|perfume-cologne|"
                         r"eaux?-de-(?:parfum|toilette|cologne)|extraits?-de-parfum|"
                         r"(?:men|women|kids|unisex)(?:-s)?-(?:perfumes?|fragrances?)|"
                         r"heren-?parfum|dames-?parfum|unisex-?parfum)$")
GENDER_U = re.compile(r"unisex")
GENDER_F = re.compile(r"women|femmes?\b|for-her|dames|damen")
GENDER_M = re.compile(r"(?:^|[\s:-])men(?:-|\b)|hommes?\b|heren|herren|for-him")


def tag_key(t):
    """'en:Women's perfumes' -> 'en:women-s-perfumes', as Open Beauty Facts would normalise it."""
    return re.sub(r"[\s'’]+", "-", str(t).strip().lower())
CONC_TAGS = [("extrait", re.compile(r"extraits?-de-parfum")), ("edp", re.compile(r"eaux?-de-parfum")),
             ("edt", re.compile(r"eaux?-de-toilette")), ("edc", re.compile(r"eaux?-de-cologne|colognes?$"))]
CONC_WORDS = [("extrait", re.compile(r"\bextrait\b", re.I)),
              ("edp", re.compile(r"\beau de parfum\b|\bedp\b", re.I)),
              ("edt", re.compile(r"\beau de toilette\b|\bedt\b", re.I)),
              ("edc", re.compile(r"\beau de cologne\b|\bedc\b", re.I)),
              ("parfum", re.compile(r"\b(le )?parfum\s*$", re.I))]
STRIP = re.compile(r"\b(extrait de parfum|eau de parfum|eau de toilette|eau de cologne|edp|edt|edc|spray|vaporisateur|"
                   r"natural spray)\b|\b\d+(?:[.,]\d+)?\s?(?:ml|fl\.?\s?oz|oz)\b", re.I)
BOTTLES = [5, 7.5, 10, 15, 20, 30, 40, 50, 60, 75, 80, 90, 100, 110, 120, 125, 150, 175, 200, 250]
GTIN = re.compile(r"^\d{8}$|^\d{12,14}$")


def gtin_ok(g):
    if not GTIN.match(g):
        return False
    d = [int(x) for x in g]
    check = d.pop()
    return (10 - sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(reversed(d))) % 10) % 10 == check


def ml_of(quantity):
    q = str(quantity or "").lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", q)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:fl\.?\s*)?oz\b", q)
    if m:   # US labels round the ounces: 3.4 oz is a 100 ml bottle
        ml = float(m.group(1)) * 29.5735
        near = min(BOTTLES, key=lambda b: abs(b - ml))
        return near if abs(near - ml) / near <= 0.04 else round(ml)
    m = re.search(r"(\d+(?:\.\d+)?)\s*cl\b", q)
    return float(m.group(1)) * 10 if m else None


def product(p):
    """One perfume row from an export line, or None when it isn't a usable perfume."""
    tags = [tag_key(t) for t in p.get("categories_tags") or []]
    if not any(PERFUME_TAG.match(t) for t in tags):
        return None
    code = str(p.get("code") or "")
    if not gtin_ok(code):
        return None
    lang = (p.get("lang") or p.get("lc") or "")[:2]
    raw_name = p.get("product_name") or p.get(f"product_name_{lang}") or p.get("product_name_en") or next(
        (v for k, v in p.items() if k.startswith("product_name_") and isinstance(v, str) and v.strip()), "")
    import catalog   # here, not at the top: catalog imports this module
    # "brands" often lists the parent company first ("L'Oréal, Giorgio Armani"); prefer the house.
    brand = catalog.pick_brand(str(p.get("brands") or "").split(","), raw_name)
    if not raw_name or not brand:
        return None
    joined = " ".join(tags)
    conc = next((c for c, rx in CONC_TAGS if rx.search(joined)), None) or \
        next((c for c, rx in CONC_WORDS if rx.search(raw_name)), "")
    f, m = bool(GENDER_F.search(joined)), bool(GENDER_M.search(joined))
    gender = "u" if GENDER_U.search(joined) or (f and m) else "f" if f else "m" if m else ""
    name = catalog.strip_brand(re.sub(r"\s+", " ", STRIP.sub(" ", raw_name)).strip(" -–,"), brand)
    if not name:
        return None
    ml = ml_of(p.get("quantity"))
    return {
        "code": code.zfill(13)[-13:] if len(code) <= 13 else code,
        "brand": brand[:80], "name": name[:120], "conc": conc, "gender": gender,
        "ml": ml if ml and 0 < ml <= 1000 else None, "lang": lang or None,
        "modified": int(p.get("last_modified_t") or 0),
    }


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS obf_products (
        code TEXT PRIMARY KEY, brand TEXT NOT NULL, name TEXT NOT NULL, conc TEXT NOT NULL, gender TEXT NOT NULL,
        ml REAL, lang TEXT, modified INTEGER NOT NULL)""")
    con.execute("CREATE TABLE IF NOT EXISTS obf_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)")


RETRY_AFTER = 86400   # after a failed import, wait at least a day before downloading again


def meta(con, k):
    r = con.execute("SELECT v FROM obf_meta WHERE k=?", (k,)).fetchone()
    return int(r[0]) if r else 0


def set_meta(con, k, v):
    with con:
        con.execute("INSERT OR REPLACE INTO obf_meta (k, v) VALUES (?, ?)", (k, str(int(v))))


def last_import(con):
    return meta(con, "imported")


def due(con, every, now=None):
    """True when the last good import is `every` seconds old and the last failure (if newer) a day old."""
    now = time.time() if now is None else now
    imported, failed = meta(con, "imported"), meta(con, "failed")
    return now - imported >= every and (failed <= imported or now - failed >= RETRY_AFTER)


def run(con, url=URL, opener=None):
    """Download the export and replace obf_products. Returns (lines read, perfumes kept).
    Every attempt is stored in obf_meta ('attempted'), a failure also as 'failed' (see due)."""
    set_meta(con, "attempted", time.time())
    try:
        return _run(con, url, opener)
    except Exception:
        set_meta(con, "failed", time.time())
        raise


def _run(con, url, opener):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    resp = (opener or urllib.request.urlopen)(req, timeout=120)
    rows, lines = {}, 0
    with resp, gzip.GzipFile(fileobj=resp) as gz:
        for line in io.TextIOWrapper(gz, encoding="utf-8", errors="replace"):
            lines += 1
            try:
                r = product(json.loads(line))
            except (ValueError, TypeError, AttributeError):
                continue
            if r and (r["code"] not in rows or r["modified"] > rows[r["code"]]["modified"]):
                rows[r["code"]] = r
    if lines and not rows:
        raise RuntimeError(f"read {lines} lines but found no perfumes; the export format may have changed")
    with con:
        con.execute("DELETE FROM obf_products")
        con.executemany("""INSERT INTO obf_products (code, brand, name, conc, gender, ml, lang, modified)
            VALUES (:code, :brand, :name, :conc, :gender, :ml, :lang, :modified)""", list(rows.values()))
        con.execute("INSERT OR REPLACE INTO obf_meta (k, v) VALUES ('imported', ?)", (str(int(time.time())),))
        con.execute("INSERT OR REPLACE INTO obf_meta (k, v) VALUES ('count', ?)", (str(len(rows)),))
    return lines, len(rows)


def as_facts(con):
    """The imported perfumes in the same shape as rows of the facts table, for catalog.build."""
    out = []
    for code, brand, name, conc, gender, ml, lang, modified in con.execute(
            "SELECT code, brand, name, conc, gender, ml, lang, modified FROM obf_products"):
        out.append({
            "install": "obf", "shop": SOURCE, "perfume_id": None, "brand": brand, "name": name, "conc": conc,
            "gender": gender, "lang": lang, "sizes": [ml] if ml else [], "gtins": [code],
            "notes": {"top": [], "heart": [], "base": []}, "families": [],
            "day": time.strftime("%Y-%m-%d", time.gmtime(modified or 0)),
        })
    return out
