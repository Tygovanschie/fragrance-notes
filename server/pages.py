"""Public web pages for the open perfume database: /database, /perfume/<id>-<slug>, /note/<slug>.

Only perfumes that are worth a page get one: at least PAGE_MIN_CONFIRMED notes confirmed by two or more
shops (catalog.CONFIRM_SHOPS). Everything else answers 404, so search engines never see near-empty pages.
A note gets a page once it is confirmed in at least one published perfume and has an English name.

What a page shows comes only from our own data: the catalog (shop facts + Open Beauty Facts), the
anonymous price reports (app.stats), reviewed note descriptions (note_texts.json, written by the local
model from a cited source and checked by hand, see llm_review.py) and bottle photos from Open Beauty Facts
(CC BY-SA, cached under IMG_DIR, see refresh_images). Nothing from Fragrantica, which is only linked to.

All values are escaped with html.escape. Links are root-relative, so the pages work on any host that
forwards these paths to the API; <link rel="canonical"> uses PAGES_BASE.
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
GENDER = {"m": "For men", "f": "For women", "u": "Unisex"}
CURRENCY = {"EUR": "€", "GBP": "£", "USD": "$", "CHF": "CHF ", "PLN": "zł ", "SEK": "kr ", "DKK": "kr "}
TIERS = (("top", "Top", "first minutes"), ("heart", "Heart", "first hours"), ("base", "Base", "the dry-down"))
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def load_texts(path=TEXTS_FILE):
    try:
        with open(path, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except FileNotFoundError:
        return {}


TEXTS = load_texts()
e = html.escape


# ---------- small helpers ----------

def slug(s):
    return "-".join(catalog.plain(s).split())[:80] or "perfume"


def perfume_path(p):
    return f"/perfume/{p['id']}-{slug(p['brand'] + ' ' + p['name'])}"


def note_path(key):
    return "/note/" + "-".join(key.split())


def nice(key):
    return key[:1].upper() + key[1:]


def day(s):
    try:
        d = date.fromisoformat(s)
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    except (TypeError, ValueError):
        return ""


def money(v, cur):
    sym = CURRENCY.get(cur, (cur or "") + " ")
    return f"{sym}{v:,.2f}"


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
        for tier, _, _ in TIERS:
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
    idx = {"perfumes": perfumes, "byId": {p["id"]: p for p in perfumes}, "notes": notes}
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
"""


