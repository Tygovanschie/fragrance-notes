"""Fragrance Notes API: anonymous, crowd-sourced perfume prices and the open perfume database.

Python standard library only. Runs behind a Cloudflare Tunnel (api.fragrancenotes.app), which does TLS.

  POST /prices              {perfumeId, ml, price, currency, shop}   header X-Install-Id: <uuid4>
  GET  /prices/{perfumeId}  ?currency=EUR (optional; defaults to the most-reported one)
  POST /facts               product facts a shop shows (opt-in "Help build the open perfume database")
  GET  /facts/stats         how the collection is growing
  GET  /facts/mine          header X-Install-Id: what this install's shared facts helped confirm (popup)
  POST /shops/suggest       {domains: [...]} shops this install added itself (opt-in, domain only), for review
  GET  /catalog/stats       the combined open perfume database (see catalog.py; includes Open Beauty Facts, obf.py)
  GET  /catalog/search?q=   find perfumes in it
  GET  /catalog/perfume/{id}
  GET  /catalog/lookup?gtin=&brand=&name=&conc=&gender=   the perfume on a shop page (anonymous, query not logged)
  GET  /health
  GET  /maintenance/week   what the nightly job fixed and left for a person (maintenance.py), for the weekly email

  Web pages (pages.py), for fragrancenotes.app: /database, /database/search?q=, /perfume/{id}-{slug},
  /note/{slug}, /photo/{barcode}.jpg, /assets/pages.css, /sitemap.xml

Privacy: no IP addresses are stored or logged. The install id is a random UUID made by the
extension; only a salted hash of it is stored. Reports older than RETENTION_DAYS are deleted.
"""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import statistics
import threading
import time

import catalog
import maintenance
import regions
import pages
import notephotos
import votes
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