def frame(title, desc, path, body, noindex=False, extra_head=""):
    robots = '<meta name="robots" content="noindex">' if noindex else f'<link rel="canonical" href="{e(BASE + path)}">'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
{robots}
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{SITE}img/og.png">
<link rel="icon" href="{SITE}img/icon.png">
<link rel="preconnect" href="https://fonts.bunny.net">
<link rel="stylesheet" href="https://fonts.bunny.net/css?family=bricolage-grotesque:600,700,750,800|figtree:400,500,600&display=swap">
<link rel="stylesheet" href="/assets/pages.css?v={CSS_VERSION}">
{extra_head}</head>
<body>
<header class="top"><div class="wrap">
<a class="brand" href="{SITE}"><img src="{SITE}img/icon.png" alt="">Fragrance Notes</a>
<a class="btn small" href="{STORE}">Get the extension</a>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">
<p>From the open Fragrance Notes perfume database: what perfume shops show on their own pages, shared anonymously by
users, and <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>. Available under the
<a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Photos from Open Beauty Facts (CC BY-SA).</p>
<p>Not affiliated with the brands or shops named. Prices change; check the shop.</p>
<p><a href="/database">The database</a> · <a href="{SITE}privacy.html">Privacy</a> · <a href="https://github.com/Tygovanschie/fragrance-notes">Source</a></p>
</div></footer>
</body>
</html>"""


CSS_VERSION = hashlib.sha1(CSS.encode()).hexdigest()[:8]


def back():
    return '<a class="back" href="/database">← Back to the database</a>'


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


# ---------- /perfume/<id>-<slug> ----------

def perfume_page(con, pid, prices=None):
    """(path, html) for a published perfume; (path, None) when the slug differs (redirect); None if no page."""
    idx = index(con)
    p = idx["byId"].get(pid)
    if not p:
        return None
    path = perfume_path(p)
    linkable = idx["notes"]
    conf = sum(n["confirmed"] for t in p["notes"].values() for n in t)
    tags = [CONC.get(p.get("conc") or "", "")] + [GENDER.get(p.get("gender") or "", "")]
    sizes = p.get("sizes") or []
    if sizes:
        tags.append(ml(sizes[0]) if len(sizes) == 1 else f"{sizes[0]:g} – {sizes[-1]:g} ml")
    ph = photo(con, p)
    photo_html = (f'<figure class="photo"><img src="/photo/{e(ph[0])}" alt="Bottle of {e(p["name"])} by {e(p["brand"])}" width="400" height="400">'
                  f'<figcaption>Photo: <a href="https://world.openbeautyfacts.org/product/{e(ph[1])}">Open Beauty Facts</a>, CC BY-SA</figcaption></figure>') if ph else ""
    full = f"{p['name']} by {p['brand']}"

    tiers = []
    for tier, label, hint in TIERS:
        chips = []
        for n in p["notes"][tier]:
            name = nice(n["en"]) if n.get("en") else n["name"]
            cls = "note ok" if n["confirmed"] else "note one"
            extra = "" if n["confirmed"] else f' <small>{n["shops"]} shop{"s" if n["shops"] != 1 else ""}</small>'
            if n.get("en") in linkable:
                chips.append(f'<li><a class="{cls}" href="{note_path(n["en"])}">{e(name)}{extra}</a></li>')
            else:
                chips.append(f'<li><span class="{cls}">{e(name)}{extra}</span></li>')
        if chips:
            tiers.append(f'<div class="tier"><h3>{label}<small>{hint}</small></h3><ul class="notes">{"".join(chips)}</ul></div>')

    price_html = ""
    st = prices(p["fragrantica"][0]) if prices and p.get("fragrantica") else None
    rows = best_prices(st)
    if rows:
        cur = st.get("currency")
        trs = "".join(
            f'<tr><td>{ml(m)}</td><td class="num"><span class="low">{e(money(low, cur))}</span></td><td>{e(shop)}</td>'
            f'<td class="num hide-sm">{e(money(low / m, cur))}</td>'
            f'<td class="num hide-sm muted">{"1 shop" if n == 1 else e(money(low, cur).split(".")[0] + " – " + f"{high:,.0f}")}</td></tr>'
            for m, low, shop, high, n, _ in rows)
        m, _, _, _, _, lows = max(rows, key=lambda r: (r[4], r[0] == 100, r[0]))
        top = max(lows.values())
        bars = "".join(
            f'<div class="bar{" best" if i == 0 else ""}"><span>{e(s)}</span><span class="track"><span class="fill" style="width:{v / top * 100:.0f}%"></span></span>'
            f'<span class="eur">{e(money(v, cur))}</span></div>'
            for i, (s, v) in enumerate(sorted(lows.items(), key=lambda kv: kv[1]))) if len(lows) > 1 else ""
        shops_n = len({s for r in rows for s in r[5]})
        price_html = f"""<section class="card" aria-labelledby="price-h"><h2 id="price-h">Prices</h2>
<p class="sub">Lowest price per size in the last {st.get("days", 30)} days at {shops_n} shop{"s" if shops_n != 1 else ""}, shared anonymously by Fragrance Notes users.</p>
<table><thead><tr><th>Size</th><th class="num">Lowest</th><th>At</th><th class="num hide-sm">Per ml</th><th class="num hide-sm">Range</th></tr></thead>
<tbody>{trs}</tbody></table>
{f'<div class="bars"><h3>{ml(m)} at each shop</h3>{bars}</div>' if bars else ""}</section>"""

    fams = [nice(f["key"]) if f["key"] in catalog.NOTE_EN else f["name"] for f in p.get("families", [])
            if f["confirmed"] or f["key"] in catalog.NOTE_EN]
    srcs = ["Open Beauty Facts" if s == obf.SOURCE else s for s in p.get("shopList", [])]
    facts = []
    if fams:
        facts.append(("Fragrance family", e(" · ".join(fams))))
    if sizes:
        facts.append(("Sizes", e(", ".join(f"{s:g}" for s in sizes) + " ml")))
    facts.append(("Described by", e(", ".join(srcs))))
    if p.get("gtins"):
        facts.append(("Barcodes (EAN)", f'<span class="codes">{"<br>".join(e(g) for g in p["gtins"][:8])}</span>'))
    q = urllib.parse.quote(f"{p['brand']} {p['name']}")
    facts.append(("More about it", f'Accords, reviews and votes on <a href="https://www.fragrantica.com/search/?query={q}" rel="nofollow">Fragrantica ↗</a>'))
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)

    body = f"""{back()}
<section class="head{'' if ph else ' nophoto'}">{photo_html}<div>
<p class="house">{e(p["brand"])}</p>
<h1>{e(p["name"])}</h1>
<ul class="tags">{"".join(f"<li>{e(t)}</li>" for t in tags if t)}</ul>
<p class="trust"><span><b>{p["shops"]} source{"s" if p["shops"] != 1 else ""}</b> describe it</span><span><b>{conf} notes</b> confirmed</span><span>Last seen <b>{e(day(p.get("lastSeen")))}</b></span></p>
</div></section>
<div class="grid"><div>
<section class="card" aria-labelledby="notes-h"><h2 id="notes-h">Notes</h2>
<p class="sub">As the shops describe it. A note gets a ✓ once two different shops list it.</p>
{"".join(tiers)}
<div class="legend"><span><i class="k-ok"></i>Confirmed by 2 or more shops</span><span><i class="k-one"></i>Named by one shop so far</span></div>
</section>
{price_html}
</div><aside>
<section class="card" aria-label="Details"><dl class="facts">{facts_html}</dl></section>
<section class="card help"><h2>See this on every shop page</h2>
<p>The free Fragrance Notes extension shows the notes, accords and prices right on the product page. Turn on “Help other perfume lovers” and the shops you visit help confirm these notes.</p>
<a class="btn" href="{STORE}">Get Fragrance Notes</a></section>
</aside></div>"""
    confirmed_names = [nice(n["en"]) if n.get("en") else n["name"] for t in p["notes"].values() for n in t if n["confirmed"]]
    desc = f"Notes of {full} ({CONC.get(p.get('conc') or '', 'perfume')}), confirmed by several shops: {', '.join(confirmed_names[:6])}."
    return path, frame(f"{full} – notes and prices | Fragrance Notes", desc, path, body)


# ---------- /note/<slug> ----------

def swatch(key):
    """A soft colour field per note (no photo): three warm circles on a gradient, from a hash of the name."""
    h = hashlib.sha1(key.encode()).digest()
    hue = h[0] * 360 // 256
    c = lambda i, s, l: f"hsl({(hue + h[i] % 40 - 20) % 360} {s}% {l}%)"
    return (f"background:radial-gradient(circle at 25% 35%,{c(1, 45, 78)} 0 18%,transparent 19%),"
            f"radial-gradient(circle at 62% 60%,{c(2, 40, 55)} 0 22%,transparent 23%),"
            f"radial-gradient(circle at 85% 25%,{c(3, 45, 35)} 0 12%,transparent 13%),"
            f"linear-gradient(120deg,{c(4, 50, 90)},{c(5, 35, 62)} 60%,{c(6, 40, 40)})")


def note_page(con, slug_):
    key = " ".join(slug_.split("-"))
    idx = index(con)
    x = idx["notes"].get(key)
    if not x:
        return None
    path = note_path(key)
    name = nice(key)
    aka = [n for n, _ in x["names"].most_common() if catalog.plain(n) != key][:6]
    text = TEXTS.get(key)
    if text:
        src = text.get("source", "")
        about = f"""<section class="card"><h2>What it smells like</h2><p>{e(text["smell"])}</p>