DB_PATH = os.environ.get("DB_PATH", "/data/prices.db")
SALT_PATH = os.environ.get("SALT_PATH", os.path.join(os.path.dirname(DB_PATH), "salt"))
SHOPS_FILE = os.environ.get("SHOPS_FILE", os.path.join(os.path.dirname(__file__), "shops.txt"))
PORT = int(os.environ.get("PORT", "8787"))
# Browsers only: CORS is not a security boundary, curl can post anyway (rate limits handle that).
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "chrome-extension://hhhiolpcmkdkegcmjmpglcnfolohldgc").split(",") if o.strip()}
# Firefox gives every install its own random moz-extension:// UUID, so those can't be listed one by one.
MOZ_ORIGIN_RE = re.compile(r"moz-extension://[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# Votes come from the form on a perfume page (pages.py, through the site's Worker): only that origin.
VOTE_ORIGINS = {o.strip() for o in os.environ.get("VOTE_ORIGINS", pages.BASE).split(",") if o.strip()}
VOTE_PATH = re.compile(r"(/[a-z]{2})?/perfume/([0-9a-f]{12})/vote")


def origin_ok(origin):
    return origin in ALLOWED_ORIGINS or bool(origin and MOZ_ORIGIN_RE.fullmatch(origin))


WINDOW_DAYS = 30          # stats cover the last 30 days
RETENTION_DAYS = 90       # rows older than this are deleted
MAX_BODY = 1024
MAX_FACTS_BODY = 4096
# Facts: a page sends one report, so far fewer per install than prices.
FACT_LIMITS = [(600, 30), (86400, 120)]
GLOBAL_FACT_LIMIT = (3600, 3000)
LIMITS = [(600, 60), (86400, 500)]   # per install: 60 reports / 10 min, 500 / day (a page sends up to 8 sizes)
GLOBAL_LIMIT = (3600, 5000)          # all installs together
# Outliers are never rejected or deleted, only left out when stats are calculated (on every GET):
# per size, a shop whose median per-ml price is below OUTLIER_LOW x or above OUTLIER_HIGH x the median
# of all shops' values is dropped, but only once the size has at least OUTLIER_MIN_SHOPS shops.
OUTLIER_LOW = float(os.environ.get("OUTLIER_LOW", "0.4"))
OUTLIER_HIGH = float(os.environ.get("OUTLIER_HIGH", "2.5"))
OUTLIER_MIN_SHOPS = 3
# Neighbouring sizes: every shop's per-ml price for a size is compared with the nearest smaller and the
# nearest larger size of the same perfume that OTHER shops sell (median of those shops' values).
# Bigger bottles are normally a bit cheaper per ml, so a price is left out when it breaks that badly:
#  - a smaller bottle more than 15% cheaper per ml than the larger size  (below SMALLER_MAX x larger)
#  - a larger bottle under 0.4x the per-ml price of the smaller size     (below LARGER_MIN x smaller)
SMALLER_MAX = float(os.environ.get("SMALLER_MAX", "0.85"))
LARGER_MIN = float(os.environ.get("LARGER_MIN", "0.4"))
# A size's "shops" (what the extension's deal label uses) stays empty until this many distinct
# installs reported the kept prices. Raise it later without an extension update.
LABEL_MIN_INSTALLS = int(os.environ.get("LABEL_MIN_INSTALLS", "1"))

# Rough EUR value of one unit, only for the absolute sanity bounds below (not for display).
EUR_PER = {"EUR": 1, "USD": 0.9, "GBP": 1.15, "CHF": 1.05, "PLN": 0.23, "SEK": 0.087, "DKK": 0.134,
           "NOK": 0.085, "CZK": 0.04, "RON": 0.2, "HUF": 0.0025, "TRY": 0.025, "RUB": 0.01, "UAH": 0.022,
           "AUD": 0.6, "CAD": 0.66, "JPY": 0.006, "KRW": 0.00065}
PER_ML_EUR = (0.03, 150.0)   # nothing sells below 3 cents or above 150 euro per ml

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")
HOST_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def load_shops():
    with open(SHOPS_FILE, encoding="utf-8") as f:
        return {l.strip().lower() for l in f if l.strip() and not l.startswith("#")}


SHOPS = load_shops()


def load_salt():
    try:
        with open(SALT_PATH, "rb") as f:
            return f.read()
    except FileNotFoundError:
        salt = secrets.token_bytes(32)
        with open(SALT_PATH, "wb") as f:
            f.write(salt)
        return salt


SALT = b""


def db():
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS reports (
            perfume_id INTEGER NOT NULL, ml REAL NOT NULL, price REAL NOT NULL, currency TEXT NOT NULL,
            per_ml REAL NOT NULL, shop TEXT NOT NULL, install TEXT NOT NULL, t INTEGER NOT NULL,
            UNIQUE (install, perfume_id, shop, ml))""")
        con.execute("CREATE INDEX IF NOT EXISTS reports_lookup ON reports (perfume_id, currency, t)")
        # Price history for "lowest in 30 days": one row per install, perfume, shop, size, currency and
        # UTC day, holding the lowest price of that day. `reports` keeps only each install's latest price.
        new = not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_lows'").fetchone()
        con.execute("""CREATE TABLE IF NOT EXISTS daily_lows (
            install TEXT NOT NULL, perfume_id INTEGER NOT NULL, shop TEXT NOT NULL, ml REAL NOT NULL,
            currency TEXT NOT NULL, day TEXT NOT NULL, price REAL NOT NULL, t INTEGER NOT NULL,
            PRIMARY KEY (install, perfume_id, shop, ml, currency, day))""")
        con.execute("CREATE INDEX IF NOT EXISTS daily_lows_lookup ON daily_lows (perfume_id, currency, day)")
        # Product facts for the open perfume database: one row per install, shop, perfume and UTC day.
        # Nothing about the user: no IP, no page address; the install id only as the salted hash.
        con.execute("""CREATE TABLE IF NOT EXISTS facts (
            install TEXT NOT NULL, day TEXT NOT NULL, shop TEXT NOT NULL, perfume_id INTEGER,
            brand TEXT NOT NULL, name TEXT NOT NULL, conc TEXT NOT NULL DEFAULT '', gender TEXT NOT NULL DEFAULT '', lang TEXT,
            sizes TEXT NOT NULL, gtins TEXT NOT NULL, notes TEXT NOT NULL, families TEXT NOT NULL,
            PRIMARY KEY (install, shop, brand, name, conc, gender, day))""")
        con.execute("CREATE INDEX IF NOT EXISTS facts_day ON facts (day)")
        # Shops people added themselves (opt-in, domain only), to find shops worth adding to the built-in list.
        # One row per domain and install; like facts, the install hash is replaced after RETENTION_DAYS.
        con.execute("""CREATE TABLE IF NOT EXISTS shop_suggestions (
            domain TEXT NOT NULL, install TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (domain, install))""")
        catalog.init(con)
        pages.init(con)
        votes.init(con)
        notephotos.init(con)
        if new:   # one-time migration: start the history with the prices we have
            con.execute("""INSERT OR IGNORE INTO daily_lows (install, perfume_id, shop, ml, currency, day, price, t)
                SELECT install, perfume_id, shop, ml, currency, date(t / 1000, 'unixepoch'), price, t FROM reports""")


def purge_old():
    cutoff = now_ms() - RETENTION_DAYS * 86400_000
    with db() as con:
        con.execute("DELETE FROM reports WHERE t < ?", (cutoff,))
        con.execute("DELETE FROM daily_lows WHERE day < ?", (day_of(cutoff),))
        # Facts stay (they're about perfumes, not people), but after RETENTION_DAYS the install hash is
        # replaced by a random value per row, so old rows can't be linked to each other or to an install.
        con.execute("""UPDATE facts SET install = 'old-' || lower(hex(randomblob(12)))
            WHERE day < ? AND install NOT LIKE 'old-%'""", (day_of(cutoff),))
        con.execute("""UPDATE shop_suggestions SET install = 'old-' || lower(hex(randomblob(12)))
            WHERE day < ? AND install NOT LIKE 'old-%'""", (day_of(cutoff),))
        votes.purge(con)


def day_of(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def now_ms():
    return int(time.time() * 1000)


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.hits = defaultdict(deque)

    def allow(self, key, limits):
        """Sliding windows; returns seconds to wait (0 = allowed, and the hit is counted)."""
        t = time.monotonic()
        with self.lock:
            q = self.hits[key]
            longest = max(w for w, _ in limits)
            while q and q[0] <= t - longest:
                q.popleft()
            for window, n in limits:
                recent = [x for x in q if x > t - window]
                if len(recent) >= n:
                    return int(recent[0] + window - t) + 1
            q.append(t)
            if len(self.hits) > 100_000:   # forget idle installs
                for k in [k for k, v in self.hits.items() if not v or v[-1] < t - longest]:
                    del self.hits[k]
            return 0


LIMITER = RateLimiter()


class Invalid(Exception):
    pass


def num(v, name, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not (lo <= v <= hi):
        raise Invalid(f"{name} must be a number between {lo} and {hi}")
    return float(v)


def shop_of(v):
    if not isinstance(v, str):
        raise Invalid("shop must be a string")
    s = v.strip().lower()
    if s.startswith("www."):
        s = s[4:]
    if len(s) > 100 or not HOST_RE.match(s):
        raise Invalid("shop must be a host name like douglas.nl")
    # Store the shop as its built-in domain (nl.example.com -> example.com).
    for d in (s, *[s.split(".", i)[-1] for i in range(1, s.count("."))]):
        if d in SHOPS:
            return d
    raise Invalid("shop is not one of the supported shops")


def validate(body):
    if not isinstance(body, dict):
        raise Invalid("body must be a JSON object")
    extra = set(body) - {"perfumeId", "ml", "price", "currency", "shop"}
    if extra:
        raise Invalid("unknown fields: " + ", ".join(sorted(extra)))
    pid = body.get("perfumeId")
    if isinstance(pid, int) and not isinstance(pid, bool):
        pid = str(pid)
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise Invalid("perfumeId must be a Fragrantica perfume number")
    ml = num(body.get("ml"), "ml", 0.5, 1000)
    price = num(body.get("price"), "price", 0.01, 10_000_000)
    cur = body.get("currency")
    if cur not in EUR_PER:
        raise Invalid("currency must be one of " + ", ".join(sorted(EUR_PER)))
    per_eur = price / ml * EUR_PER[cur]
    if not (PER_ML_EUR[0] <= per_eur <= PER_ML_EUR[1]):
        raise Invalid("price per ml is not plausible")
    return int(pid), round(ml, 2), round(price, 2), cur, shop_of(body.get("shop"))


FACT_FIELDS = {"shop", "perfumeId", "brand", "name", "conc", "gender", "sizes", "gtins", "notes", "families", "lang"}
CONCS = {"extrait", "parfum", "edp", "edt", "edc"}
GTIN_RE = re.compile(r"^[0-9]{8,14}$")
LANG_RE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")


def text(v, name, max_len, required=False):
    if v is None and not required:
        return ""
    if not isinstance(v, str):
        raise Invalid(f"{name} must be a string")
    s = re.sub(r"\s+", " ", v).strip()
    if required and not s:
        raise Invalid(f"{name} is required")
    if len(s) > max_len:
        raise Invalid(f"{name} is longer than {max_len} characters")
    return s


def text_list(v, name, max_items, max_len):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > max_items:
        raise Invalid(f"{name} must be a list of at most {max_items} items")
    out = []
    for x in v:
        s = text(x, name, max_len)
        if s and s.lower() not in (o.lower() for o in out):
            out.append(s)
    return out


def validate_facts(body):
    if not isinstance(body, dict):
        raise Invalid("body must be a JSON object")
    extra = set(body) - FACT_FIELDS
    if extra:
        raise Invalid("unknown fields: " + ", ".join(sorted(extra)))
    pid = body.get("perfumeId")
    if isinstance(pid, int) and not isinstance(pid, bool):
        pid = str(pid)
    if pid is not None and (not isinstance(pid, str) or not ID_RE.match(pid)):
        raise Invalid("perfumeId must be a Fragrantica perfume number or null")
    conc = body.get("conc")
    if conc is not None and conc not in CONCS:
        raise Invalid("conc must be one of " + ", ".join(sorted(CONCS)) + " or null")
    gender = body.get("gender")
    if gender is not None and gender not in ("m", "f", "u"):
        raise Invalid("gender must be m, f, u or null")
    lang = body.get("lang")
    if lang is not None and (not isinstance(lang, str) or not LANG_RE.match(lang)):
        raise Invalid("lang must look like nl or nl-nl")
    sizes = body.get("sizes") or []
    if not isinstance(sizes, list) or len(sizes) > 8:
        raise Invalid("sizes must be a list of at most 8 numbers")
    sizes = sorted({round(num(x, "sizes", 0.5, 1000), 1) for x in sizes})
    gtins = body.get("gtins") or []
    if not isinstance(gtins, list) or len(gtins) > 8 or not all(isinstance(g, str) and GTIN_RE.match(g) for g in gtins):
        raise Invalid("gtins must be a list of at most 8 barcodes (8-14 digits)")
    notes = body.get("notes") or {}
    if not isinstance(notes, dict) or set(notes) - {"top", "heart", "base", "mentioned"}:
        raise Invalid("notes must be an object with top, heart, base and mentioned lists")
    notes = {k: text_list(notes.get(k), "notes", 15, 40) for k in ("top", "heart", "base")}
    # Notes a brand's own site names in its text, without a tier (catalog.OFFICIAL_SITES; ignored for other shops).
    mentioned = text_list(notes_in.get("mentioned"), "notes", 20, 40) if isinstance(notes_in := body.get("notes"), dict) else []
    if mentioned:
        notes["mentioned"] = mentioned
    return {
        "shop": shop_of(body.get("shop")),
        "perfume_id": int(pid) if pid else None,
        "brand": text(body.get("brand"), "brand", 80, required=True),
        "name": text(body.get("name"), "name", 120, required=True),
        "conc": conc or "",
        "gender": gender or "",
        "lang": lang,
        "sizes": sizes,
        "gtins": sorted({g.zfill(13)[-13:] if len(g) <= 13 else g for g in gtins}),
        "notes": notes,
        "families": text_list(body.get("families"), "families", 6, 40),
    }


def add_facts(install, f):
    with db() as con:
        con.execute("""INSERT INTO facts (install, day, shop, perfume_id, brand, name, conc, gender, lang,
                sizes, gtins, notes, families) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (install, shop, brand, name, conc, gender, day) DO UPDATE SET
              perfume_id=excluded.perfume_id, lang=excluded.lang, sizes=excluded.sizes,
              gtins=excluded.gtins, notes=excluded.notes, families=excluded.families""",
                    (install, day_of(now_ms()), f["shop"], f["perfume_id"], f["brand"], f["name"], f["conc"],
                     f["gender"], f["lang"], json.dumps(f["sizes"]), json.dumps(f["gtins"]),
                     json.dumps(f["notes"], ensure_ascii=False), json.dumps(f["families"], ensure_ascii=False)))


_facts_stats = {"t": 0, "data": None}


def add_suggestions(key, body):
    """POST /shops/suggest {"domains": ["armani.com", …]}: shops this install added itself (opt-in). Only domain
    names; built-in shops are ignored. Returns how many were new for this install."""
    domains = body.get("domains") if isinstance(body, dict) else None
    if not isinstance(domains, list) or not 1 <= len(domains) <= 20:
        raise Invalid("domains must be a list of 1-20 host names")
    clean = set()
    for d in domains:
        if not isinstance(d, str):
            raise Invalid("domains must be host names")
        s = d.strip().lower().removeprefix("www.")
        if len(s) > 100 or not HOST_RE.match(s):
            raise Invalid("domains must be host names like example.com")
        if not any(p in SHOPS for p in (s, *[s.split(".", i)[-1] for i in range(1, s.count("."))])):
            clean.add(s)
    day = day_of(now_ms())
    with db() as con:
        before = con.total_changes
        con.executemany("INSERT OR IGNORE INTO shop_suggestions (domain, install, day) VALUES (?,?,?)",
                        [(d, key, day) for d in sorted(clean)])
        return con.total_changes - before


def shop_suggestions(min_installs=1):
    """Domains people added themselves, most installs first (for the nightly review list)."""
    with db() as con:
        return [tuple(r) for r in con.execute("SELECT domain, COUNT(*) FROM shop_suggestions GROUP BY domain HAVING COUNT(*) >= ? "
                                              "ORDER BY COUNT(*) DESC, domain", (min_installs,))]


def contribution(key):
    """What one install's shared facts (last RETENTION_DAYS; older rows no longer carry the install) did for the
    database: GET /facts/mine, for the popup's "You helped confirm …". Only reads; the perfumes are found the
    same way as /catalog/lookup, and a note counts when this install named it and it is confirmed now."""
    with db() as con:
        rows = con.execute("SELECT brand, name, conc, gender, gtins, notes FROM facts WHERE install=?", (key,)).fetchall()
        perfumes, notes = {}, set()
        for r in rows:
            p = catalog.lookup(con, json.loads(r["gtins"] or "[]")[:8], r["brand"], r["name"], r["conc"], r["gender"])
            if not p:
                continue
            perfumes[p["id"]] = p
            mine = {catalog.note_key(n) for tier in json.loads(r["notes"] or "{}").values() for n in tier}
            for tier in p["notes"].values():
                for n in tier:
                    if n["confirmed"] and n["key"] in mine:
                        notes.add((p["id"], n["key"]))
    return {"shared": len(rows), "perfumes": len(perfumes), "notesConfirmed": len(notes),
            "withPage": sum(p["confirmedNotes"] >= pages.PAGE_MIN_CONFIRMED for p in perfumes.values()),
            "days": RETENTION_DAYS}


def facts_stats():
    if time.monotonic() - _facts_stats["t"] < 60 and _facts_stats["data"]:
        return _facts_stats["data"]
    since = day_of(now_ms() - 30 * 86400_000)
    with db() as con:
        q = lambda sql, *a: con.execute(sql, a).fetchone()[0]
        data = {
            "rows": q("SELECT COUNT(*) FROM facts"),
            "perfumes": q("SELECT COUNT(*) FROM (SELECT 1 FROM facts GROUP BY lower(brand), lower(name), conc)"),
            # Installs of the last RETENTION_DAYS: older rows have a random 'old-…' value per row instead.
            "installs": q("SELECT COUNT(DISTINCT install) FROM facts WHERE install NOT LIKE 'old-%'"),
            "withNotes": q("""SELECT COUNT(*) FROM facts WHERE json_array_length(notes, '$.top')
                + json_array_length(notes, '$.heart') + json_array_length(notes, '$.base') > 0"""),
            "gtins": q("SELECT COUNT(DISTINCT value) FROM facts, json_each(facts.gtins)"),
            "shops": {r[0]: r[1] for r in con.execute(
                "SELECT shop, COUNT(*) FROM facts GROUP BY shop ORDER BY COUNT(*) DESC LIMIT 50")},
            "perDay": {r[0]: r[1] for r in con.execute(
                "SELECT day, COUNT(*) FROM facts WHERE day >= ? GROUP BY day ORDER BY day", (since,))},
        }
    _facts_stats.update(t=time.monotonic(), data=data)
    return data


def page_prices(fragrantica_id, visitor=None, region=None):
    """Price stats for a perfume page (pages.py) plus "history": per size the lowest price of each day in the window
    (all shown shops together), for the price chart. Only the prices for one country (regions.pick: the visitor's,
    the one picked in the menu, or the eurozone), never mixed currencies; "region" says which, and where else there
    are prices. Without a visitor country (tests, the API): the most-reported currency, as before."""
    pid = int(fragrantica_id)
    since = now_ms() - WINDOW_DAYS * 86400_000
    with db() as con:
        available = {}
        for shop, cur in con.execute("SELECT DISTINCT shop, currency FROM reports WHERE perfume_id=? AND t>=?", (pid, since)):
            available.setdefault(regions.country_of(shop, cur), cur)
    countries, kind = regions.pick(available, visitor, region)
    region_info = {"kind": kind, "want": (region or visitor or "").upper(), "shown": sorted(countries or available),
                   "available": available}
    if kind == "none":
        return {"perfumeId": str(pid), "currency": None, "count": 0, "sizes": [], "history": {}, "region": region_info}
    cur = available[next(iter(countries))] if countries else None
    out = stats(pid, cur, countries)
    cur = out.get("currency")
    region_info["shown"] = sorted(countries) if countries else sorted(c for c, x in available.items() if x == cur)
    history = defaultdict(list)
    if cur:
        lows = defaultdict(lambda: None)
        with db() as con:
            for ml, day, shop, low in con.execute(
                    "SELECT ml, day, shop, MIN(price) FROM daily_lows WHERE perfume_id=? AND currency=? AND day>=? "
                    "GROUP BY ml, day, shop", (pid, cur, day_of(since))):
                if countries is None or regions.country_of(shop, cur) in countries:
                    k = (ml, day)
                    lows[k] = low if lows[k] is None else min(lows[k], low)
        for (ml, day) in sorted(lows):
            history[ml].append((day, round(lows[(ml, day)], 2)))
    out["history"] = dict(history)
    out["region"] = region_info
    return out


def stats(pid, currency=None, countries=None):
    """countries: only prices for these countries (regions.country_of), e.g. {"NL"}; None: all of the currency."""
    since = now_ms() - WINDOW_DAYS * 86400_000
    with db() as con:
        curs = [r[0] for r in con.execute(
            "SELECT currency FROM reports WHERE perfume_id=? AND t>=? GROUP BY currency ORDER BY COUNT(*) DESC",
            (pid, since))]
        cur = currency if currency in curs else (curs[0] if curs and not currency else currency)
        all_rows = con.execute(
            "SELECT ml, price, per_ml, shop, install, t FROM reports WHERE perfume_id=? AND currency=? AND t>=?",
            (pid, cur, since)).fetchall() if cur else []
        if countries is not None:
            all_rows = [r for r in all_rows if regions.country_of(r["shop"], cur) in countries]
        history = defaultdict(list)   # (ml, shop) -> daily lowest prices in the window
        for ml, shop, price in (con.execute(
                "SELECT ml, shop, price FROM daily_lows WHERE perfume_id=? AND currency=? AND day>=?",
                (pid, cur, day_of(since))) if cur else []):
            if countries is None or regions.country_of(shop, cur) in countries:
                history[(ml, shop)].append(price)
    out = {"perfumeId": str(pid), "currency": cur, "currencies": curs, "days": WINDOW_DAYS, "count": len(all_rows)}
    if not all_rows:
        return out
    r4 = lambda x: round(x, 4)

    # Per size: one value per shop (that shop's median), then drop outlier shops against their median.
    by_size = defaultdict(lambda: defaultdict(list))   # ml -> shop -> rows
    for r in all_rows:
        by_size[r["ml"]][r["shop"]].append(r)
    # Pass 1: sizes with 3+ shops, against the median of their own shops.
    values, kept_by = {}, {}
    for ml, shops in by_size.items():
        value = {s: statistics.median(r["per_ml"] for r in rs) for s, rs in shops.items()}
        kept = dict(value)
        if len(value) >= OUTLIER_MIN_SHOPS:
            base = statistics.median(value.values())
            kept = {s: v for s, v in value.items() if OUTLIER_LOW * base <= v <= OUTLIER_HIGH * base}
        values[ml], kept_by[ml] = value, kept
    # Pass 2: neighbouring sizes, using only other shops' prices (as kept by pass 1) as reference.
    def neighbour(ml, shop, sizes_in_order):
        """Median of other shops' values at the nearest size in that order that has any."""
        for m in sizes_in_order:
            other = [v for s, v in pass1[m].items() if s != shop]
            if other:
                return statistics.median(other)
        return None
    order = sorted(by_size)
    pass1 = {ml: dict(k) for ml, k in kept_by.items()}   # judge against pass-1 values, not each other's results
    for i, ml in enumerate(order):
        keep = {}
        for shop, v in pass1[ml].items():
            larger = neighbour(ml, shop, order[i + 1:])
            smaller = neighbour(ml, shop, reversed(order[:i]))
            if (larger is not None and v < SMALLER_MAX * larger) or (smaller is not None and v < LARGER_MIN * smaller):
                continue
            keep[shop] = v
        kept_by[ml] = keep

    sizes, dropped = [], set()   # dropped: (ml, shop) pairs left out everywhere
    for ml, shops in sorted(by_size.items()):
        value, kept = values[ml], kept_by[ml]
        dropped.update((ml, s) for s in value if s not in kept)
        kept_rows = [r for s in kept for r in shops[s]]
        installs = len({r["install"] for r in kept_rows})
        show = installs >= LABEL_MIN_INSTALLS
        sizes.append({
            "ml": ml, "count": len(kept_rows),
            "median": r4(statistics.median(r["per_ml"] for r in kept_rows)) if kept_rows else None,
            # The extension compares a page with the *other* shops in here (one value per shop, so one
            # busy shop doesn't outweigh the rest). Empty until enough distinct installs back it up.
            "shops": {s: r4(v) for s, v in sorted(kept.items())} if show else {},
            # Lowest full price (not per ml) each kept shop had for this size in the last 30 days, from the
            # daily history; same visibility rule as "shops".
            "lows": lows_for(ml, kept, shops, kept_rows, history) if show else {},
            "installs": installs, "outliers": len(value) - len(kept),
        })

    rows = [r for r in all_rows if (r["ml"], r["shop"]) not in dropped]
    per = [r["per_ml"] for r in rows]
    if not per:   # everything was left out
        out.update({"count": 0, "shopCount": 0, "sizes": sizes, "cheapest": []})
        return out
    best = {}
    for r in rows:
        b = best.get(r["shop"])
        if b is None or r["per_ml"] < b["per_ml"] or (r["per_ml"] == b["per_ml"] and r["t"] > b["t"]):
            best[r["shop"]] = r
    out.update({
        "count": len(rows),
        "median": r4(statistics.median(per)), "min": r4(min(per)), "max": r4(max(per)),
        "shopCount": len(best),
        "sizes": sizes,
        "cheapest": [{"shop": r["shop"], "perMl": r4(r["per_ml"]), "ml": r["ml"], "price": r["price"], "t": r["t"]}
                     for r in sorted(best.values(), key=lambda r: r["per_ml"])[:5]],
    })
    return out


def lows_for(ml, kept, shops, kept_rows, history):
    """Per kept shop: the lowest daily price in the window. A past day only counts if its per-ml price is
    at least OUTLIER_LOW x the size's current median, so an old misreading (later corrected, so no longer
    in `reports`) can't stay on show as "lowest in 30 days" for a month."""
    floor = OUTLIER_LOW * statistics.median(r["per_ml"] for r in kept_rows) * ml
    out = {}
    for s in sorted(kept):
        current = min(r["price"] for r in shops[s])          # always valid: it passed the filters
        past = [p for p in history.get((ml, s), []) if p >= floor]
        out[s] = round(min([current] + past), 2)
    return out


def add_report(install, pid, ml, price, cur, shop):
    # No outlier check here: odd prices are stored and only left out in stats() (see OUTLIER_LOW).
    per, t = price / ml, now_ms()
    with db() as con:
        con.execute("""INSERT INTO reports (perfume_id, ml, price, currency, per_ml, shop, install, t)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT (install, perfume_id, shop, ml) DO UPDATE SET
              price=excluded.price, currency=excluded.currency, per_ml=excluded.per_ml, t=excluded.t""",
                    (pid, ml, price, cur, per, shop, install, t))
        # SET expressions see the old row, so both use the stored price for the comparison.
        con.execute("""INSERT INTO daily_lows (install, perfume_id, shop, ml, currency, day, price, t)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT (install, perfume_id, shop, ml, currency, day) DO UPDATE SET
              t = CASE WHEN excluded.price < price THEN excluded.t ELSE t END,
              price = MIN(price, excluded.price)""",
                    (install, pid, shop, ml, cur, day_of(t), price, t))


class Handler(BaseHTTPRequestHandler):
    server_version = "fragrance-api"
    sys_version = ""
    timeout = 10                 # drop slow clients
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # no client addresses in the logs
        pass

    def log_request(self, code="-", size="-"):
        print(f"{self.command} {urlsplit(self.path).path} {code}", flush=True)

    def cors(self):
        origin = self.headers.get("Origin")
        if self.command == "GET":
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def reply(self, code, obj, headers=()):
        data = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers:
            self.send_header(k, v)
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Install-Id")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/maintenance/week":
            # What the nightly job fixed and left for a person (note and perfume names, counts): the Worker mails it weekly.
            return self.reply(200, maintenance.week())
        if u.path == "/health":
            return self.reply(200, {"ok": True})
        if u.path == "/facts/mine":
            # The install id is sent only by installs that share (it's made when sharing is turned on). Read-only:
            # nothing is stored or logged (log_request writes the path only).
            install = (self.headers.get("X-Install-Id") or "").lower()
            if not UUID_RE.match(install):
                return self.reply(400, {"error": "X-Install-Id must be a random UUID"})
            key = hashlib.sha256(SALT + install.encode()).hexdigest()[:32]
            wait = LIMITER.allow("m:" + key, [(600, 30)])
            if wait:
                return self.reply(429, {"error": "too many requests"}, [("Retry-After", str(wait))])
            return self.reply(200, contribution(key), [("Cache-Control", "private, max-age=300")])
        if u.path == "/facts/stats":
            return self.reply(200, facts_stats(), [("Cache-Control", "public, max-age=60")])
        if u.path.startswith("/catalog/"):
            return self.catalog_get(u)
        if u.path.split("/")[1] in ("database", "perfume", "note", "notes", "brand", "photo", "assets", "sitemap.xml") or u.path.split("/")[1] in pages.LANGS:
            return self.page_get(u)
        m = re.fullmatch(r"/prices/([0-9]+)", u.path)
        if not m or not ID_RE.match(m.group(1)):
            return self.reply(404, {"error": "not found"})
        cur = (parse_qs(u.query).get("currency") or [None])[0]
        if cur is not None and cur not in EUR_PER:
            return self.reply(400, {"error": "unknown currency"})
        self.reply(200, stats(int(m.group(1)), cur), [("Cache-Control", "public, max-age=300")])

    def send(self, code, data, ctype, cache="public, max-age=600", headers=()):
        if isinstance(data, str):
            data = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache)
        if ctype.startswith("text/html"):
            # Pages run no scripts: only our CSS, the fonts and our own images.
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.bunny.net; "
                             "font-src https://fonts.bunny.net; img-src 'self' https://fragrancenotes.app; form-action 'self'; "
                             "base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def page_get(self, u):
        """The public web pages (pages.py). Read-only; nothing about the visitor is stored."""
        html_t = "text/html; charset=utf-8"
        path = u.path
        if path == "/assets/pages.css":
            return self.send(200, pages.CSS, "text/css; charset=utf-8", "public, max-age=31536000, immutable")
        if path.startswith("/photo/"):
            f = notephotos.image_file(path[9:]) if path.startswith("/photo/n/") else pages.image_file(path[7:])
            if not f:
                return self.send(404, "not found", "text/plain; charset=utf-8")
            return self.send(200, f[0], f[1], "public, max-age=2592000")
        with db() as con:
            if path == "/sitemap.xml":
                return self.send(200, pages.sitemap(con), "application/xml; charset=utf-8", "public, max-age=3600")
            # Someone who voted before (fn_voter cookie) gets the page with their own vote filled in: never cached.
            token = self.voter_token()
            # Prices for the visitor's country: the Worker adds Cloudflare's country of the request as ?vc=NL (and
            # caches a copy per country); ?region= is the visitor's own choice in the price menu. Neither is stored.
            q = parse_qs(u.query)
            code_re = re.compile(r"[A-Z]{2}|" + regions.ZONE)
            vc = next((v for v in q.get("vc", []) if code_re.fullmatch(v)), None)
            region = next((v for v in q.get("region", []) if code_re.fullmatch(v)), None)
            code, body, location = pages.route(con, path, u.query, lambda fid: page_prices(fid, vc, region),
                                               votes.voter_hash(SALT, token) if token else None)
        if location:
            return self.send(301, "", html_t, headers=[("Location", location)])
        cache = "public, max-age=300" if code != 200 or path.endswith("/search") else "public, max-age=600"
        if "vote=" in u.query or token:   # right after voting, or with the voter's own answers: never cached
            cache = "private, no-store"
        return self.send(code, body, html_t, cache)

    def catalog_get(self, u):
        cache = [("Cache-Control", "public, max-age=300")]
        if u.path == "/catalog/stats":
            with db() as con:
                return self.reply(200, catalog.stats(con), cache)
        if u.path == "/catalog/search":
            q = (parse_qs(u.query).get("q") or [""])[0][:100]
            with db() as con:
                return self.reply(200, {"results": catalog.search(con, q)}, cache)
        if u.path == "/catalog/lookup":
            # The extension asks this for the perfume on a shop page ("own database first"). Anonymous: no
            # install id, nothing stored, and log_request writes only the path, never the query.
            q = parse_qs(u.query)
            one = lambda k, n: (q.get(k) or [""])[0][:n]
            gtins = [g for g in one("gtin", 200).split(",") if g][:8]
            with db() as con:
                p = catalog.lookup(con, gtins, one("brand", 80), one("name", 120), one("conc", 10), one("gender", 1))
            return self.reply(200, {"perfume": p}, cache)
        m = re.fullmatch(r"/catalog/perfume/([0-9a-f]{12})", u.path)
        if m:
            with db() as con:
                p = catalog.perfume(con, m.group(1))
            return self.reply(200, p, cache) if p else self.reply(404, {"error": "not found"})
        return self.reply(404, {"error": "not found"})

    def voter_token(self):
        """The fn_voter code from the Cookie header (only set by voting), or ''."""
        for c in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = c.strip().partition("=")
            if k == "fn_voter" and re.fullmatch(r"[0-9a-f]{32}", v):
                return v
        return ""

    def vote_post(self, prefix, pid, raw):
        """A vote from the form on a perfume page (no JavaScript): stored, then back to the page (303).
        Only from the site itself (Origin), for any perfume in the catalog (back to its page, or to its rating page
        when it has no page yet), and rate-limited per voter, per visitor address (kept in memory only, never
        stored or logged) and overall."""
        lang = prefix.strip("/") if prefix.strip("/") in pages.LANGS else "en"
        if self.headers.get("Origin") not in VOTE_ORIGINS:
            return self.send(403, "Votes can only be sent from the perfume page.", "text/plain; charset=utf-8", "no-store")
        with db() as con:
            target = pages.vote_target(con, pid)
        if not target:
            return self.send(404, pages.not_found(lang), "text/html; charset=utf-8", "no-store")
        back = pages.P(lang, target)
        token = self.voter_token()
        new = not token
        if new:
            token = secrets.token_hex(16)
        voter = votes.voter_hash(SALT, token)
        addr = self.headers.get("X-Visitor-IP") or self.headers.get("CF-Connecting-IP") or ""
        checks = [("v:" + voter, [(3600, 40)]), ("v:*", [(3600, 3000)])]
        if addr:
            checks.append(("va:" + hashlib.sha256(SALT + addr.encode()).hexdigest()[:24], [(3600, 120)]))
        for k, lim in checks:
            if LIMITER.allow(k, lim):
                return self.send(303, "", "text/html; charset=utf-8", "no-store", [("Location", back + "?vote=busy#vote")])
        try:
            answers = votes.parse(parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True))
        except votes.Invalid as e:
            return self.send(303, "", "text/html; charset=utf-8", "no-store",
                             [("Location", back + ("?vote=own" if str(e) == "owns" else "?vote=empty") + "#vote")])
        with db() as con:
            votes.add(con, pid, voter, answers)
        headers = [("Location", back + "?vote=thanks#vote")]
        if new:
            headers.append(("Set-Cookie", f"fn_voter={token}; Path=/; Max-Age={votes.VOTE_KEEP_DAYS * 86400}; "
                                          "HttpOnly; Secure; SameSite=Lax"))
        return self.send(303, "", "text/html; charset=utf-8", "no-store", headers)

    def do_POST(self):
        self.close_connection = True   # never reuse a connection whose body we may not have read
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        # Read (or drain) the body first, so an early error reply isn't lost to a connection reset.
        raw = self.rfile.read(min(max(length, 0), 65536))
        path = urlsplit(self.path).path
        limit = MAX_FACTS_BODY if path == "/facts" else MAX_BODY
        if not (0 < length <= limit):
            return self.reply(413 if length > limit else 400, {"error": f"body must be 1-{limit} bytes"})
        m = VOTE_PATH.fullmatch(path)
        if m:
            return self.vote_post(m.group(1) or "", m.group(2), raw)
        if path not in ("/prices", "/facts", "/shops/suggest"):
            return self.reply(404, {"error": "not found"})
        if self.headers.get("Origin") and not origin_ok(self.headers.get("Origin")):
            return self.reply(403, {"error": "origin not allowed"})
        install = (self.headers.get("X-Install-Id") or "").lower()
        if not UUID_RE.match(install):
            return self.reply(400, {"error": "X-Install-Id must be a random UUID"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.reply(415, {"error": "use application/json"})
        key = hashlib.sha256(SALT + install.encode()).hexdigest()[:32]
        if path == "/shops/suggest":
            wait = LIMITER.allow("s:" + key, [(86400, 20)]) or LIMITER.allow("s:*", [(3600, 2000)])
            if wait:
                return self.reply(429, {"error": "too many reports"}, [("Retry-After", str(wait))])
            try:
                n = add_suggestions(key, json.loads(raw))
            except Invalid as e:
                return self.reply(422, {"error": str(e)})
            except ValueError:
                return self.reply(400, {"error": "invalid JSON"})
            return self.reply(201, {"ok": True, "new": n})
        if path == "/facts":
            for k, lim in (("f:" + key, FACT_LIMITS), ("f:*", [GLOBAL_FACT_LIMIT])):
                wait = LIMITER.allow(k, lim)
                if wait:
                    return self.reply(429, {"error": "too many reports"}, [("Retry-After", str(wait))])
            try:
                add_facts(key, validate_facts(json.loads(raw)))
            except Invalid as e:
                return self.reply(422, {"error": str(e)})
            except ValueError:
                return self.reply(400, {"error": "invalid JSON"})
            return self.reply(201, {"ok": True})
        for k, lim in ((key, LIMITS), ("*", [GLOBAL_LIMIT])):
            wait = LIMITER.allow(k, lim)
            if wait:
                return self.reply(429, {"error": "too many reports"}, [("Retry-After", str(wait))])
        try:
            add_report(key, *validate(json.loads(raw)))
        except Invalid as e:
            return self.reply(422, {"error": str(e)})
        except ValueError:   # includes JSON and UTF-8 decode errors
            return self.reply(400, {"error": "invalid JSON"})
        self.reply(201, {"ok": True})


def purge_loop():
    while True:
        time.sleep(3600)
        try:
            purge_old()
        except Exception as e:  # keep serving even if a purge fails
            print("purge failed:", e, flush=True)


def obf_loop():
    """Import Open Beauty Facts once every OBF_EVERY seconds (default a week), then rebuild the catalog.
    The last import time is stored, so restarts don't download it again; after a failed import (network
    error, or an export without perfumes) it waits at least a day (obf.RETRY_AFTER). OBF_EVERY=0 turns it off."""
    every = int(os.environ.get("OBF_EVERY", str(7 * 86400)))
    if every <= 0:
        return
    time.sleep(int(os.environ.get("OBF_DELAY", "600")))   # let the API settle after a restart
    while True:
        try:
            with db() as con:
                due = catalog.obf.due(con, every)
            if due:
                with db() as con:
                    lines, kept = catalog.obf.run(con)
                    n = catalog.build(con)
                print(f"open beauty facts: {kept} perfumes from {lines} products; catalog {n} perfumes", flush=True)
        except Exception as e:  # keep serving; obf.due waits a day before the next download
            print("open beauty facts import failed:", e, flush=True)
        time.sleep(3600)


def catalog_loop():
    """Rebuild the open perfume database from the collected facts every CATALOG_EVERY seconds."""
    every = int(os.environ.get("CATALOG_EVERY", "3600"))
    while True:
        try:
            with db() as con:
                n = catalog.build(con)
            print(f"catalog rebuilt: {n} perfumes", flush=True)
            if os.environ.get("PAGE_IMAGES", "1") != "0":
                with db() as con:
                    got = pages.refresh_images(con)
                if got:
                    print(f"pages: {got} new bottle photos", flush=True)
                # Note photos from Wikimedia Commons (free licences only, see notephotos.py).
                with db() as con:
                    got = notephotos.refresh(con, pages.index(con)["notes"])
                if got:
                    print(f"pages: {got} new note photos", flush=True)
        except Exception as e:  # keep serving even if a rebuild fails
            print("catalog rebuild failed:", e, flush=True)
        time.sleep(every)


def make_server(port=PORT):
    global SALT
    SALT = load_salt()
    init_db()
    purge_old()
    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


if __name__ == "__main__":
    srv = make_server()
    srv.daemon_threads = True
    threading.Thread(target=purge_loop, daemon=True).start()
    threading.Thread(target=catalog_loop, daemon=True).start()
    threading.Thread(target=obf_loop, daemon=True).start()
    print(f"fragrance-api listening on :{PORT}, {len(SHOPS)} shops", flush=True)
    srv.serve_forever()