<h2 style="margin-top:26px">Where it comes from</h2><p>{e(text["origin"])}</p>
<p class="src">Written by our own AI model from the source text, checked by hand before it went online.
{f'Source: <a href="{e(src)}" rel="nofollow">{e(text.get("sourceName", "source"))}</a> ({e(text.get("license", ""))}).' if src else ""}</p></section>"""
    else:
        about = ""
    items = []
    for p, shops in sorted(x["perfumes"], key=lambda t: (-t[1], t[0]["name"])):
        im = img_tag(con, p, size=56) or "<i></i>"
        items.append(f'<li><a href="{perfume_path(p)}">{im}<span><b>{e(p["name"])}</b>'
                     f'<small>{e(p["brand"])} · {e(CONC.get(p.get("conc") or "", "perfume"))} · confirmed by {shops} shops</small></span></a></li>')
    total = sum(x["tiers"].values()) or 1
    where = "".join(f'<div class="{"on" if x["tiers"][t] * 2 >= total and x["tiers"][t] else ""}"><b>{label}</b>'
                    f'{x["tiers"][t]} perfume{"s" if x["tiers"][t] != 1 else ""}</div>' for t, label, _ in TIERS)
    pairs = [k for k, _ in x["pairs"].most_common(8) if k in idx["notes"]]
    pairs_html = (f'<section class="card"><h2>Often paired with</h2><ul class="pairs">'
                  f'{"".join(f"<li><a href={chr(34)}{note_path(k)}{chr(34)}>{e(nice(k))}</a></li>" for k in pairs)}</ul></section>') if pairs else ""
    body = f"""{back()}
<section class="head" style="grid-template-columns:1fr 340px;align-items:end"><div>
<p class="kind">Perfume note</p><h1>{e(name)}</h1>
{f'<p class="muted" style="font-size:1rem">Shops also write: {", ".join(f"<b>{e(a)}</b>" for a in aka)}</p>' if aka else ""}
</div><div class="swatch" style="{swatch(key)}" aria-hidden="true"></div></section>
<div class="grid"><div>
{about}
<section class="card"><h2>Perfumes with {e(key)}</h2><ul class="plist">{"".join(items)}</ul></section>
</div><aside>
<section class="card"><h2>Where it sits</h2><div class="where">{where}</div></section>
{pairs_html}
</aside></div>"""
    desc = (text["smell"][:150] if text else f"Perfumes with a confirmed {key} note in the open Fragrance Notes database.")
    return path, frame(f"{name} – what it smells like, perfumes with this note | Fragrance Notes", desc, path, body)


# ---------- /database and /database/search ----------

def card(con, p, prices=None):
    conf = [nice(n["en"]) if n.get("en") else n["name"] for t in p["notes"].values() for n in t if n["confirmed"]]
    tail = ""
    st = prices(p["fragrantica"][0]) if prices and p.get("fragrantica") else None
    rows = best_prices(st)
    if rows:
        m, low, *_ = min(rows, key=lambda r: (abs(r[0] - 100), r[0]))
        tail = f'<p class="p"><span>{ml(m)} from</span><b>{e(money(low, st.get("currency")))}</b></p>'
    bits = [CONC.get(p.get("conc") or "", ""), (GENDER.get(p.get("gender") or "", "") or "").lower(), f'{p["shops"]} sources']
    return (f'<a class="pcard" href="{perfume_path(p)}">{img_tag(con, p, "img", 84)}<p class="h">{e(p["brand"])}</p>'
            f'<p class="n">{e(p["name"])}</p><p class="c">{e(" · ".join(b for b in bits if b))}</p>'
            f'<ul>{"".join(f"<li>{e(c)}</li>" for c in conf[:8])}</ul>{tail}</a>')


def database_page(con, prices=None):
    idx = index(con)
    s = catalog.stats(con)
    shops = con.execute("SELECT COUNT(DISTINCT shop) FROM reports").fetchone()[0] if _has(con, "reports") else 0
    cards = "".join(card(con, p, prices) for p in idx["perfumes"][:24])
    body = f"""<section class="hero">
<h1>An open perfume database, built while you shop</h1>
<p class="lead">Every perfume shop describes its perfumes a little differently. When people who use Fragrance Notes visit a shop page, it can share what that shop says. Where shops agree, a note gets confirmed. Everything is free to use.</p>
<form class="search" role="search" action="/database/search"><input type="search" name="q" placeholder="Search a perfume or brand" aria-label="Search a perfume or brand" required maxlength="100"><button class="btn" type="submit">Search</button></form>
</section>
<div class="stats">
<div><b>{s["perfumes"]:,}</b><span>perfumes</span></div>
<div><b>{s["brands"]:,}</b><span>brands</span></div>
<div class="hl"><b>{s["withConfirmedNotes"]:,}</b><span>with confirmed notes</span></div>
<div><b>{shops:,}</b><span>shops with prices</span></div>
</div>
<p class="asof">Counted {e(day(date.today().isoformat()))}. It grows with every shop page people visit.</p>
<section class="part"><h2>How a note gets confirmed</h2>
<p class="intro">Nothing here is copied from other sites. It's only what perfume shops show on their own product pages, collected by people who turned sharing on.</p>
<ol class="steps">
<li><h3>You visit a perfume page</h3><p>On any of 300+ supported shops, as you normally would. Sharing is off until you turn on “Help other perfume lovers”.</p></li>
<li><h3>The shop's facts are shared</h3><p>The notes, family, sizes, barcode and price that the shop itself shows. Never who you are or what you buy.</p></li>
<li><h3>Shops agree, it's confirmed</h3><p>Once two different shops list the same note, it gets <span class="chip">confirmed</span> and shows up in the extension and on this site.</p></li>
</ol></section>
<section class="part"><h2>Perfumes with confirmed notes</h2>
<p class="intro">A perfume gets its own page once at least {PAGE_MIN_CONFIRMED} of its notes are confirmed.</p>
<div class="cards">{cards}<div class="pcard soon"><div><b>Yours could be next</b>Visit a perfume at two shops with sharing on.</div></div></div>
</section>
<section class="open"><div><h2>Open data</h2>
<p>The database is published under the <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>. Use it in your own app, research or site, as long as you name the source and share improvements under the same licence.</p>
<p>It also includes perfume data from <a href="https://world.openbeautyfacts.org/">Open Beauty Facts</a>.</p></div>
<div><ul><li>Search: <code>api.fragrancenotes.app/catalog/search?q=</code></li><li>One perfume: <code>api.fragrancenotes.app/catalog/perfume/{{id}}</code></li>
<li>Totals: <code>api.fragrancenotes.app/catalog/stats</code></li></ul>
<a class="btn" href="{STORE}">Help it grow: get the extension</a></div></section>"""
    return frame("The open perfume database | Fragrance Notes",
                 "An open perfume database built by shoppers: notes confirmed by several shops, sizes, barcodes and anonymous prices. Free under the Open Database License.",
                 "/database", body)


def search_page(con, q):
    q = (q or "")[:100]
    idx = index(con)
    words = catalog.plain(q).split()
    hits = [p for p in idx["perfumes"] if words and all(f" {w}" in " " + catalog.plain(p["brand"] + " " + p["name"]) for w in words)]
    notes = [k for k in idx["notes"] if words and all(w in k for w in words)]
    others = 0
    if words:
        others = sum(1 for r in catalog.search(con, q) if r["id"] not in idx["byId"])
    lis = "".join(f'<li><a href="{perfume_path(p)}"><b>{e(p["name"])}</b></a> <span class="muted">{e(p["brand"])} · {e(CONC.get(p.get("conc") or "", "perfume"))}</span></li>' for p in hits)
    lis += "".join(f'<li><a href="{note_path(k)}"><b>{e(nice(k))}</b></a> <span class="muted">perfume note</span></li>' for k in notes)
    none = "" if lis else "<p>No perfume page matches that yet.</p>"
    more = (f'<p class="muted">{others} more perfume{"s" if others != 1 else ""} in the database match, but don\'t have enough confirmed notes for a page yet.</p>' if others else "")
    body = f"""{back()}<h1 style="font-size:clamp(2rem,4vw,3rem)">Search</h1>
<form class="search" role="search" action="/database/search" style="margin-bottom:28px"><input type="search" name="q" value="{e(q)}" aria-label="Search a perfume or brand" required maxlength="100"><button class="btn" type="submit">Search</button></form>
<section class="card"><ul class="results">{lis}</ul>{none}{more}</section>"""
    return frame(f"Search: {q} | Fragrance Notes", "Search the open perfume database.", "/database/search", body, noindex=True)


def not_found():
    body = f"""{back()}<h1>Not here (yet)</h1><p class="lead">This perfume or note has no page yet. A perfume gets one once
at least {PAGE_MIN_CONFIRMED} of its notes are confirmed by two different shops.</p>"""
    return frame("Not found | Fragrance Notes", "This page doesn't exist yet.", "/database", body, noindex=True)


def sitemap(con):
    idx = index(con)
    urls = ["/database"] + [perfume_path(p) for p in idx["perfumes"]] + [note_path(k) for k in sorted(idx["notes"])]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"<url><loc>{e(BASE + u)}</loc></url>\n" for u in urls) + "</urlset>\n")


def _has(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
